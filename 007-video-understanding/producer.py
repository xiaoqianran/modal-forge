"""Upload a bounded window of frames to R2; publish verified batches to CF Worker."""

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

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


def _read_progress(client, bucket: str, job_id: str) -> dict:
    try:
        response = client.get_object(Bucket=bucket, Key=f"state/{job_id}.json")
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
            return {}
        raise
    return json.loads(response["Body"].read())


def _pending_frames(client, bucket: str, job_id: str) -> int:
    """Count images awaiting consumption, without downloading the images."""
    paginator = client.get_paginator("list_objects_v2")
    return sum(
        page.get("KeyCount", 0)
        for page in paginator.paginate(Bucket=bucket, Prefix=f"temp/{job_id}/")
    )


def produce_all(job_id: str, max_pending_frames: int = 200) -> dict:
    """Submit all windows, persisting progress; NVIDIA consumption stays async."""
    if max_pending_frames < 100:
        raise ValueError("max_pending_frames must be at least 100")
    video = locate_video(job_id)
    duration = duration_seconds(video)
    bucket = os.environ["CF_R2_BUCKET"]
    client = r2_client()
    state = _read_progress(client, bucket, job_id)
    if state.get("status") == "submitted":
        return state

    start = int(state.get("next_second", 0))
    windows = int(state.get("windows", 0))
    # The per-video cap protects against uncontrolled R2 backlog.
    wait_started = time.monotonic()
    # Container duration may include a few milliseconds of muxing padding.
    # Do not schedule a spurious final frame for e.g. a 4.004s / 4-frame clip.
    while start + 0.02 < duration:
        while _pending_frames(client, bucket, job_id) > max_pending_frames - 100:
            if time.monotonic() - wait_started > 3600:
                raise TimeoutError("R2 pending frame limit exceeded for one hour; rerun to resume")
            time.sleep(15)
        wait_started = time.monotonic()
        result = produce(job_id, start_second=start)
        if result["next_second"] <= start:
            raise RuntimeError("Video producer made no progress")
        start = result["next_second"]
        windows += 1
        state = {
            "job_id": job_id,
            "status": "submitted" if start + 0.02 >= duration else "submitting",
            "next_second": start,
            "duration_s": duration,
            "windows": windows,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        client.put_object(
            Bucket=bucket, Key=f"state/{job_id}.json",
            Body=json.dumps(state, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        print(f"VIDEO_PROGRESS {job_id} {start:.0f}/{duration:.0f}s", flush=True)
    if state.get("status") != "submitted":
        state = {
            "job_id": job_id,
            "status": "submitted",
            "next_second": start,
            "duration_s": duration,
            "windows": windows,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        client.put_object(
            Bucket=bucket, Key=f"state/{job_id}.json",
            Body=json.dumps(state, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
    return state
