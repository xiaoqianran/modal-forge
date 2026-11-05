"""Independent Modal smoke test without Cloudflare or NVIDIA credentials."""

import json
import tempfile
from pathlib import Path

import modal


app = modal.App("modal-forge-007-extract-smoke")
image = modal.Image.debian_slim(python_version="3.12").apt_install("ffmpeg").add_local_python_source("extractor")
volume = modal.Volume.from_name("modal-forge")


@app.function(image=image, volumes={"/data": volume}, cpu=2, timeout=180)
def smoke_extract(job_id: str, seconds: int = 4) -> dict:
    from extractor import duration_seconds, extract_window, locate_video
    video = locate_video(job_id)
    with tempfile.TemporaryDirectory(prefix="smoke-frames-") as temporary:
        frames = extract_window(video, Path(temporary), 0, seconds)
        return {
            "video": video.name,
            "duration_s": duration_seconds(video),
            "frames": len(frames),
            "jpeg_bytes": sum(frame.stat().st_size for frame in frames),
        }


@app.local_entrypoint()
def main(job_id: str, seconds: int = 4):
    print(json.dumps(smoke_extract.remote(job_id, seconds), ensure_ascii=False, indent=2))
