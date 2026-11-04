"""RTX PRO 6000 Volume v1/v2 to GPU path comparison.

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
from benchmarks.qwen_mem_bench_core import CudaMemcpy, volume_to_gpu_once

app = modal.App("005-qwen-volume-gpu-benchmark")
cpu_image = modal.Image.debian_slim(python_version="3.12").add_local_python_source(
    "legacy", "qwen_core", "benchmarks"
)
gpu_image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-runtime-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .add_local_python_source("legacy", "qwen_core", "benchmarks")
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


@app.function(image=gpu_image, gpu="RTX-PRO-6000", cpu=4, memory=8192,
              timeout=150, scaledown_window=2, max_containers=1,
              volumes={"/v1": V1, "/v2": V2})
def volume_to_gpu() -> dict:
    V1.reload()
    V2.reload()
    start = time.monotonic()
    paths = {}
    manifests = {}
    for version in (1, 2):
        path, manifest = model_file(f"/v{version}")
        paths[version] = path
        manifests[version] = manifest
    cuda = CudaMemcpy()
    measurements = []
    # Alternate order on second trial. This is a staging baseline, not zero-copy.
    for trial, versions in ((1, (1, 2)), (2, (2, 1))):
        for version in versions:
            item = volume_to_gpu_once(str(paths[version]), mib=256, cuda=cuda)
            item.update(volume_version=version, trial=trial, mode="volume_direct_staged")
            measurements.append(item)
    # Optional prefetch on local ephemeral storage, including copy overhead.
    # 256 MiB only; never copies the whole 126.9 GiB model.
    prefetch = []
    with tempfile.TemporaryDirectory(prefix="qwen-volume-probe-") as temp:
        for version in (1, 2):
            dest = Path(temp) / f"v{version}_weight_chunk.bin"
            ts = time.perf_counter()
            with paths[version].open("rb", buffering=0) as src, dest.open("wb", buffering=0) as out:
                remaining = 256 * MIB
                while remaining:
                    chunk = src.read(min(8 * MIB, remaining))
                    if not chunk:
                        raise IOError("Short volume read during local staging")
                    out.write(chunk)
                    remaining -= len(chunk)
            copy_s = time.perf_counter() - ts
            item = volume_to_gpu_once(str(dest), mib=256, cuda=cuda)
            item.update(volume_version=version, mode="prefetch_local_then_gpu",
                        prefetch_copy_s=round(copy_s, 6),
                        combined_wall_s=round(copy_s + item["total_s"], 6),
                        local_path=str(dest))
            prefetch.append(item)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "gpu": "RTX-PRO-6000", "cpu_reserved": 4, "ram_reserved_gib": 8,
        "revision": PINNED_REVISION,
        "weights": {str(k): manifests[k]["volume_version"] for k in (1, 2)},
        "direct": measurements, "prefetch": prefetch,
        "elapsed_s": round(time.monotonic() - start, 3),
        "success": True,
        "limitations": [
            "256MiB staging is not representative of entire 126.9GiB Penny Royal model startup",
            "Observed memory reads may use kernel file cache",
            "Local /tmp may have different persistence/IO path from a dedicated SSD",
            "No GPUDirect Storage; CUDA uses explicit host-pinned copy",
        ],
    }


@app.local_entrypoint()
def main():
    start = time.monotonic()
    result = {"stage": "gpu", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "results": [], "errors": []}
    try:
        result["results"].append(volume_to_gpu.remote())
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    result["wall_s"] = round(time.monotonic() - start, 3)
    folder = Path(__file__).resolve().parent.parent / "results" / "qwen_benchmark"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ("volume_gpu_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("RESULT_FILE=" + str(target), flush=True)
    print("SUCCESS=" + str(bool(result["results"]) and not result["errors"]), flush=True)
    for item in result["results"]:
        print("GPU_DIRECT=" + str([(v["volume_version"], v["trial"], v["total_s"]) for v in item["direct"]]), flush=True)
        print("GPU_PREFETCH=" + str([(v["volume_version"], v["combined_wall_s"]) for v in item["prefetch"]]), flush=True)
    for err in result["errors"]:
        print("ERROR=" + err, flush=True)
