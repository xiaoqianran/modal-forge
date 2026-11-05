"""Upload a bounded window of frames to R2; publish verified batches to CF Worker."""

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3

from extractor import duration_seconds, extract_window, locate_video


REQUIRED_ENV = (
    "CF_R2_ACCOUNT_ID", "CF_R2_ACCESS_KEY_ID", "CF_R2_SECRET_ACCESS_KEY",
    "CF_R2_BUCKET", "CF_WORKER_URL", "CF_INGEST_TOKEN",
)


def make_batch(job_id: str, offset: int, files: list[Path]) -> dict:
    return {
        "job_id": job_id,
        "batch_id": f"{offset:08d}",
        "timestamps_s": [offset + i for i in range(len(files))],
        "keys": [f"temp/{job_id}/{offset + i:08d}.jpg" for i in range(len(files))],
    }


def r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['CF_R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["CF_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CF_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def publish_batch(message: dict) -> None:
    url = os.environ["CF_WORKER_URL"].rstrip("/") + "/enqueue"
    request = urllib.request.Request(
        url, data=json.dumps(message).encode("utf-8"),
        headers={"Authorization": "Bearer " + os.environ["CF_INGEST_TOKEN"],
                 "Content-Type": "application/json",
                 "User-Agent": "modal-forge-007-video-understanding/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 202:
                raise RuntimeError(f"Unexpected queue HTTP status: {response.status}")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Cloudflare enqueue failed: HTTP {error.code}") from None


def produce(job_id: str, start_second: int = 0, max_batches: int = 25,
            batch_size: int = 4, width: int = 960) -> dict:
    missing = [key for key in REQUIRED_ENV if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Missing Modal Secret fields: " + ", ".join(missing))
    if start_second < 0 or not 1 <= max_batches <= 50 or not 1 <= batch_size <= 8:
        raise ValueError("Invalid processing window or batch size")
    video = locate_video(job_id)
    duration = duration_seconds(video)
    if start_second >= duration:
        raise ValueError("start_second is beyond end of video")
    count = min(max_batches * batch_size, int(duration - start_second + 0.999))
    started = time.perf_counter()
    published = 0
    client = r2_client()
    with tempfile.TemporaryDirectory(prefix="video-frames-") as temp:
        files = extract_window(video, Path(temp), start_second, count, width)
        for position in range(0, len(files), batch_size):
            group = files[position:position + batch_size]
            message = make_batch(job_id, start_second + position, group)
            for path, key in zip(group, message["keys"]):
                client.upload_file(
                    str(path), os.environ["CF_R2_BUCKET"], key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
            # If publication fails, leave objects for diagnosis / TTL cleanup;
            # rerunning the same window may repeat a queued message; Worker checks result key.
            publish_batch(message)
            published += 1
            print(f"Queued batch {published}: {message['batch_id']}", flush=True)
    return {
        "job_id": job_id,
        "start_second": start_second,
        "next_second": start_second + len(files),
        "duration_s": duration,
        "frames": len(files),
        "batches": published,
        "extract_and_publish_s": round(time.perf_counter() - started, 3),
    }
