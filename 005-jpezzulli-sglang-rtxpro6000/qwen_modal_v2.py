"""Qwen3.8-Flash-Next / Penny Royal: bounded Modal memory experiments.

Original app.py and its results are left untouched.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import modal

from qwen_core.hardware import capture_hardware

from qwen_core.storage import MODEL_ID, MODEL_VOLUME, link_ready_model

GPU = "RTX-PRO-6000"
IMAGE_TAG = "ghcr.io/jpezzulli/sglang-rtxpro6000:v3.1.5"
COSTS = {"gpu": 0.000842, "cpu": 0.0000131, "ram": 0.00000222}
app = modal.App("005-qwen38-flashnext-memory-v2")

probe_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("numactl", "util-linux", "hwloc")
    .add_local_python_source('qwen_core')
)
# Preserve Penny Royal's patched Python venv; add only Modal's worker and cache contract.
penny_image = (
    modal.Image.from_registry(IMAGE_TAG, add_python="3.12")
    .entrypoint([])
    # Base Penny Royal image has no apt-get. Hardware commands are best-effort.
    # Never change the inference runtime image to install optional diagnostics.
    .add_local_python_source('qwen_core')
)


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _number(path):
    value = _read(path)
    return int(value) if value and value.isdecimal() else None


def _gpu():
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu,power.draw,compute_cap",
             "--format=csv,noheader,nounits"],
            text=True, capture_output=True, check=True, timeout=8,
        )
        fields = [x.strip() for x in p.stdout.splitlines()[0].split(",")]
        return dict(zip(
            ["name", "total_mib", "used_mib", "utilization_pct", "power_w", "compute_capability"],
            fields,
        ))
    except (OSError, subprocess.SubprocessError, IndexError) as exc:
        return {"error": repr(exc)}


def _ram():
    c = "/sys/fs/cgroup"
    v1 = c + "/memory"
    stats = {}
    raw_stat = (_read(c + "/memory.stat") or _read(v1 + "/memory.stat") or "")
    for line in raw_stat.splitlines():
        key, _, raw = line.partition(" ")
        if key in ("anon", "file", "unevictable", "kernel", "shmem",
                   "rss", "cache", "mapped_file", "total_rss", "total_cache") and raw.isdecimal():
            stats[key + "_bytes"] = int(raw)
    proc = {}
    for line in (_read("/proc/self/status") or "").splitlines():
        key, _, value = line.partition(":")
        if key in ("VmRSS", "VmHWM", "VmLck", "VmPin", "VmSize"):
            proc[key] = value.strip()
    return {
        "current_bytes": _number(c + "/memory.current") or _number(v1 + "/memory.usage_in_bytes"),
        "peak_bytes": _number(c + "/memory.peak") or _number(v1 + "/memory.max_usage_in_bytes"),
        "limit": _read(c + "/memory.max") or _read(v1 + "/memory.limit_in_bytes"),
        "cpu_quota": _read(c + "/cpu.max") or _read(c + "/cpu/cpu.cfs_quota_us"),
        "events": _read(c + "/memory.events") or _read(v1 + "/memory.failcnt"),
        "breakdown": stats,
        "process_memory": proc,
        "cgroup_self": _read("/proc/self/cgroup"),
    }


def _machine(include_commands: bool = True):
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    info = _read("/proc/cpuinfo") or ""
    model = next((x.split(":", 1)[1].strip() for x in info.splitlines()
                  if x.startswith("model name")), "unknown")
    return {
        "gpu": _gpu(),
        "memory": _ram(),
        "cpu_count": os.cpu_count(),
        "cpu_model": model,
        "pinned_memlock_limit_bytes": {"soft": soft, "hard": hard},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hardware_commands": capture_hardware() if include_commands else None,
    }


def _api(url, body=None, timeout=8):
    data = json.dumps(body).encode() if body else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.load(resp)


def _stream(model, prompt, max_tokens=128):
    request = urllib.request.Request(
        "http://127.0.0.1:8001/v1/chat/completions",
        data=json.dumps({
            "model": model, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": max_tokens, "stream": True,
            "stream_options": {"include_usage": True},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.monotonic()
    first = None
    pieces = []
    usage = {}
    with urllib.request.urlopen(request, timeout=170) as resp:
        for raw in resp:
            text = raw.decode("utf-8", errors="replace").strip()
            if not text.startswith("data:"):
                continue
            raw_json = text[5:].strip()
            if raw_json == "[DONE]":
                break
            try:
                chunk = json.loads(raw_json)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices", []):
                delta = choice.get("delta") or {}
                content = delta.get("content") or delta.get("reasoning_content") or ""
                if content:
                    if first is None:
                        first = time.monotonic()
                    pieces.append(content)
    stop = time.monotonic()
    tokens = usage.get("completion_tokens")
    decode_s = stop - first if first is not None else None
    return {
        "ttft_s": round(first - start, 3) if first is not None else None,
        "total_s": round(stop - start, 3),
        "decode_s": round(decode_s, 3) if decode_s is not None else None,
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": tokens,
        "output_tok_s": round((tokens - 1) / decode_s, 2)
        if isinstance(tokens, int) and decode_s and decode_s > 0 else None,
        "output_text": "".join(pieces)[:300],
        "token_rate_note": "Exact usage tokens; null if the server omits usage.",
    }


@app.function(image=probe_image, gpu=GPU, cpu=8, memory=131072,
              timeout=100, scaledown_window=2, max_containers=1)
def probe():
    before = _machine()
    buf = bytearray(128 * 1024 * 1024)
    buf[0] = 1
    during = _ram()
    del buf
    return {"stage": "probe", "before": before, "during": during}


@app.function(image=penny_image, gpu=GPU, cpu=8, memory=131072,
              timeout=900, scaledown_window=2, max_containers=1,
              volumes={"/cache": MODEL_VOLUME})
def infer(ram_gib: int, hicache_gb: int, max_seconds: int, cpu_cores: int = 8,
          workload: str = "smoke"):
    from qwen_core.profile import run_suite, parse_startup_log
    started = time.monotonic()
    deadline = started + max_seconds
    phase_state = {"current": "function_start"}
    def mark(stage):
        phase_state["current"] = stage
        result.setdefault("phase_marks", []).append({
            "phase": stage, "elapsed_s": round(time.monotonic()-started,3),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })
    result = {
        "stage": "infer", "success": False, "ram_gib": ram_gib, "cpu_cores": cpu_cores,
        "hicache_gb_decimal": hicache_gb, "model": MODEL_ID, "image": IMAGE_TAG,
        "workload": workload,
        "ple_backend": "ram", "nixl": "off", "before": _machine(),
        "profile_constraints": {
            "max_running_requests": 2, "gpu_count": 1,
            "ram_requested_gib": ram_gib, "cpu_cores_requested": cpu_cores,
            "note": "4-client batch is queued under engine max_running_requests=2",
        },
        "samples": [], "requests": [],
    }
    mark("hardware_recorded")
    # GPU only reads a committed Volume v2 snapshot; never downloads weights.
    try:
        MODEL_VOLUME.reload()
        model_path, cache_manifest = link_ready_model()
        result["model_cache"] = {
            "volume_version": 2,
            "revision": cache_manifest["revision"],
            "verified_files": len(cache_manifest["files"]),
            "model_path": model_path,
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        result["error"] = f"Model cache unavailable: {exc}"
        return result

    mark("volume_manifest_checked")
    env = os.environ.copy()
    env.update({
        "TARGET_MODEL": model_path,
        "CACHE_BASE": "/tmp/penny-cache",
        "NIXL": "off",
        "PENNY_PLE_BACKEND": "ram",
        "PENNY_HICACHE_SIZE_GB": str(hicache_gb),
        "TP_SIZE": "1", "MAX_RUNNING_REQUESTS": "2",
        "MAX_MAMBA_CACHE_SIZE": "12",
        "MAX_TOTAL_TOKENS": "131072",
        "PENNY_MTP_POLICY": "tiered",
        "SGLANG_MM_PREPROCESS_DEVICE": "cpu",
        "CUDA_VISIBLE_DEVICES": "0",
        "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4",
    })
    Path(env["CACHE_BASE"]).mkdir(parents=True, exist_ok=True)
    log_path = Path("/tmp/pennyroyal-infer.log")
    ended = threading.Event()

    def monitor():
        while not ended.is_set():
            cpu_stat = {}
            for line in (_read("/sys/fs/cgroup/cpu.stat") or "").splitlines():
                key, _, value = line.partition(" ")
                if value.isdecimal() and key in ("usage_usec","user_usec","system_usec",
                                                  "nr_throttled","throttled_usec"):
                    cpu_stat[key] = int(value)
            # Modal's Penny Royal image exposes cgroup v1 on some workers.
            # Keep CPU time as unknown rather than reporting a fabricated zero.
            if "usage_usec" not in cpu_stat:
                legacy_usage = _read("/sys/fs/cgroup/cpuacct/cpuacct.usage")
                if legacy_usage and legacy_usage.isdecimal():
                    cpu_stat["usage_usec"] = int(legacy_usage) // 1000
                    cpu_stat["source"] = "cgroup_v1_cpuacct"
            result["samples"].append({
                "elapsed_s": round(time.monotonic() - started, 2),
                "phase": phase_state["current"],
                "memory": _ram(), "gpu": _gpu(),
                "cpu_cgroup": cpu_stat,
            })
            ended.wait(1)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    proc = None
    try:
        with log_path.open("w", encoding="utf-8") as log:
            mark("pennyroyal_process_start")
            proc = subprocess.Popen(
                ["bash", "/opt/pennyroyal/configs/pennyroyal/serve-flash-next-frspec.sh"],
                stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True,
            )
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("Penny Royal exited: " + str(proc.returncode))
                try:
                    models = _api("http://127.0.0.1:8001/v1/models", timeout=2)
                    if models.get("data"):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise TimeoutError("Model did not become ready before the deadline")
            result["startup_s"] = round(time.monotonic() - started, 2)
            mark("api_models_ready")
            model = models["data"][0]["id"]
            result["served_model_id"] = model
            mark("smoke_warmup")
            for prompt in ("Reply with the single word READY.", "What is 17 times 23?"):
                if time.monotonic() + 175 >= deadline:
                    raise TimeoutError("Insufficient time left for the next request")
                result["requests"].append(_stream(model, prompt))
            result["success"] = all(x["output_text"] for x in result["requests"])
            result["answer_checks"] = {
                "ready_contains_expected": "READY" in result["requests"][0]["output_text"].upper(),
                "arithmetic_contains_391": "391" in result["requests"][1]["output_text"],
            }
            if workload == "profile":
                mark("profile_suite_start")
                result["profile_suite"] = run_suite(
                    model, deadline, max_running_requests=2,
                    phase_hook=mark,
                )
                result["profile_suite_ok"] = (
                    all("error" not in x for x in result["profile_suite"]["case_results"])
                    and all(x["all_requests_succeeded"]
                            for x in result["profile_suite"]["batch_results"])
                    and not result["profile_suite"]["skipped"]
                )
                result["success"] = result["success"] and result["profile_suite_ok"]
            if workload == "extended":
                # Real tokenizer usage is returned by SGLang, not inferred from characters.
                fragment = ("The experiment contains alpha beta gamma delta epsilon zeta eta "
                            "theta iota kappa and a verified checksum. ")
                result["long_context_tests"] = []
                for label, repeats in (("medium", 450), ("large", 1400)):
                    if time.monotonic() + 120 >= deadline:
                        raise TimeoutError("Insufficient budget for long-context benchmark")
                    prompt = fragment * repeats + "\nWhat is 17 times 23? Respond with 391."
                    measurement = _stream(model, prompt, 256)
                    measurement["label"] = label
                    result["long_context_tests"].append(measurement)
                result["long_context_passed"] = all(
                    "391" in t["output_text"] for t in result["long_context_tests"]
                )
                result["success"] = result["success"] and result["long_context_passed"]
                if time.monotonic() + 90 < deadline:
                    from concurrent.futures import ThreadPoolExecutor
                    start_batch = time.monotonic()
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        pair = list(pool.map(
                            lambda p: _stream(model, p, 128),
                            ("What is 17 times 23?", "Reply with READY."),
                        ))
                    duration = time.monotonic() - start_batch
                    tokens = [t.get("output_tokens") for t in pair]
                    result["concurrent_test"] = {
                        "duration_s": round(duration, 3),
                        "requests": pair,
                        "aggregate_output_tok_s": round(sum(tokens) / duration, 2)
                        if all(isinstance(v, int) for v in tokens) and duration > 0 else None,
                    }
    except Exception as exc:
        result["success"] = False
        result["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        mark("shutdown_begin")
        ended.set()
        thread.join(timeout=5)
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        result["elapsed_s"] = round(time.monotonic() - started, 2)
        result["after"] = _machine(include_commands=False)
        try:
            import base64
            import gzip
            import hashlib
            raw_log = log_path.read_bytes()
            result["raw_log_bytes"] = len(raw_log)
            result["raw_log_sha256"] = hashlib.sha256(raw_log).hexdigest()
            result["raw_log_archive_b64"] = base64.b64encode(gzip.compress(raw_log)).decode("ascii")
            result["log_phase_report"] = parse_startup_log(raw_log.decode("utf-8",errors="replace"))
            log_lines = raw_log.decode("utf-8", errors="replace").splitlines()
            result["log_tail"] = "\n".join(log_lines[-45:])
            keywords = ("load_weight", "load weight", "loading", "loaded",
                        "ple backend", "cuda graph", "compil", "warmup",
                        "model weights", "init memory", "mem usage")
            result["startup_events"] = [
                line[:600] for line in log_lines
                if any(keyword in line.lower() for keyword in keywords)
                and not line.lstrip().startswith("Multi-thread loading shards")
            ][:180]
        except OSError:
            result["log_tail"] = ""
            result["startup_events"] = []
    return result


def _rates(cores, ram, gpu=True):
    return (COSTS["gpu"] if gpu else 0) + cores * COSTS["cpu"] + ram * COSTS["ram"]


def _save(result, wall_s, ram):
    folder = Path(__file__).parent / "results" / "qwen_flash_next_v2"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = folder / (result.get("stage", "unknown") + "_" + str(ram) + "g_" + stamp + ".json")
    result["local_wall_s"] = round(wall_s, 2)
    rate = _rates(result.get("cpu_cores", 8), ram)
    result["estimated_usd"] = round(rate * wall_s, 5)
    result["cost_note"] = "Planning estimate, not an actual invoice; cold starts and memory/CPU metering can differ."
    import base64
    # Preserve the complete remote process log as a separate gzip artifact.
    archive = result.pop("raw_log_archive_b64", None)
    if archive is not None:
        archive_path = target.with_suffix(".log.gz")
        archive_path.write_bytes(base64.b64decode(archive))
        result["raw_log_archive_path"] = str(archive_path)
        print("LOG_ARCHIVE_FILE=" + str(archive_path), flush=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_FILE=" + str(target), flush=True)


@app.function(image=penny_image, gpu=GPU, cpu=8, memory=131072,
              timeout=180, scaledown_window=2, max_containers=1)
def pin_probe():
    """Measure CUDA pinned-host allocation capacity under Modal's memlock limit.

    Capped at 48 GiB, always freed; avoids downloading model weights first.
    """
    import ctypes
    import glob

    result = {"stage": "pin", "before": _machine(), "allocations": [],
              "target_gib": 48, "success": False}
    candidates = glob.glob("/usr/local/cuda*/lib64/libcudart.so*")
    library = next((p for p in candidates if ".so" in p), None)
    if library is None:
        result["error"] = "CUDA runtime library not found"
        return result
    cuda = ctypes.CDLL(library)
    cuda.cudaHostAlloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t,
                                   ctypes.c_uint]
    cuda.cudaHostAlloc.restype = ctypes.c_int
    cuda.cudaFreeHost.argtypes = [ctypes.c_void_p]
    cuda.cudaFreeHost.restype = ctypes.c_int
    allocations = []
    start = time.monotonic()
    # Reuse 4 GiB chunks, up to a 48 GiB bound. Stop on the first error.
    try:
        for n in range(1, 13):
            ptr = ctypes.c_void_p()
            error = cuda.cudaHostAlloc(ctypes.byref(ptr), 4 * 1024**3, 0)
            if error != 0:
                result["error"] = f"cudaHostAlloc failed at {n * 4} GiB: code={error}"
                break
            allocations.append(ptr)
            result["allocations"].append({
                "allocated_gib": n * 4, "elapsed_s": round(time.monotonic() - start, 2),
                "memory": _ram(),
            })
            if time.monotonic() - start >= 145:
                result["error"] = "stopped at 145s safety deadline"
                break
        result["success"] = len(allocations) == 12
    except Exception as exc:
        result["error"] = repr(exc)
    finally:
        for ptr in reversed(allocations):
            cuda.cudaFreeHost(ptr)
        result["after"] = _machine()
        result["elapsed_s"] = round(time.monotonic() - start, 2)
    return result


@app.local_entrypoint()
def main(stage: str = "probe", ram_gib: int = 128, hicache_gb: int = 8,
         max_seconds: int = 540, budget_usd: float = 1.5,
         cpu_cores: int = 8, workload: str = "smoke"):
    if stage not in {"probe", "pin", "infer"}:
        raise ValueError("stage = probe | pin | infer; use qwen_download.py for CPU-only downloads")
    if workload not in {"smoke", "extended", "profile"}:
        raise ValueError("workload = smoke | extended | profile")
    if not 32 <= ram_gib <= 256 or not 1 <= hicache_gb <= 64:
        raise ValueError("ram_gib = 32..256; hicache_gb = 1..64")
    if not 2 <= cpu_cores <= 16:
        raise ValueError("cpu_cores = 2..16")
    if not 60 <= max_seconds <= 870:
        raise ValueError("max_seconds = 60..870")
    if budget_usd <= 0:
        raise ValueError("budget_usd must be positive")
    reservation = (180 * _rates(8, 128) if stage == "pin" else
                   100 * _rates(8, 128) if stage == "probe" else
                   max_seconds * _rates(cpu_cores, ram_gib))
    if reservation > budget_usd:
        raise ValueError("Estimated preflight cost {:.3f} USD exceeds budget {:.3f} USD. "
                         "Not an account-level charge limit.".format(reservation, budget_usd))
    print("STAGE={} CPU={} RAM={}GiB HICACHE={}GB UPPER_ESTIMATE={:.3f}USD".format(
        stage, cpu_cores, ram_gib, hicache_gb, reservation), flush=True)
    start = time.monotonic()
    try:
        if stage == "probe":
            output = probe.remote()
        elif stage == "pin":
            output = pin_probe.remote()
        else:
            custom = infer.with_options(memory=ram_gib * 1024, cpu=cpu_cores,
                                        timeout=max_seconds + 30)
            output = custom.remote(ram_gib, hicache_gb, max_seconds, cpu_cores, workload)
    except Exception as exc:
        _save({"stage": stage, "success": False, "remote_error": repr(exc)},
              time.monotonic() - start, ram_gib)
        raise
    _save(output, time.monotonic() - start, ram_gib)
    print("SUCCESS={} ERROR={}".format(output.get("success"), output.get("error", "")))
