"""Isolated read-throughput comparison: same model, same CPU allocation, each Volume."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from legacy.qwen_storage_v1 import MODEL_VOLUME as V1
from qwen_core.storage import MODEL_VOLUME as V2

app = modal.App("005-qwen38-volume-read-compare")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .add_local_python_source("legacy", "qwen_core")
)
GiB = 1024 ** 3


def read_probe(storage_version: int, bytes_to_read: int = 4 * GiB) -> dict:
    if storage_version == 1:
        from legacy.qwen_storage_v1 import ready_snapshot
    else:
        from qwen_core.storage import ready_snapshot
    root, manifest = ready_snapshot()
    # Force reading real safetensors weight payloads, not only metadata.
    shards = sorted(
        (p for p in root.glob("*.safetensors") if p.stat().st_size > 512 * 1024 * 1024),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not shards:
        raise RuntimeError("No large safetensors weights available for read benchmarking")
    start = time.perf_counter()
    amount = 0
    chosen = []
    for file in shards:
        if amount >= bytes_to_read:
            break
        count = 0
        with file.open("rb", buffering=8 * 1024 * 1024) as handle:
            while amount < bytes_to_read:
                chunk = handle.read(min(8 * 1024 * 1024, bytes_to_read - amount))
                if not chunk:
                    break
                amount += len(chunk)
                count += len(chunk)
        chosen.append({"filename": file.name, "bytes": count})
    seconds = time.perf_counter() - start
    return {
        "version": storage_version, "revision": manifest["revision"],
        "read_bytes": amount, "elapsed_s": seconds,
        "throughput_mib_s": amount / (1024**2) / seconds if seconds else None,
        "files": chosen, "cpu_reserved": 4, "ram_reserved_gib": 8,
        "cache_warning": "Sequential read may benefit from storage/host caching; compare repeated trials.",
    }


@app.function(image=image, cpu=4, memory=8192, timeout=240,
              volumes={"/cache": V1}, max_containers=1, scaledown_window=2)
def read_v1(bytes_to_read: int):
    V1.reload()
    return read_probe(1, bytes_to_read)


@app.function(image=image, cpu=4, memory=8192, timeout=240,
              volumes={"/cache": V2}, max_containers=1, scaledown_window=2)
def read_v2(bytes_to_read: int):
    V2.reload()
    return read_probe(2, bytes_to_read)


@app.local_entrypoint()
def main(read_gib: int = 4, repeats: int = 1, order: str = "v1-v2"):
    if not (1 <= read_gib <= 12 and 1 <= repeats <= 3):
        raise ValueError("read_gib=1..12, repeats=1..3")
    if order not in {"v1-v2", "v2-v1"}:
        raise ValueError("order=v1-v2 or v2-v1")
    versions = (1, 2) if order == "v1-v2" else (2, 1)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "read_gib": read_gib,
        "order": order,
        "results": [],
    }
    for _ in range(repeats):
        for version in versions:
            fn = read_v1 if version == 1 else read_v2
            report["results"].append(fn.remote(read_gib * GiB))
    folder = Path(__file__).resolve().parent.parent / "results" / "qwen_volume_ab"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("io_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("SAVED=" + str(path))
    print(json.dumps(report, ensure_ascii=False, indent=2))
