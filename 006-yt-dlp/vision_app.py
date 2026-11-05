"""Modal entrypoint for NVIDIA video frame understanding."""

import json

import modal

app = modal.App("modal-forge-006-youtube-vision")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .add_local_python_source("video_vision")
)
volume = modal.Volume.from_name("modal-forge")


@app.function(
    image=image.add_local_python_source("video_vision", "app"),
    volumes={"/data": volume},
    secrets=[modal.Secret.from_name("nvidia-api")],
    cpu=2,
    timeout=3600,
)
def analyze(job_id: str, interval: float = 5.0, max_frames: int = 24,
            batch_size: int = 4) -> dict:
    from video_vision import analyze_download

    result = analyze_download(job_id, interval=interval, max_frames=max_frames,
                              batch_size=batch_size)
    volume.commit()
    return result


@app.local_entrypoint()
def main(job_id: str, interval: float = 5.0, max_frames: int = 24,
         batch_size: int = 4):
    result = analyze.remote(job_id, interval=interval, max_frames=max_frames,
                            batch_size=batch_size)
    print(json.dumps(result, ensure_ascii=False, indent=2))
