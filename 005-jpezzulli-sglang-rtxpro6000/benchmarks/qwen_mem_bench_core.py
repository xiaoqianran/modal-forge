"""Bounded, dependency-light CPU-memory and CUDA memcpy microbenchmarks.

CPU: official STREAM executable, deterministic random pointer-chasing C program.
GPU: CUDA Runtime synchronous cudaMemcpy, pageable vs page-locked memory.
Time measurements include runtime memcpy API overhead; not GPU compute throughput.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import statistics
import subprocess
import time

MIB = 1024 * 1024


def _run(command: list[str], *, timeout: int = 35, env: dict | None = None) -> dict:
    start = time.monotonic()
    try:
        p = subprocess.run(
            command, capture_output=True, text=True, errors="replace",
            timeout=timeout, env={**os.environ, **(env or {})},
        )
        return {
            "exit_code": p.returncode, "elapsed_s": round(time.monotonic() - start, 3),
            "stdout": p.stdout[-16000:], "stderr": p.stderr[-1500:],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "exit_code": None, "elapsed_s": round(time.monotonic() - start, 3),
            "stdout": "", "stderr": repr(exc),
        }


def cpu_memory_tests(*, max_seconds: float = 60) -> dict:
    start = time.monotonic()
    out = {"stream": {}, "pointer_chase": [], "limitations": []}
    for threads in (1, 4):
        if time.monotonic() - start >= max_seconds - 15:
            out["limitations"].append("CPU STREAM stopped by total test budget")
            break
        out["stream"][str(threads)] = _run(
            ["/usr/local/bin/stream"], timeout=23,
            env={"OMP_NUM_THREADS": str(threads), "OMP_PROC_BIND": "true",
                 "OMP_PLACES": "cores"},
        )
        lines = out["stream"][str(threads)].get("stdout", "").splitlines()
        metrics = {}
        for line in lines:
            fields = line.split()
            if len(fields) >= 2 and fields[0].rstrip(":") in ("Copy", "Scale", "Add", "Triad"):
                try:
                    metrics[fields[0].rstrip(":")] = float(fields[1])
                except ValueError:
                    continue
        out["stream"][str(threads)]["best_mb_s"] = metrics
    for mib in (8, 64, 256):
        if time.monotonic() - start >= max_seconds - 8:
            out["limitations"].append("Pointer chase skipped remaining sizes due to time budget")
            break
        item = _run(["/usr/local/bin/qwen-pointer-chase", str(mib), "2"], timeout=18)
        item["working_set_mib"] = mib
        try:
            item["measurement"] = json.loads(item["stdout"].strip().splitlines()[-1])
        except (ValueError, IndexError, KeyError):
            item["measurement"] = None
        out["pointer_chase"].append(item)
    out["elapsed_s"] = round(time.monotonic() - start, 3)
    out["interpretation"] = (
        "STREAM is effective bandwidth for requested CPU quota, not host theoretical DDR bandwidth; "
        "pointer chasing includes cache/TLB effects and virtualized NUMA, not pure DRAM latency."
    )
    return out


class CudaMemcpy:
    def __init__(self):
        self.lib = ctypes.CDLL("libcudart.so.12")
        self.lib.cudaSetDevice.argtypes = [ctypes.c_int]
        self.lib.cudaSetDevice.restype = ctypes.c_int
        self.lib.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        self.lib.cudaMalloc.restype = ctypes.c_int
        self.lib.cudaFree.argtypes = [ctypes.c_void_p]
        self.lib.cudaFree.restype = ctypes.c_int
        self.lib.cudaHostAlloc.argtypes = [
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t, ctypes.c_uint,
        ]
        self.lib.cudaHostAlloc.restype = ctypes.c_int
        self.lib.cudaFreeHost.argtypes = [ctypes.c_void_p]
        self.lib.cudaFreeHost.restype = ctypes.c_int
        self.lib.cudaMemcpy.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
        ]
        self.lib.cudaMemcpy.restype = ctypes.c_int
        self.lib.cudaDeviceSynchronize.argtypes = []
        self.lib.cudaDeviceSynchronize.restype = ctypes.c_int
        self._ok(self.lib.cudaSetDevice(0), "cudaSetDevice")

    @staticmethod
    def _ok(code: int, op: str):
        if code:
            raise RuntimeError(f"{op} returned CUDA error {code}")

    def alloc_device(self, n: int) -> ctypes.c_void_p:
        ptr = ctypes.c_void_p()
        self._ok(self.lib.cudaMalloc(ctypes.byref(ptr), n), "cudaMalloc")
        return ptr

    def alloc_pinned(self, n: int) -> ctypes.c_void_p:
        ptr = ctypes.c_void_p()
        self._ok(self.lib.cudaHostAlloc(ctypes.byref(ptr), n, 0), "cudaHostAlloc")
        return ptr

    def copy(self, dst: ctypes.c_void_p, src: ctypes.c_void_p, n: int,
             kind: int) -> float:
        start = time.perf_counter()
        self._ok(self.lib.cudaMemcpy(dst, src, n, kind), "cudaMemcpy")
        self._ok(self.lib.cudaDeviceSynchronize(), "cudaDeviceSynchronize")
        return time.perf_counter() - start


def gpu_transfer_tests(*, sizes_mib: tuple[int, ...] = (1, 32, 128),
                       max_seconds: float = 40) -> dict:
    result = {"samples": [], "errors": [],
              "measurement": "sync cudaMemcpy + device sync wall time; pageable/pinned H2D and D2H",
              "unit": "MiB/s (payload bytes / wall seconds)"}
    start = time.monotonic()
    try:
        cuda = CudaMemcpy()
    except (OSError, RuntimeError) as exc:
        result["errors"].append("CUDA runtime unavailable: " + repr(exc))
        return result
    for size in sizes_mib:
        if time.monotonic() - start > max_seconds - 6:
            result["errors"].append("Stopped before next size due to time budget")
            break
        n = size * MIB
        device = None
        pinned = None
        try:
            device = cuda.alloc_device(n)
            pinned = cuda.alloc_pinned(n)
            page_arr = ctypes.create_string_buffer(n)
            page = ctypes.c_void_p(ctypes.addressof(page_arr))
            ctypes.memset(page, 73, n)
            ctypes.memset(pinned, 73, n)
            for category, host in (("pageable", page), ("pinned", pinned)):
                for direction, kind in (("H2D", 1), ("D2H", 2)):
                    dst, src = (device, host) if direction == "H2D" else (host, device)
                    cuda.copy(dst, src, n, kind)
                    timings = [cuda.copy(dst, src, n, kind) for _ in range(3)]
                    median = statistics.median(timings)
                    result["samples"].append({
                        "host_memory": category, "direction": direction,
                        "size_mib": size, "trials_s": timings,
                        "median_s": round(median, 6),
                        "effective_mib_s": round(size / median, 2),
                    })
        except (OSError, RuntimeError) as exc:
            result["errors"].append(f"CUDA {size}MiB: {type(exc).__name__}: {exc}")
        finally:
            if pinned is not None:
                cuda.lib.cudaFreeHost(pinned)
            if device is not None:
                cuda.lib.cudaFree(device)
    result["elapsed_s"] = round(time.monotonic() - start, 3)
    return result


def volume_to_gpu_once(path: str, *, mib: int = 256,
                       cuda: CudaMemcpy | None = None) -> dict:
    """Time uncompressed Volume read, host->pinned copy and GPU upload separately.

    Python bytes plus cudaHostAlloc pinned buffer are held concurrently.
    This is a staged baseline, not actual SGLang/Penny Royal weight-loading code.
    """
    started = time.perf_counter()
    obj = cuda or CudaMemcpy()
    n = mib * MIB
    device = None
    pinned = None
    try:
        ts = time.perf_counter()
        with open(path, "rb", buffering=0) as reader:
            data = reader.read(n)
        file_s = time.perf_counter() - ts
        if len(data) != n:
            raise IOError(f"Expected {n} bytes, got {len(data)}")
        ts = time.perf_counter()
        pinned = obj.alloc_pinned(n)
        ctypes.memmove(pinned, data, n)
        copy_s = time.perf_counter() - ts
        del data
        device = obj.alloc_device(n)
        copy_gpu_s = obj.copy(device, pinned, n, 1)
        return {
            "size_mib": mib, "read_s": round(file_s, 6),
            "cpu_to_pinned_copy_s": round(copy_s, 6),
            "pinned_to_gpu_s": round(copy_gpu_s, 6),
            "total_s": round(time.perf_counter() - started, 6),
            "note": "Includes pinning and cudaMalloc overhead in total_s, not in transfer_s.",
        }
    finally:
        if pinned is not None:
            obj.lib.cudaFreeHost(pinned)
        if device is not None:
            obj.lib.cudaFree(device)
