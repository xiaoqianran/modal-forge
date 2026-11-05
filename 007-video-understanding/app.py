"""Modal CPU producer: read existing 006 downloads; enqueue bounded 1 FPS windows."""

import json
import modal

app = modal.App("modal-forge-007-video-understanding")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install("boto3>=1.35,<2")
    .add_local_python_source("extractor", "producer")
)
volume = modal.Volume.from_name("modal-forge")


@app.function(
    image=image,
    volumes={"/data": volume},
    secrets=[modal.Secret.from_name("cf-video-pipeline")],
    cpu=2,
    timeout=900,
)
def queue_window(job_id: str, start_second: int = 0, max_batches: int = 25,
                 batch_size: int = 4, width: int = 960) -> dict:
    from producer import produce
    return produce(job_id, start_second, max_batches, batch_size, width)


@app.local_entrypoint()
def main(job_id: str, start_second: int = 0, max_batches: int = 25,
         batch_size: int = 4, width: int = 960):
    result = queue_window.remote(job_id, start_second, max_batches, batch_size, width)
    print(json.dumps(result, ensure_ascii=False, indent=2))
