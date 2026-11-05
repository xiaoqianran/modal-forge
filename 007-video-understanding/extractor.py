"""Bounded 1 FPS CPU frame extraction; images remain inside Modal temp storage."""

import math
import re
import subprocess
from pathlib import Path

VIDEO_ROOT = Path("/data/006-yt-dlp-downloads/videos")
JOB_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")
EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm"}


def locate_video(job_id: str, root: Path = VIDEO_ROOT) -> Path:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("Invalid job ID")
    folder = root / job_id
    if not folder.is_dir():
        raise FileNotFoundError(f"Video job does not exist: {job_id}")
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if len(files) != 1:
        raise ValueError(f"Expected exactly one video in {job_id}; found {len(files)}")
    return files[0]


def duration_seconds(video: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid video duration")
    return duration


def extract_window(video: Path, output: Path, offset: int, seconds: int, width: int = 960) -> list[Path]:
    if offset < 0 or seconds < 1 or seconds > 200 or width < 256 or width > 1920:
        raise ValueError("Invalid extraction parameters")
    output.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", str(offset), "-i", str(video), "-t", str(seconds),
        "-vf", f"fps=1,scale={width}:-2", "-q:v", "4",
        str(output / "frame_%05d.jpg"),
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)
    frames = sorted(output.glob("frame_*.jpg"))
    if not frames:
        raise RuntimeError("FFmpeg produced no frames")
    return frames
