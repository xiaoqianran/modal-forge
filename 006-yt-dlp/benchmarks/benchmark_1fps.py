"""Measure sequential 1 fps JPEG extraction on videos already in Modal Volume."""

import json
import subprocess
import tempfile
import time
from pathlib import Path

import modal


app = modal.App("modal-forge-006-1fps-benchmark")
volume = modal.Volume.from_name("modal-forge")
image = modal.Image.debian_slim(python_version="3.12").apt_install("ffmpeg")
root = Path("/data/006-yt-dlp-downloads/videos")


@app.function(image=image, volumes={"/data": volume}, cpu=2, timeout=600)
def measure(job_id: str, seconds: int = 60, offset: int = 0) -> dict:
    if not job_id or Path(job_id).name != job_id or job_id in {".", ".."}:
        raise ValueError("Invalid job ID")
    if not 1 <= seconds <= 180 or offset < 0:
        raise ValueError("Invalid seconds or offset")
    video_files = sorted(
        p for p in (root / job_id).iterdir()
        if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    )
    if not video_files:
        raise FileNotFoundError("No video found")
    video = video_files[0]
    metadata = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        check=True, capture_output=True, text=True,
    )
    duration = float(metadata.stdout.strip())
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp)
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(offset), "-i", str(video), "-t", str(seconds),
            "-vf", "fps=1,scale=960:-2", "-q:v", "3",
            str(output / "frame_%05d.jpg"),
        ]
        started = time.perf_counter()
        completed = subprocess.run(args, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        if completed.returncode:
            raise RuntimeError(completed.stderr[-1000:])
        files = list(output.glob("frame_*.jpg"))
        if not files:
            raise RuntimeError("No frames were generated")
        return {
            "job_id": job_id, "video": video.name,
            "video_duration_s": duration,
            "offset_s": offset, "sample_s": seconds,
            "extracted_frames": len(files),
            "elapsed_s": round(elapsed, 3),
            "frames_per_second": round(len(files) / elapsed, 3),
            "bytes_total": sum(p.stat().st_size for p in files),
            "estimated_full_s": round(elapsed * duration / len(files), 1),
        }


@app.local_entrypoint()
def main(seconds: int = 60):
    jobs = (
        "8748ecf7da644a1884d7cd8fae692b41",
        "3631d8c342d94847a2ba4ba140cdfc28",
    )
    for job in jobs:
        started = time.perf_counter()
        result = measure.remote(job, seconds=seconds)
        result["modal_call_s"] = round(time.perf_counter() - started, 3)
        print("BENCHMARK_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)
