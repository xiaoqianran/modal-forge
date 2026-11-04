"""CPU-only Volume v1/v2 read comparison.

Does not re-download weights or initialize Qwen/Penny Royal.
v1/v2 cache paths are *read-only* for every benchmark.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from legacy.qwen_storage_v1 import MODEL_VOLUME as V1
from qwen_core.storage import MODEL_VOLUME as V2

app = modal.App("005-qwen-volume-cpu-benchmark")
cpu_image = modal.Image.debian_slim(python_version="3.12").add_local_python_source(
    "legacy", "qwen_core", "benchmarks"
)

MIB = 1024 * 1024
GIB = 1024 * MIB
MODEL_SLUG = "models--RadixArk--Qwen3.8-Flash-Next-NVFP4"
PINNED_REVISION = "7b719225242aacd3dbd3f9407468c2ee9a9d2594"


def model_file(root_mount: str) -> tuple[Path, dict]:
    base = Path(root_mount)
    ready = json.loads((base / ".qwen-model-ready.json").read_text("utf-8"))
    if ready.get("revision") != PINNED_REVISION:
        raise RuntimeError("Unexpected revision; refusing to compare different model weights")
    path = base / MODEL_SLUG / "snapshots" / PINNED_REVISION / "model-bf16-00011.safetensors"
    if not path.is_file() or path.stat().st_size < 4 * GIB:
        raise RuntimeError(f"Expected real >=4 GiB weight shard not present: {path}")
    return path, ready


def io_cpu(version: int, gib_to_read: int = 4) -> dict:
    mount = "/cache"
    path, manifest = model_file(mount)
    start = time.monotonic()
    total = path.stat().st_size
    random_records = []
    # Small random 4KiB and 64KiB unaligned-ish preads; deliberately sampled
    # BEFORE large sequential scans to reduce same-process page-cache heating.
    rng = random.Random(159026)
    fd = os.open(path, os.O_RDONLY)
    try:
        for block in (4096, 65536):
            offsets = [rng.randrange(0, total - block) for _ in range(256)]
            ts = time.perf_counter()
            actual = 0
            checksum = 0
            for offset in offsets:
                data = os.pread(fd, block, offset)
                actual += len(data)
                checksum ^= data[0] if data else 0
            elapsed = time.perf_counter() - ts
            random_records.append({
                "block_bytes": block, "ops": 256, "bytes": actual,
                "wall_s": round(elapsed, 6),
                "mean_ms_per_op": round(elapsed * 1000 / 256, 5),
                "ops_per_sec": round(256 / elapsed, 2),
                "checksum": checksum,
            })
    finally:
        os.close(fd)
    seq = []
    for cap in (1, gib_to_read):
        for trial in (1, 2):
            amt = 0
            checksum = 0
            ts = time.perf_counter()
            with path.open("rb", buffering=0) as source:
                while amt < cap * GIB:
                    data = source.read(min(8 * MIB, cap * GIB - amt))
                    if not data:
                        break
                    amt += len(data)
                    checksum ^= data[0]
            elapsed = time.perf_counter() - ts
            seq.append({
                "gib": cap, "trial": trial, "bytes": amt,
                "elapsed_s": round(elapsed, 5),
                "mib_s": round(amt / MIB / elapsed, 2),
                "checksum": checksum,
            })
    return {
        "volume_version": version, "sha": manifest["revision"],
        "file": path.name, "file_size_bytes": total,
        "cpu_reserved": 4, "ram_reserved_gib": 8,
        "random": random_records, "sequential": seq,
        "elapsed_s": round(time.monotonic() - start, 3),
        "warning": "OS page cache and Volume backend caching are uncontrolled; random reads are not O_DIRECT.",
    }


@app.function(image=cpu_image, cpu=4, memory=8192, timeout=125,
              volumes={"/cache": V1}, max_containers=1, scaledown_window=2)
def cpu_v1():
    V1.reload()
    return io_cpu(1)


@app.function(image=cpu_image, cpu=4, memory=8192, timeout=125,
              volumes={"/cache": V2}, max_containers=1, scaledown_window=2)
def cpu_v2():
    V2.reload()
    return io_cpu(2)


@app.local_entrypoint()
def main(order: str = "v1-v2"):
    if order not in ("v1-v2", "v2-v1"):
        raise ValueError("order must be v1-v2 or v2-v1")
    start = time.monotonic()
    result = {"order": order, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "results": [], "errors": []}
    for version in ((1, 2) if order == "v1-v2" else (2, 1)):
        fn = cpu_v1 if version == 1 else cpu_v2
        try:
            payload = fn.remote()
            result["results"].append(payload)
            print("CPU_IO_COMPLETE=v" + str(version), flush=True)
        except Exception as exc:
            result["errors"].append(f"v{version}: {type(exc).__name__}: {exc}")
    result["wall_s"] = round(time.monotonic() - start, 3)
    folder = Path(__file__).resolve().parent.parent / "results" / "qwen_benchmark"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ("volume_cpu_" + order.replace("-", "_") + "_"
                       + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("RESULT_FILE=" + str(target), flush=True)
    print("SUCCESS=" + str(len(result["results"]) == 2 and not result["errors"]), flush=True)
    for item in result["results"]:
        print("SUMMARY=" + str({
            "volume_version": item["volume_version"],
            "seq_mib_s": [v["mib_s"] for v in item["sequential"]],
            "random_ops_per_s": [v["ops_per_sec"] for v in item["random"]],
        }), flush=True)
    for err in result["errors"]:
        print("ERROR=" + err, flush=True)
