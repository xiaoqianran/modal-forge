"""Compare CPU decoding and CUDA NVDEC decoding on the same Modal Volume video."""

import json
import subprocess
import time
from pathlib import Path

import modal

app = modal.App("modal-forge-006-ffmpeg-benchmark")
volume = modal.Volume.from_name("modal-forge")
image = modal.Image.debian_slim(python_version="3.12").apt_install("ffmpeg")
ROOT = Path("/data/006-yt-dlp-downloads/videos")


def run_benchmark(job_id: str, mode: str, frames: int) -> dict:
    if not job_id or Path(job_id).name != job_id or job_id in {".", ".."}:
        raise ValueError("Invalid job ID")
    if frames < 1 or frames > 60:
        raise ValueError("frames must be 1..60")
    folder = ROOT / job_id
    videos = sorted(
        path for path in folder.iterdir()
        if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    )
    if not videos:
        raise FileNotFoundError(f"No video in {job_id}")
    video = videos[0]
    codec = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    hwaccels = subprocess.run(
        ["ffmpeg", "-hide_banner", "-hwaccels"],
        capture_output=True, text=True, check=True,
    ).stdout
    results = []
    start = time.perf_counter()
    for index in range(frames):
        seconds = index * 5
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "verbose", "-ss", str(seconds)]
        if mode == "gpu":
            cmd += ["-hwaccel", "cuda"]
        cmd += [
            "-i", str(video), "-frames:v", "1",
            "-vf", "scale=960:-2", "-q:v", "3",
            "-f", "image2", "-vcodec", "mjpeg", "pipe:1",
        ]
        t = time.perf_counter()
        process = subprocess.run(cmd, capture_output=True)
        elapsed = time.perf_counter() - t
        diagnostic = process.stderr.decode("utf-8", "replace")
        if process.returncode != 0 or not process.stdout:
            raise RuntimeError(
                f"Failed on frame {index}: {diagnostic[-1000:]}"
            )
        gpu_decoder_used = "Using hwaccel cuda" in diagnostic or (
            "cuda" in diagnostic.lower() and "format" in diagnostic.lower()
        )
        results.append({
            "time_s": seconds,
            "seconds": round(elapsed, 4),
            "jpeg_bytes": len(process.stdout),
            "gpu_decoder_indicated": gpu_decoder_used,
        })
    return {
        "mode": mode,
        "video": video.name,
        "codec": json.loads(codec.stdout),
        "cuda_listed": "cuda" in hwaccels.lower(),
        "frame_count": frames,
        "total_s": round(time.perf_counter() - start, 4),
        "frames": results,
    }


@app.function(image=image, volumes={"/data": volume}, cpu=2, timeout=600)
def cpu_benchmark(job_id: str, frames: int = 12) -> dict:
    return run_benchmark(job_id, "cpu", frames)


@app.function(image=image, volumes={"/data": volume}, gpu="T4", cpu=2, timeout=600)
def gpu_benchmark(job_id: str, frames: int = 12) -> dict:
    return run_benchmark(job_id, "gpu", frames)


@app.local_entrypoint()
def main(job_id: str, frames: int = 12):
    for fn in (cpu_benchmark, gpu_benchmark):
        start = time.perf_counter()
        try:
            result = fn.remote(job_id, frames)
            result["wall_s"] = round(time.perf_counter() - start, 4)
        except Exception as exc:
            result = {"mode": fn.tag, "error": str(exc)[:500]}
        print(json.dumps(result, ensure_ascii=False), flush=True)
