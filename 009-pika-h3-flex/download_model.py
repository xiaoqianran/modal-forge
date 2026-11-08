"""Download Pika weights on CPU to the shared Modal Volume (no GPU allocation)."""
import json
from pathlib import Path

import modal

from model_cache import CACHE_ROOT, HF_HUB_CACHE, MODEL, READY_FILE, VOLUME_ROOT, inspect_snapshot

app = modal.App("modal-forge-009-pika-h3-flex-download")
volume = modal.Volume.from_name("modal-forge", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("huggingface_hub>=0.34,<2")
         .add_local_file(str(Path(__file__).with_name("model_cache.py")),
                         "/root/model_cache.py"))


@app.function(
    image=image,
    cpu=4,
    memory=16384,
    timeout=14400,
    volumes={VOLUME_ROOT: volume},
)
def download(revision: str = "main"):
    from huggingface_hub import snapshot_download

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    READY_FILE.unlink(missing_ok=True)
    volume.commit()
    print(f"CPU DOWNLOAD: {MODEL} revision={revision}", flush=True)
    snapshot = Path(snapshot_download(
        repo_id=MODEL,
        revision=revision,
        cache_dir=str(HF_HUB_CACHE),
        max_workers=8,
    ))
    details = inspect_snapshot(snapshot)
    manifest = {
        "repo_id": MODEL,
        "revision": revision,
        "snapshot_path": str(snapshot),
        **details,
    }
    temp = READY_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temp.replace(READY_FILE)
    volume.commit()
    print("CPU DOWNLOAD COMPLETE: " + json.dumps(manifest), flush=True)
    return manifest


@app.local_entrypoint()
def main(revision: str = "main"):
    print(json.dumps(download.remote(revision), indent=2))
