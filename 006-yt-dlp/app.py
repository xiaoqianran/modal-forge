"""Modal CPU download application; downloaded media never touches the local PC."""
import json
import time

import modal

from yt_downloader.models import validate_url

APP_NAME = "modal-forge-006-yt-dlp"
VOLUME_NAME = "modal-forge"
SECRET_NAME = "youtube-cookies"

app = modal.App(APP_NAME)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "aria2", "curl", "unzip", "ca-certificates")
    .run_commands(
        "curl -fsSL https://dl.deno.land/release/v2.3.0/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip",
        "unzip -q /tmp/deno.zip -d /usr/local/bin && chmod +x /usr/local/bin/deno && rm /tmp/deno.zip",
    )
    .uv_pip_install("yt-dlp[default]")
    .add_local_python_source("yt_downloader")
)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


@app.function(
    image=image,
    volumes={"/data": volume},
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    timeout=1800,
    cpu=2,
)
def inspect_video(url: str) -> dict:
    from yt_downloader.downloader import inspect

    return inspect(url)


@app.function(
    image=image,
    volumes={"/data": volume},
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    timeout=3600,
    cpu=2,
)
def download_video(
    url: str,
    subtitles: bool = False,
    strategy: str = "native",
    connections: int = 4,
    fragments: int = 1,
) -> dict:
    from yt_downloader.downloader import download

    return download(
        url, volume, subtitles=subtitles, strategy=strategy,
        connections=connections, fragments=fragments,
    )


@app.local_entrypoint()
def main(
    url: str, download: bool = False, subtitles: bool = False,
    strategy: str = "native", connections: int = 4, fragments: int = 1,
):
    from yt_downloader.downloader import validate_tuning

    validate_url(url)
    validate_tuning(strategy, connections, fragments)
    if subtitles and not download:
        raise ValueError("--subtitles requires --download")
    start = time.perf_counter()
    print("TIMING host_start: 0.000s", flush=True)
    try:
        result = (
            download_video.remote(
                url, subtitles=subtitles, strategy=strategy,
                connections=connections, fragments=fragments,
            )
            if download
            else inspect_video.remote(url)
        )
    finally:
        print(f"TIMING host_elapsed: {time.perf_counter() - start:.3f}s", flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
