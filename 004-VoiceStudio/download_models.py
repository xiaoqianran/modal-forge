from __future__ import annotations

import os
from pathlib import Path

import modal

"""CPU-only model cache manager for VoiceStudio.

Examples:
  uv run modal run download_models.py  # all catalogue models
  uv run modal run download_models.py --list
  uv run modal run download_models.py --all --list
  uv run modal run download_models.py --all --check
  uv run modal run download_models.py --parallel 4
"""

app = modal.App("modal-forge-004-voicestudio-download")
volume = modal.Volume.from_name("modal-forge", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface-secret")
image = (
    modal.Image.from_registry("ghcr.io/debpalash/voicestudio:stable")
    .entrypoint([])
    .env({
        "HF_HOME": "/app/omnivoice_data/huggingface",
        "HF_HUB_DISABLE_XET": "1",
    })
)
DATA = "/app/omnivoice_data"
CACHE = Path(DATA) / "huggingface" / "hub"
DEFAULT_REPO = "k2-fsa/OmniVoice"


def _catalog():
    import yaml

    path = "/app/backend/config/models.yaml"
    with open(path, encoding="utf-8") as handle:
        rows = yaml.safe_load(handle)["models"]
    repos = {}
    for row in rows:
        repo = row["repo_id"]
        if repo not in repos:
            repos[repo] = {
                "repo_id": repo,
                "label": row.get("label", repo),
                "size_gb": float(row.get("size_gb") or 0),
                "required": bool(row.get("required")),
                "patterns": row.get("allow_patterns") or None,
            }
        else:
            # More than one catalogue package can point at the same HF repo.
            # A full-repository entry takes precedence over restricted packages.
            existing = repos[repo]
            patterns = row.get("allow_patterns") or None
            if patterns is None or existing["patterns"] is None:
                existing["patterns"] = None
            else:
                existing["patterns"] = sorted(set(existing["patterns"] + patterns))
            existing["size_gb"] += float(row.get("size_gb") or 0)
            existing["required"] |= bool(row.get("required"))
    return list(repos.values())


def _cached(repo):
    """Fast local cache check; no remote HF network requests or byte hashing."""
    root = CACHE / ("models--" + repo.replace("/", "--")) / "snapshots"
    if not root.is_dir():
        return False
    return any(p.is_file() and p.stat().st_size for rev in root.iterdir()
               if rev.is_dir() for p in rev.rglob("*"))


@app.function(image=image, cpu=1, memory=2048, timeout=180,
              volumes={DATA: volume.with_mount_options(sub_path="/004-VoiceStudio")})
def inspect_models(all_models: bool):
    volume.reload()
    entries = [m for m in _catalog() if all_models or m["repo_id"] == DEFAULT_REPO]
    for item in entries:
        item["cached"] = _cached(item["repo_id"])
    return entries




def pack_shards(items: list[dict], count: int) -> list[list[dict]]:
    """LPT partitioning, balancing total byte sizes across containers."""
    bins = [[] for _ in range(min(count, len(items)))]
    loads = [0] * len(bins)
    for item in sorted(items, key=lambda x: -x["size"]):
        i = min(range(len(bins)), key=loads.__getitem__)
        bins[i].append(item)
        loads[i] += item["size"]
    return bins


@app.function(image=image, cpu=2, memory=4096, timeout=1800, secrets=[hf_secret],
              volumes={DATA: volume.with_mount_options(sub_path="/004-VoiceStudio")})
def manifest(models: list[dict]):
    """Query pinned HF metadata once and prepare a complete per-file manifest."""
    import fnmatch
    from huggingface_hub import HfApi

    api = HfApi(token=os.getenv("HF_TOKEN") or None)
    entries = []
    for m in models:
        repo = m["repo_id"]
        info = api.model_info(repo, files_metadata=True)
        patterns = m["patterns"]
        for f in info.siblings or []:
            filename = f.rfilename
            if patterns and not any(fnmatch.fnmatch(filename, pat) for pat in patterns):
                continue
            size = f.size
            digest = f.lfs.sha256 if f.lfs else f.blob_id
            if size is None or not digest:
                raise ValueError(f"Missing metadata for {repo}/{filename}")
            entries.append({"repo": repo, "revision": info.sha, "name": filename,
                            "size": int(size), "digest": digest,
                            "algorithm": "sha256" if f.lfs else "sha1"})
    return entries


def _verify(path: Path, item: dict) -> bool:
    import hashlib
    if not path.is_file() or path.stat().st_size != item["size"]:
        return False
    digest = hashlib.new(item["algorithm"])
    if item["algorithm"] == "sha1":
        digest.update(f"blob {item['size']}\0".encode())
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == item["digest"]


def _blob(item: dict, stage: str = "") -> Path:
    repo = "models--" + item["repo"].replace("/", "--")
    root = CACHE if not stage else Path(DATA) / ".download-shards" / stage
    return root / repo / "blobs" / item["digest"]


@app.function(image=image, cpu=2, memory=4096, timeout=900,
              volumes={DATA: volume.with_mount_options(sub_path="/004-VoiceStudio")})
def missing_files(items: list[dict]):
    volume.reload()
    return [i for i in items if not _verify(_blob(i), i)]


@app.function(image=image, cpu=4, memory=4096, timeout=7200, secrets=[hf_secret],
              volumes={DATA: volume.with_mount_options(sub_path="/004-VoiceStudio")})
def fetch_shard(payload: dict):
    """Download disjoint files to staging; do not touch public cache."""
    from concurrent.futures import ThreadPoolExecutor
    from huggingface_hub import hf_hub_download

    volume.reload()
    failures = []
    stage = payload["stage"]

    def fetch(item):
        if _verify(_blob(item), item):
            return
        target = _blob(item, stage)
        if _verify(target, item):
            return
        for attempt in range(2):
            try:
                hf_hub_download(
                    repo_id=item["repo"], filename=item["name"],
                    revision=item["revision"],
                    cache_dir=str(Path(DATA) / ".download-shards" / stage),
                    headers={"Accept-Encoding": "identity"},
                    force_download=attempt > 0,
                    token=os.getenv("HF_TOKEN") or None,
                )
                if not _verify(target, item):
                    raise ValueError("download hash verification failed")
                return
            except Exception:
                if attempt:
                    raise

    def guarded(item):
        try:
            fetch(item)
        except Exception as exc:
            failures.append(f"{item['repo']}/{item['name']}: {exc}")

    with ThreadPoolExecutor(max_workers=min(payload["workers"], len(payload["items"]))) as executor:
        list(executor.map(guarded, payload["items"]))
    volume.commit()
    return {"stage": stage, "errors": failures, "files": len(payload["items"])}


@app.function(image=image, cpu=2, memory=8192, timeout=7200,
              volumes={DATA: volume.with_mount_options(sub_path="/004-VoiceStudio")})
def publish(items: list[dict], stage: str):
    """Single publisher; commit weights before publishing snapshots and refs."""
    import os as _os
    import shutil

    volume.reload()
    root = Path(DATA) / ".download-shards" / stage
    for item in items:
        dest = _blob(item)
        if not _verify(dest, item):
            source = _blob(item, stage)
            if not _verify(source, item):
                raise RuntimeError(f"Missing verified weight: {item['repo']}/{item['name']}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            _os.replace(source, dest)
        repo_dir = dest.parent.parent
        link = repo_dir / "snapshots" / item["revision"] / item["name"]
        link.parent.mkdir(parents=True, exist_ok=True)
        tmp = link.with_name(link.name + ".publishing")
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(_os.path.relpath(dest, link.parent))
        _os.replace(tmp, link)
    volume.commit()
    for item in items:
        repo_dir = _blob(item).parent.parent
        ref = repo_dir / "refs" / "main"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(item["revision"])
    # Preserve checkpoints on failures; clean up only after successful commit.
    volume.commit()
    shutil.rmtree(root, ignore_errors=True)
    volume.commit()
    return len(items)


@app.local_entrypoint()
def main(all: bool = True, list: bool = False, check: bool = False,
         ensure: bool = True, parallel: int = 4, workers: int = 2):
    import hashlib
    import json
    import time

    if not 1 <= parallel <= 16 or not 1 <= workers <= 8:
        raise ValueError("parallel must be 1..16 and workers must be 1..8")
    models = inspect_models.remote(all)
    if list:
        for model in models:
            print(model["repo_id"], "CACHE HIT" if model["cached"] else "CACHE MISS")
        return
    # Resolve exact files for a strong check, rather than assuming a nonempty
    # repository directory proves the whole model was downloaded.
    items = manifest.remote(models)
    missing = missing_files.remote(items)
    print(f"Verified files: {len(items)-len(missing)}/{len(items)}; missing {len(missing)}", flush=True)
    if check:
        if missing:
            raise SystemExit(3)
        return
    if not missing:
        print("CACHE READY", flush=True)
        return
    if all and not ensure:
        raise ValueError("To download the full catalogue, add --ensure explicitly")
    t0 = time.monotonic()
    run_id = hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()[:12]
    shards = pack_shards(missing, parallel)
    payloads = [{"stage": run_id, "items": shard, "workers": workers} for shard in shards]
    print(f"Downloading {len(missing)} files / {sum(x['size'] for x in missing)/1e9:.2f} GB "
          f"across {len(shards)} CPU containers", flush=True)
    results = [result for result in fetch_shard.map(payloads)]
    failures = [e for r in results for e in r["errors"]]
    if failures:
        raise RuntimeError("Download failures; staged data retained:\n" + "\n".join(failures))
    published = publish.remote(items, run_id)
    print(f"CACHE READY: {published} verified files, {time.monotonic()-t0:.1f}s", flush=True)
