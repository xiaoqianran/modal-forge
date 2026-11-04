"""Project relocation guards: import topology and report/result paths only.

All tests are local. Do not start a Modal function or modify remote Volumes.
"""
from __future__ import annotations

import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class LayoutTests(unittest.TestCase):
    def test_entrypoints_and_packages_import(self):
        names = (
            "qwen_modal_v2", "qwen_download_v2",
            "qwen_core.storage", "qwen_core.hardware", "qwen_core.profile",
            "benchmarks.qwen_opt_experiment",
            "benchmarks.qwen_compiler_cache",
            "benchmarks.qwen_opt_ple_profile",
            "benchmarks.qwen_mem_benchmark",
            "benchmarks.qwen_volume_gpu_benchmark",
            "legacy.qwen_modal_v1", "legacy.qwen_download_v1", "legacy.app",
        )
        for name in names:
            with self.subTest(name=name):
                importlib.import_module(name)

    def test_stable_entrypoint_optional_compiler_cache(self):
        import ast
        source = (ROOT / "qwen_modal_v2.py").read_text(encoding="utf-8")
        funcs = {n.name: n for n in ast.parse(source).body
                 if isinstance(n, ast.FunctionDef)}
        for name in ("main", "infer"):
            f = funcs[name]
            self.assertEqual(f.args.args[-1].arg, "compiler_cache")
            self.assertEqual(ast.literal_eval(f.args.defaults[-1]), "off")
        self.assertIn('"/compiler-vol": COMPILER_VOLUME', source)
        self.assertIn(".add_local_python_source('qwen_core', 'benchmarks')", source)
        self.assertIn('result["compiler_cache"]["status"] = "restored"', source)
        self.assertIn('result["compiler_cache"]["status"] = "failed"', source)

    def test_reports_target_project_results(self):
        from benchmarks import qwen_opt_analyze, qwen_opt_trace_analyze
        from benchmarks import qwen_profile_report, qwen_report
        expected = ROOT / "results"
        self.assertEqual(qwen_opt_analyze.RESULTS, expected / "qwen_optimization")
        self.assertEqual(qwen_opt_trace_analyze.BASE, ROOT)
        self.assertEqual(qwen_profile_report.DIR, expected / "qwen_flash_next_v2")
        self.assertEqual(qwen_report.BASE, expected / "qwen_flash_next")

    def test_stable_volumes_and_local_assets(self):
        from qwen_core import storage
        from legacy import qwen_storage_v1
        from benchmarks.qwen_compiler_cache import COMPILER_VOLUME_NAME
        self.assertNotEqual(storage.MODEL_VOLUME_NAME, qwen_storage_v1.MODEL_VOLUME_NAME)
        self.assertEqual(COMPILER_VOLUME_NAME, "modal-forge-qwen38-compile-v2")
        self.assertTrue((ROOT / "benchmarks" / "qwen_pointer_chase.c").is_file())
        self.assertTrue((ROOT / "results" / "default_gpu" / "results_t4.json").is_file())
        self.assertTrue((ROOT / "results" / "default_gpu" / "results_l40s.json").is_file())


if __name__ == "__main__":
    unittest.main()
