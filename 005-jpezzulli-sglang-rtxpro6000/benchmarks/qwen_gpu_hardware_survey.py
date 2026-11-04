"""One-shot, low-cost GPU host survey: no model downloads or memory benchmark."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from qwen_core.hardware import capture_hardware

app = modal.App("005-gpu-hardware-survey")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("util-linux", "numactl", "hwloc")
    .add_local_python_source("qwen_core")
)


def capture(requested: str) -> dict:
    start = time.monotonic()
    result = capture_hardware()
    result["requested_gpu"] = requested
    result["elapsed_s"] = round(time.monotonic() - start, 3)
    result["cpu_reserved"] = 1
    result["memory_reserved_mib"] = 1024
    return result


@app.function(image=image, gpu="T4", cpu=1, memory=1024,
              timeout=90, scaledown_window=2, max_containers=1)
def t4(): return capture("T4")


@app.function(image=image, gpu="L4", cpu=1, memory=1024,
              timeout=90, scaledown_window=2, max_containers=1)
def l4(): return capture("L4")


@app.function(image=image, gpu="L40S", cpu=1, memory=1024,
              timeout=90, scaledown_window=2, max_containers=1)
def l40s(): return capture("L40S")


@app.function(image=image, gpu="A100", cpu=1, memory=1024,
              timeout=90, scaledown_window=2, max_containers=1)
def a100(): return capture("A100")


@app.function(image=image, gpu="RTX-PRO-6000", cpu=1, memory=1024,
              timeout=90, scaledown_window=2, max_containers=1)
def pro6000(): return capture("RTX-PRO-6000")


@app.local_entrypoint()
def main(gpu: str = "all"):
    functions = {
        "T4": t4, "L4": l4, "L40S": l40s,
        "A100": a100, "RTX-PRO-6000": pro6000,
    }
    if gpu.upper() != "ALL" and gpu.upper() not in functions:
        raise ValueError("Choose all, T4, L4, L40S, A100 or RTX-PRO-6000")
    selected = functions if gpu.upper() == "ALL" else {gpu.upper(): functions[gpu.upper()]}
    output_dir = Path(__file__).resolve().parent.parent / "results" / "gpu_hardware"
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in selected.items():
        started = time.monotonic()
        try:
            result = fn.remote()
            result["success"] = True
        except Exception as exc:
            result = {
                "requested_gpu": name, "success": False, "error": repr(exc),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        result["wall_seconds"] = round(time.monotonic() - started, 3)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = output_dir / (name.lower().replace("-", "_") + "_" + stamp + ".json")
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        cmds = result.get("commands", {})
        gpu_details = cmds.get("nvidia-smi -q", {}).get("stdout", "")
        product = next(
            (line.strip() for line in gpu_details.splitlines()
             if line.strip().startswith("Product Name")),
            "GPU product unavailable",
        )
        print(
            f"GPU={name} OK={result['success']} CPU={result.get('cpu_model')} "
            f"PRODUCT={product} WALL={result['wall_seconds']}s SAVED={path}",
            flush=True,
        )
        if not result["success"]:
            print("ERROR=" + result["error"], flush=True)
