"""Sample frames from downloaded videos and analyze them with NVIDIA Vision API."""

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
ROOT = Path("/data/006-yt-dlp-downloads/videos")
PROMPT = (
    "你正在分析一段视频中按时间顺序提取的画面。请用简体中文描述每张画面的"
    "人物、动作、场景、文字和关键变化，结合时间戳说明事件顺序。"
    "不要推断帧之间不可见的事件。"
)


def probe_duration(video: Path) -> float:
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        check=True, capture_output=True, text=True,
    )
    duration = float(process.stdout.strip())
    if not 0 < duration < float("inf"):
        raise ValueError("Invalid video duration")
    return duration


def sample_times(duration: float, interval: float, max_frames: int) -> list[float]:
    if interval <= 0 or not 1 <= max_frames <= 100:
        raise ValueError("interval must be positive; max_frames must be 1..100")
    return [round(i * interval, 3) for i in range(min(max_frames, max(1, int((duration - 0.001) // interval) + 1)))]


def extract_frame(video: Path, seconds: float, width: int = 960) -> bytes:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(seconds),
         "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2",
         "-q:v", "3", "-f", "image2", "-vcodec", "mjpeg", "pipe:1"],
        check=True, capture_output=True,
    )
    if not result.stdout:
        raise RuntimeError(f"No frame at {seconds}s")
    return result.stdout


def analyze_frames(frames: list[tuple[float, bytes]], api_key: str, prompt: str = PROMPT) -> str:
    content = [{"type": "text", "text": prompt}]
    for seconds, jpeg in frames:
        content.append({"type": "text", "text": f"视频时间戳: {seconds:.3f} 秒"})
        content.append({
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")},
        })
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.6,
        "top_p": 0.95,
        "max_tokens": 2048,
        "reasoning_effort": "none",
        "stream": False,
    }
    request = urllib.request.Request(
        ENDPOINT, json.dumps(payload).encode("utf-8"),
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            detail = payload.get("error", payload.get("detail", payload.get("message", "")))
        except json.JSONDecodeError:
            detail = body[:400]
        detail = re.sub(r"nvapi-[A-Za-z0-9_-]+", "[REDACTED]", str(detail))
        raise RuntimeError(f"NVIDIA API HTTP {exc.code}: {detail[:500]}") from exc
    return result["choices"][0]["message"]["content"]


def analyze_download(job_id: str, interval: float = 5.0, max_frames: int = 24,
                     batch_size: int = 4, prompt: str = PROMPT) -> dict:
    if not job_id or Path(job_id).name != job_id or job_id in {".", ".."}:
        raise ValueError("Invalid job_id")
    if not 1 <= batch_size <= 8:
        raise ValueError("batch_size must be 1..8")
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        raise RuntimeError("NVIDIA_API_KEY missing: configure Modal Secret nvidia-api")
    folder = ROOT / job_id
    if not folder.is_dir():
        raise FileNotFoundError(f"Download job not found: {job_id}")
    videos = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"})
    if not videos:
        raise FileNotFoundError("No video file inside download job")
    video = videos[0]
    duration = probe_duration(video)
    times = sample_times(duration, interval, max_frames)
    batches = []
    for begin in range(0, len(times), batch_size):
        group = [(t, extract_frame(video, t)) for t in times[begin:begin + batch_size]]
        description = analyze_frames(group, key, prompt)
        batches.append({"timestamps_s": [t for t, _ in group], "description": description})
        print(f"Analyzed {min(begin + batch_size, len(times))}/{len(times)} frames", flush=True)
    result = {"job_id": job_id, "video": video.name, "model": MODEL, "duration_s": duration,
              "interval_s": interval, "frames": len(times), "batches": batches}
    (folder / "nvidia_vision.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
