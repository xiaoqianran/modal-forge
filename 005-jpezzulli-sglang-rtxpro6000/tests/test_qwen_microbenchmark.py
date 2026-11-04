"""Offline checks for benchmark units and result semantics. No Modal calls."""
from __future__ import annotations

import ctypes
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks import qwen_mem_bench_core as core


class _FakeCuda:
    def __init__(self):
        self.buffers = []
        self.lib = self

    def alloc_device(self, n):
        buf = ctypes.create_string_buffer(n)
        self.buffers.append(buf)
        return ctypes.c_void_p(ctypes.addressof(buf))

    def alloc_pinned(self, n):
        return self.alloc_device(n)

    def copy(self, dst, src, n, kind):
        ctypes.memmove(dst, src, n)
        return 0.01

    def cudaFreeHost(self, p):
        return 0

    def cudaFree(self, p):
        return 0


class BenchTests(unittest.TestCase):
    def test_stream_parser_extracts_triad(self):
        fake = {
            "exit_code": 0,
            "stdout": "Copy: 12000 0.2 0.1 0.3\nTriad: 26000 0.2 0.1 0.3\n",
            "stderr": "", "elapsed_s": 0.3,
        }
        fake_latency = {
            "exit_code": 0,
            "stdout": json.dumps({"working_set_mib": 8, "ns_per_access": 125}),
            "stderr": "", "elapsed_s": 0.3,
        }
        with patch.object(core, "_run", side_effect=[
            fake, fake, fake_latency, fake_latency, fake_latency,
        ]):
            data = core.cpu_memory_tests(max_seconds=80)
        self.assertEqual(data["stream"]["4"]["best_mb_s"]["Triad"], 26000)
        self.assertEqual(data["pointer_chase"][0]["measurement"]["ns_per_access"], 125)

    def test_host_gpu_staging_split_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "weights.bin"
            path.write_bytes(b"Q" * core.MIB)
            out = core.volume_to_gpu_once(str(path), mib=1, cuda=_FakeCuda())
        self.assertEqual(out["size_mib"], 1)
        self.assertEqual(out["pinned_to_gpu_s"], 0.01)
        self.assertGreaterEqual(out["total_s"], out["read_s"])

    def test_memcpy_sampling_dimensions(self):
        with patch.object(core, "CudaMemcpy", _FakeCuda):
            result = core.gpu_transfer_tests(sizes_mib=(1,))
        self.assertFalse(result["errors"], result["errors"])
        self.assertEqual(len(result["samples"]), 4)
        self.assertEqual(
            {(x["host_memory"], x["direction"]) for x in result["samples"]},
            {("pageable", "H2D"), ("pageable", "D2H"),
             ("pinned", "H2D"), ("pinned", "D2H")},
        )


if __name__ == "__main__":
    unittest.main()
