"""One-time cloud-side layout migration. No video bytes touch the local computer."""
import json
import os
from pathlib import Path

import modal

app = modal.App("modal-forge-006-volume-migration")
volume = modal.Volume.from_name("modal-forge")


@app.function(volumes={"/data": volume}, timeout=1200)
def migrate():
    source = Path("/data/modal-forge/006-yt-dlp-downloads")
    target = Path("/data/006-yt-dlp-downloads")
    if not source.is_dir():
        raise FileNotFoundError(f"Expected source directory not found: {source}")
    if target.exists():
        raise FileExistsError(f"Destination already exists: {target}")
    os.replace(source, target)
    updated = 0
    for manifest in target.rglob("manifest.json"):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["files"] = [
            value.replace(str(source), str(target), 1)
            for value in data.get("files", [])
        ]
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        updated += 1
    volume.commit()
    return {"root": str(target), "manifests_updated": updated,
            "media_files": [str(p) for p in target.rglob("*.mkv")]}


@app.local_entrypoint()
def main():
    print(json.dumps(migrate.remote(), ensure_ascii=False, indent=2))
