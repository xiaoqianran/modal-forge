"""CPU-only, resumable Qwen model downloader for Modal Volume v1.

Adapted from modal-comfyui-caru-ini/download-models.py:
- pinned Hugging Face commit
- size-balanced 16GB shards across independent CPU containers
- native hf_xet transport / resumable per-file staging
- per-file SHA256 or Git-blob SHA1 check
- publish only after every shard succeeds
- GPU inference reads the published manifest, never downloads

No Modal calls are made merely by importing the module.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from legacy.qwen_storage_v1 import (
    CACHE_DIR,
    MODEL_ID,
    MODEL_VOLUME,
    PIN_FILE,
    READY_FILE,
    STAGING_DIR,
    atomic_json,
    blob_file,
    ready_snapshot,
    safe_filename,
    size_matches,
    snapshot_file,
    validate_weights,
)

app = modal.App("005-qwen38-flashnext-download-v1")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("huggingface_hub>=0.30,<2", "hf_xet")
    .env({"HF_XET_HIGH_PERFORMANCE": "0"})
    .add_local_python_source("legacy")
)


def pack_shards(items: list[dict], target_bytes: int, max_shards: int) -> list[list[dict]]:
    """Distribute largest files first among evenly loaded CPU download jobs."""
    if not items:
        return []
    total = sum(int(item["size"]) for item in items)
    count = min(max_shards, len(items), max(1, (total + target_bytes - 1) // target_bytes))
    groups: list[list[dict]] = [[] for _ in range(count)]
    sizes = [0] * count
    for item in sorted(items, key=lambda obj: -obj["size"]):
        index = min(range(count), key=lambda n: sizes[n])
        groups[index].append(item)
        sizes[index] += item["size"]
    return [group for group in groups if group]


def stage_root(revision: str, item: dict) -> Path:
    key = hashlib.sha256(item["filename"].encode("utf-8")).hexdigest()[:24]
    return STAGING_DIR / revision / key


def stage_file(revision: str, item: dict) -> Path:
    return stage_root(revision, item) / safe_filename(item["filename"])


def verify_hash(path: Path, item: dict) -> None:
    if not size_matches(path, item["size"]):
        raise RuntimeError(f"File missing or size mismatch: {item['filename']}")
    algorithm = item["algorithm"]
    h = hashlib.new(algorithm)
    if algorithm == "sha1":
        h.update(f"blob {item['size']}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    if h.hexdigest() != item["digest"]:
        raise RuntimeError(f"Hash mismatch: {item['filename']}")


@app.function(image=image, cpu=2, memory=4096, timeout=3600,
              volumes={"/cache": MODEL_VOLUME}, max_containers=1)
def check_ready() -> dict:
    MODEL_VOLUME.reload()
    pending = json.loads(PIN_FILE.read_text("utf-8")) if PIN_FILE.is_file() else {}
    result = {"ready": False, "pending_revision": pending.get("revision")}
    if not READY_FILE.is_file():
        return result
    try:
        root, record = ready_snapshot()
    except (OSError, KeyError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        result["error"] = f"Published cache invalid: {exc}"
        return result
    return {
        "ready": True, "revision": record["revision"],
        "files": len(record["files"]), "bytes": sum(i["size"] for i in record["files"]),
        "root": str(root),
        "pending_revision": (
            pending.get("revision")
            if pending.get("revision") != record["revision"]
            else None
        ),
    }


@app.function(image=image, cpu=2, memory=4096, timeout=3600,
              volumes={"/cache": MODEL_VOLUME}, max_containers=1)
def resolve_manifest(update: bool = False) -> dict:
    """Lock to a commit before download; retries retain the same revision."""
    from huggingface_hub import HfApi

    MODEL_VOLUME.reload()
    previous = json.loads(PIN_FILE.read_text("utf-8")) if PIN_FILE.is_file() else None
    revision = "7b719225242aacd3dbd3f9407468c2ee9a9d2594" if update or not previous else previous["revision"]
    details = HfApi(token=os.getenv("HF_TOKEN") or None).model_info(
        MODEL_ID, revision=revision, files_metadata=True
    )
    if not details.sha or len(details.sha) != 40:
        raise RuntimeError("Could not resolve a pinned model revision")
    items = []
    for entry in details.siblings or []:
        if entry.size is None or entry.size <= 0:
            raise RuntimeError(f"Missing positive file size: {entry.rfilename}")
        if entry.lfs is not None:
            digest = entry.lfs.sha256
            algorithm = "sha256"
        else:
            digest = entry.blob_id
            algorithm = "sha1"
        if not digest:
            raise RuntimeError(f"Missing content digest: {entry.rfilename}")
        blob_file(digest)  # validate the expected digest format
        safe_filename(entry.rfilename)
        items.append({
            "filename": entry.rfilename, "size": entry.size,
            "digest": digest, "algorithm": algorithm,
        })
    if not items:
        raise RuntimeError("Hugging Face manifest has no files")
    manifest = {"model": MODEL_ID, "revision": details.sha, "files": items}
    atomic_json(PIN_FILE, manifest)
    MODEL_VOLUME.commit()
    return manifest


@app.function(image=image, cpu=2, memory=4096, timeout=3600,
              volumes={"/cache": MODEL_VOLUME}, max_containers=1)
def check_missing(manifest: dict) -> list[dict]:
    MODEL_VOLUME.reload()
    revision = manifest["revision"]
    missing = []
    for item in manifest["files"]:
        if size_matches(snapshot_file(revision, item["filename"]), item["size"]):
            continue
        staged = stage_file(revision, item)
        if size_matches(staged, item["size"]):
            try:
                verify_hash(staged, item)
                continue
            except RuntimeError:
                staged.unlink(missing_ok=True)
        missing.append(item)
    return missing


@app.function(image=image, cpu=4, memory=4096, timeout=7200,
              volumes={"/cache": MODEL_VOLUME}, max_containers=8)
def download_shard(payload: dict) -> dict:
    """Independent files have independent staging directories and retry state."""
    from concurrent.futures import ThreadPoolExecutor
    from huggingface_hub import hf_hub_download

    MODEL_VOLUME.reload()
    started = time.monotonic()
    items = payload["items"]
    revision = payload["revision"]
    errors = []

    def fetch(item: dict) -> None:
        path = stage_file(revision, item)
        if size_matches(snapshot_file(revision, item["filename"]), item["size"]):
            return
        if size_matches(path, item["size"]):
            try:
                verify_hash(path, item)
                return
            except RuntimeError:
                path.unlink(missing_ok=True)
        # Each file gets its own stable local_dir. hf_hub_download retains
        # resumable metadata under that local_dir's .cache/huggingface.
        local_dir = stage_root(revision, item)
        last_error = None
        for attempt in range(4):
            try:
                downloaded = hf_hub_download(
                    repo_id=MODEL_ID,
                    filename=item["filename"],
                    revision=revision,
                    local_dir=str(local_dir),
                    token=os.getenv("HF_TOKEN") or None,
                    force_download=attempt > 0,
                )
                verify_hash(Path(downloaded), item)
                return
            except Exception as exc:
                last_error = exc
                if attempt == 3:
                    break
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"Download failed after 4 attempts: {last_error}")

    def guarded(item: dict) -> None:
        try:
            fetch(item)
        except Exception as exc:
            errors.append(f"{item['filename']}: {type(exc).__name__}: {exc}")

    try:
        with ThreadPoolExecutor(max_workers=payload["workers"]) as pool:
            list(pool.map(guarded, items))
    finally:
        # Persist successful staging even if other files fail; next run resumes.
        MODEL_VOLUME.commit()
    return {
        "shard": payload["shard"], "ok": not errors, "errors": errors,
        "files": len(items), "seconds": round(time.monotonic() - started, 2),
    }


@app.function(image=image, cpu=2, memory=8192, timeout=7200,
              volumes={"/cache": MODEL_VOLUME}, max_containers=1)
def publish(manifest: dict) -> dict:
    """ComfyUI-style staged publication: weights first, ready record last."""
    MODEL_VOLUME.reload()
    revision = manifest["revision"]
    items = manifest["files"]
    # Do not modify the published model if any requested file is missing.
    missing = [
        item["filename"] for item in items
        if not size_matches(snapshot_file(revision, item["filename"]), item["size"])
        and not size_matches(stage_file(revision, item), item["size"])
    ]
    if missing:
        raise RuntimeError(f"Cannot publish; {len(missing)} files missing: {missing[:6]}")
    for item in items:
        target = snapshot_file(revision, item["filename"])
        if size_matches(target, item["size"]):
            continue
        staged = stage_file(revision, item)
        blob = blob_file(item["digest"])
        blob.parent.mkdir(parents=True, exist_ok=True)
        if not size_matches(blob, item["size"]):
            os.replace(staged, blob)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".publish")
        temp.unlink(missing_ok=True)
        temp.symlink_to(os.path.relpath(blob, target.parent))
        os.replace(temp, target)
    root = snapshot_file(revision, "config.json").parent
    for item in items:
        if not size_matches(snapshot_file(revision, item["filename"]), item["size"]):
            raise RuntimeError(f"Invalid published file: {item['filename']}")
    validate_weights(root)
    # Publishing the weights and the success record in separate commits ensures
    # inference never sees a "ready" manifest for partially uploaded files.
    MODEL_VOLUME.commit()
    ready = {
        **manifest, "volume_version": 1,
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(READY_FILE, ready)
    MODEL_VOLUME.commit()
    staged = STAGING_DIR / revision
    if staged.exists():
        try:
            shutil.rmtree(staged)
            MODEL_VOLUME.commit()
        except OSError as exc:
            print(f"WARN: staging cleanup deferred: {exc}", flush=True)
    return {
        "ready": True, "revision": revision,
        "files": len(items), "bytes": sum(item["size"] for item in items),
        "volume_version": 1,
    }


@app.local_entrypoint()
def main(stage: str = "check", update: bool = False,
         shard_gb: int = 16, max_shards: int = 8, workers: int = 2):
    """Explicit CPU-only stages; no GPU allocation or downloading on import."""
    if stage not in {"check", "download"}:
        raise ValueError("stage must be check or download")
    if not (1 <= shard_gb <= 128 and 1 <= max_shards <= 16 and 1 <= workers <= 8):
        raise ValueError("shard_gb=1..128, max_shards=1..16, workers=1..8")
    if stage == "check":
        print(json.dumps(check_ready.remote(), ensure_ascii=False, indent=2))
        return
    if not update:
        current = check_ready.remote()
        if current["ready"] and not current["pending_revision"]:
            print(f"Already cached in Volume v1: {current}")
            return

    started = time.monotonic()
    manifest = resolve_manifest.remote(update)
    missing = check_missing.remote(manifest)
    print(f"MODEL={MODEL_ID} SHA={manifest['revision']}")
    print(f"FILES={len(manifest['files'])} MISSING={len(missing)}")
    shards = pack_shards(missing, shard_gb * 1_000_000_000, max_shards)
    payloads = [
        {"shard": idx, "revision": manifest["revision"],
         "items": group, "workers": workers}
        for idx, group in enumerate(shards)
    ]
    results = list(download_shard.map(payloads)) if payloads else []
    failures = [item for item in results if not item["ok"]]
    if failures:
        for item in failures:
            print(json.dumps(item, ensure_ascii=False))
        raise RuntimeError(
            "One or more download shards failed; completed files remain staged for retry"
        )
    published = publish.remote(manifest)
    published["wall_seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(published, ensure_ascii=False, indent=2))
