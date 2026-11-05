"""Inspect and download a single video; output remains in Modal Volume."""
from pathlib import Path
import time
import uuid

from yt_downloader.auth import cookie_file
from yt_downloader.models import public_metadata, validate_url
from yt_downloader.storage import discard, publish, task_dirs


def validate_tuning(strategy: str, connections: int, fragments: int) -> None:
    if strategy not in {"native", "chunked", "aria2"}:
        raise ValueError("strategy must be native, chunked or aria2")
    if not isinstance(connections, int) or not 1 <= connections <= 8:
        raise ValueError("connections must be an integer between 1 and 8")
    if not isinstance(fragments, int) or not 1 <= fragments <= 8:
        raise ValueError("fragments must be an integer between 1 and 8")


def _options(
    staging=None, subtitles=False, cookie_path=None,
    strategy="native", connections=4, fragments=1,
) -> dict:
    validate_tuning(strategy, connections, fragments)
    options = {
        "quiet": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "retries": 3,
        "continuedl": True,
        "format": "bv*+ba/b",
        "merge_output_format": "mkv",
        "restrictfilenames": True,
        "skip_download": staging is None,
        "concurrent_fragment_downloads": fragments,
        "fragment_retries": 3,
    }
    if staging is not None and strategy == "aria2":
        # The external downloader is used only for HTTP(S). Fragmented
        # DASH/HLS remains on yt-dlp's built-in concurrent downloader.
        options["external_downloader"] = {
            "default": "aria2c", "dash": "native", "m3u8": "native",
        }
        options["external_downloader_args"] = {
            "aria2c": [
                f"--max-connection-per-server={connections}",
                f"--split={connections}",
                "--min-split-size=4M",
                "--max-tries=3",
                "--retry-wait=2",
                "--connect-timeout=15",
                "--timeout=30",
                "--file-allocation=none",
                "--summary-interval=0",
            ],
        }
    elif staging is not None and strategy == "chunked":
        # YouTube can throttle large HTTP Range responses; bounded native
        # chunks permit comparing this behaviour against aria2 and baseline.
        options["http_chunk_size"] = 8 * 1024 * 1024
    if staging is not None:
        options["outtmpl"] = str(staging / "%(title).160B [%(id)s].%(ext)s")
    if subtitles:
        options.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en.*"],
            "subtitlesformat": "vtt/best",
            "convertsubtitles": "srt",
        })
    if cookie_path:
        options["cookiefile"] = cookie_path
    return options


def _requires_authentication(error: Exception) -> bool:
    """Only retry an explicitly authentication-gated extraction."""
    message = str(error).lower()
    return any(phrase in message for phrase in (
        "sign in to confirm you’re not a bot",
        "sign in to confirm you're not a bot",
        "login required",
        "sign in to confirm your age",
        "this video is private",
    ))


def inspect(url: str) -> dict:
    import yt_dlp

    validate_url(url)
    def extract(cookie_path=None):
        with yt_dlp.YoutubeDL(_options(cookie_path=cookie_path)) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise RuntimeError("yt-dlp found no video information")
            return public_metadata(ydl.sanitize_info(info))

    try:
        result = extract()
        result["authentication"] = "anonymous"
        return result
    except yt_dlp.utils.DownloadError as error:
        if not _requires_authentication(error):
            # Avoid shipping yt-dlp's unpickleable traceback to the host.
            raise RuntimeError(f"Metadata extraction failed: {str(error)[:500]}") from None
        print("INSPECT anonymous login challenge; retrying with Modal Secret", flush=True)
    with cookie_file() as path:
        try:
            result = extract(path)
            result["authentication"] = "cookie"
            return result
        except yt_dlp.utils.DownloadError as error:
            raise RuntimeError(f"Authenticated metadata extraction failed: {str(error)[:500]}") from None


def download(
    url: str, volume, subtitles: bool = False,
    strategy: str = "native", connections: int = 4, fragments: int = 1,
) -> dict:
    import yt_dlp

    validate_url(url)
    validate_tuning(strategy, connections, fragments)
    started = time.perf_counter()
    milestones = {}
    stream_events = []
    last_progress = 0.0
    job_id = uuid.uuid4().hex
    staging, _ = task_dirs(job_id)
    staging.mkdir(parents=True, exist_ok=False)

    def report(stage: str):
        elapsed = round(time.perf_counter() - started, 3)
        milestones[stage] = elapsed
        print(f"TIMING {stage}: {elapsed:.3f}s", flush=True)

    def progress(data):
        nonlocal last_progress
        if data.get("status") == "downloading" and "download_start" not in milestones:
            report("download_start")
        if data.get("status") == "downloading":
            now = time.perf_counter()
            if now - last_progress >= 5:
                last_progress = now
                downloaded = data.get("downloaded_bytes") or 0
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                speed = data.get("speed")
                fraction = f"{downloaded / total:.1%}" if total else "unknown"
                speed_text = f"{speed / 1048576:.2f} MiB/s" if speed else "unknown"
                print(
                    f"PROGRESS {fraction} {downloaded / 1048576:.1f} MiB "
                    f"{speed_text}", flush=True,
                )
        elif data.get("status") == "finished":
            index = len(stream_events) + 1
            report(f"stream_{index}_finished")
            detail = data.get("info_dict") or {}
            filename = data.get("filename")
            byte_size = Path(filename).stat().st_size if filename and Path(filename).is_file() else None
            stream_events.append({
                "format_id": str(detail.get("format_id") or "unknown")[:40],
                "bytes": byte_size,
                "completed_at_seconds": milestones[f"stream_{index}_finished"],
            })

    def postprocess(data):
        if data.get("postprocessor") == "FFmpegMergerPP":
            report("merge_" + data.get("status", "unknown"))

    try:
        report("worker_start")
        with cookie_file() as path:
            report("cookie_ready")
            config = _options(
                staging, subtitles, path, strategy=strategy,
                connections=connections, fragments=fragments,
            )
            config["progress_hooks"] = [progress]
            config["postprocessor_hooks"] = [postprocess]
            with yt_dlp.YoutubeDL(config) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise RuntimeError("yt-dlp found no media information")
                report("metadata_ready")
                print(
                    f"DOWNLOADER strategy={strategy} connections={connections} "
                    f"fragments={fragments}", flush=True,
                )
                report("media_download_invoked")
                result = ydl.process_ie_result(info, download=True)
                if result is None:
                    raise RuntimeError("yt-dlp returned no completed video")
                metadata = ydl.sanitize_info(result)
                report("download_and_merge_done")
        selected = metadata.get("requested_formats") or metadata.get("requested_downloads") or [metadata]
        format_summary = [
            {
                "format_id": item.get("format_id"),
                "protocol": item.get("protocol"),
                "ext": item.get("ext"),
                "filesize": item.get("filesize") or item.get("filesize_approx"),
            }
            for item in selected if isinstance(item, dict)
        ]
        print(f"FORMATS {format_summary}", flush=True)
        output_dir, paths = publish(job_id, metadata, volume)
        report("volume_committed")
        return {
            "status": "success",
            "job_id": job_id,
            "video_id": metadata.get("id"),
            "title": metadata.get("title"),
            "volume": "modal-forge",
            "cloud_directory": output_dir,
            "files": paths,
            "strategy": strategy,
            "connections": connections,
            "fragments": fragments,
            "selected_formats": format_summary,
            "stream_events": stream_events,
            "timings_seconds_from_worker_start": milestones,
        }
    except Exception:
        report("failed")
        discard(job_id)
        raise
