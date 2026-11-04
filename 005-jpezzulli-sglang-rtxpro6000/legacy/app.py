"""Probe Modal's default system RAM allocation without setting memory or cpu."""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import modal

app = modal.App("005-jpezzulli-sglang-rtxpro6000")
IMAGE = modal.Image.debian_slim(python_version="3.12")


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _probe(gpu_type: str) -> dict:
    out = {
        "requested_gpu": gpu_type,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": os.uname().nodename,
        "meminfo": {
            k: v.strip()
            for line in (_read("/proc/meminfo") or "").splitlines()
            if ":" in line
            for k, v in [line.split(":", 1)]
            if k in ("MemTotal", "MemAvailable", "MemFree")
        },
        "cgroup_v2": {
            "memory_max_bytes": _read("/sys/fs/cgroup/memory.max"),
            "memory_high_bytes": _read("/sys/fs/cgroup/memory.high"),
            "memory_current_bytes": _read("/sys/fs/cgroup/memory.current"),
            "cpu_max": _read("/sys/fs/cgroup/cpu.max"),
            "memory_limit_v1_bytes": _read("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
            "memory_usage_v1_bytes": _read("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
        },
    }
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        out["gpu_smi_csv_memory_mib"] = p.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        out["gpu_smi_error"] = str(exc)
    print("GPU_PROBE=" + json.dumps(out, ensure_ascii=False, sort_keys=True), flush=True)
    return out


@app.function(image=IMAGE, gpu="T4", timeout=90, scaledown_window=2)
def probe_t4():
    return _probe("T4")


@app.function(image=IMAGE, gpu="L4", timeout=90, scaledown_window=2)
def probe_l4():
    return _probe("L4")


@app.function(image=IMAGE, gpu="L40S", timeout=90, scaledown_window=2)
def probe_l40s():
    return _probe("L40S")


@app.local_entrypoint()
def main(gpu: str = "all"):
    gpu = gpu.upper()
    functions = (("T4", probe_t4), ("L4", probe_l4), ("L40S", probe_l40s))
    if gpu not in ("ALL", "T4", "L4", "L40S"):
        raise ValueError("gpu must be all, T4, L4, or L40S")
    results = []
    for name, fn in functions:
        if gpu != "ALL" and name != gpu:
            continue
        try:
            results.append(fn.remote())
        except Exception as exc:
            results.append({"requested_gpu": name, "error": str(exc)})
    folder = Path(__file__).resolve().parent.parent / "results" / "default_gpu"
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / ("results_" + gpu.lower() + ".json")
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nSaved:", output)
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
