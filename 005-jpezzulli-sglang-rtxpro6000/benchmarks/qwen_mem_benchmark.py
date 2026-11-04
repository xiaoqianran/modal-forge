"""Memory and PCIe microbenchmarks; no model and no model Volume mounted.

Four GPUs share exactly the same container image, 4 CPU cores and 8 GiB RAM.
GPU reservation and runtime are intentionally bounded to reduce Modal spend.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from qwen_core.hardware import capture_hardware
from benchmarks.qwen_mem_bench_core import cpu_memory_tests, gpu_transfer_tests

app = modal.App("005-qwen-memory-microbenchmark")
GPU_IMAGE_TAG = "nvidia/cuda:12.8.1-runtime-ubuntu22.04"
image = (
    modal.Image.from_registry(GPU_IMAGE_TAG, add_python="3.12")
    .entrypoint([])
    .apt_install("gcc", "libgomp1", "numactl", "util-linux", "curl", "hwloc")
    .add_local_file(str(Path(__file__).with_name("qwen_pointer_chase.c")), "/opt/qwen_bench/ptr_chase.c", copy=True)
    .run_commands(
        "curl --fail --location --silent --show-error --retry 2 "
        "--max-time 20 https://www.cs.virginia.edu/stream/FTP/Code/stream.c "
        "-o /opt/qwen_bench/stream.c",
        "gcc -O3 -fopenmp -DSTREAM_ARRAY_SIZE=50000000 -DNTIMES=8 "
        "/opt/qwen_bench/stream.c -o /usr/local/bin/stream",
        "gcc -O3 -std=c11 /opt/qwen_bench/ptr_chase.c "
        "-o /usr/local/bin/qwen-pointer-chase",
    )
    .add_local_python_source("qwen_core", "benchmarks")
)


def run_probe(name: str) -> dict:
    started = time.monotonic()
    result = {
        "gpu_requested": name,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "cpu_cores_reserved": 4,
        "ram_gib_reserved": 8,
        "image": GPU_IMAGE_TAG,
        "hardware": capture_hardware(),
    }
    result["cpu_ram"] = cpu_memory_tests(max_seconds=58)
    result["pcie"] = gpu_transfer_tests(max_seconds=35)
    result["elapsed_s"] = round(time.monotonic() - started, 3)
    result["success"] = bool(result["cpu_ram"]["stream"]) and bool(result["pcie"]["samples"])
    return result


@app.function(image=image, gpu="T4", cpu=4, memory=8192,
              timeout=125, scaledown_window=2, max_containers=1)
def t4(): return run_probe("T4")


@app.function(image=image, gpu="A100-40GB", cpu=4, memory=8192,
              timeout=125, scaledown_window=2, max_containers=1)
def a100(): return run_probe("A100-40GB")


@app.function(image=image, gpu="L40S", cpu=4, memory=8192,
              timeout=125, scaledown_window=2, max_containers=1)
def l40s(): return run_probe("L40S")


@app.function(image=image, gpu="RTX-PRO-6000", cpu=4, memory=8192,
              timeout=125, scaledown_window=2, max_containers=1)
def pro6000(): return run_probe("RTX-PRO-6000")


@app.local_entrypoint()
def main(gpu: str = "t4"):
    choices = {"t4": t4, "a100": a100, "l40s": l40s, "pro6000": pro6000}
    if gpu.lower() not in choices:
        raise ValueError("gpu must be one of: t4, a100, l40s, pro6000")
    started = time.monotonic()
    key = gpu.lower()
    try:
        result = choices[key].remote()
    except Exception as exc:
        result = {
            "gpu_requested": key, "success": False,
            "error": type(exc).__name__ + ": " + str(exc),
        }
    result["wall_seconds"] = round(time.monotonic() - started, 3)
    folder = Path(__file__).resolve().parent.parent / "results" / "qwen_benchmark"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = folder / (f"memory_{key}_{stamp}.json")
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("RESULT_FILE=" + str(target), flush=True)
    print("SUCCESS=" + str(result.get("success")), flush=True)
    ram = result.get("cpu_ram", {})
    pcie = result.get("pcie", {})
    print("STREAM_TRIAD_MBPS=" + str({
        k: v.get("best_mb_s", {}).get("Triad")
        for k, v in ram.get("stream", {}).items()
    }), flush=True)
    print("RANDOM_LATENCY_NS=" + str([
        (x.get("working_set_mib"), (x.get("measurement") or {}).get("ns_per_access"))
        for x in ram.get("pointer_chase", [])
    ]), flush=True)
    print("GPU_SAMPLES=" + str(len(pcie.get("samples", []))), flush=True)
    if result.get("error"):
        print("ERROR=" + result["error"], flush=True)
