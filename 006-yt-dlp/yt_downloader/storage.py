"""Volume layout and publishing completed media."""
import json
import os
import shutil
from pathlib import Path

ROOT = Path("/data/006-yt-dlp-downloads")
TEMP = ROOT / ".incomplete"
VIDEOS = ROOT / "videos"


def task_dirs(job_id: str):
    return TEMP / job_id, VIDEOS / job_id


def publish(job_id: str, info: dict, volume) -> tuple[str, list[str]]:
    staging, final = task_dirs(job_id)
    files = sorted(
        p for p in staging.rglob("*")
        if p.is_file() and not p.name.endswith((".part", ".ytdl"))
    )
    if not files:
        raise RuntimeError("yt-dlp did not produce a completed file")
    if any(p.stat().st_size == 0 for p in files):
        raise RuntimeError("A downloaded file is empty")
    VIDEOS.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise FileExistsError("Download job directory already exists")
    os.replace(staging, final)
    paths = [str(final / p.relative_to(staging)) for p in files]
    metadata = {
        "status": "success",
        "job_id": job_id,
        "video_id": info.get("id"),
        "title": info.get("title"),
        "files": paths,
    }
    (final / "manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    volume.commit()
    return str(final), paths


def discard(job_id: str):
    staging, _ = task_dirs(job_id)
    shutil.rmtree(staging, ignore_errors=True)
