"""Qwen profile offline tests, no Modal or model import."""
from __future__ import annotations
import unittest
import time
from qwen_core.profile import build_context, parse_startup_log, run_suite


def fake_stream(model, prompt, max_tokens, timeout):
    return {
        "input_tokens": len(prompt) // 4, "output_tokens": 50,
        "decode_tok_s": 300.0, "tpot_ms": 3.33, "ttft_s": 0.12,
        "contains_391": True, "total_s": 0.22,
    }


class ProfileTests(unittest.TestCase):
    def test_prompt_case_isolation(self):
        self.assertNotEqual(build_context("long",3), build_context("medium",3))
        self.assertIn("391", build_context("long",2))

    def test_suite_schedules_expected_bounded_workloads(self):
        phases = []
        result = run_suite(
            "qwen", time.monotonic() + 700, stream_fn=fake_stream,
            phase_hook=phases.append,
        )
        self.assertEqual([x["case"] for x in result["case_results"]],
                         ["short","medium","long"])
        self.assertEqual([x["clients"] for x in result["batch_results"]],[1,2,4])
        self.assertTrue(all(x["all_requests_succeeded"] for x in result["batch_results"]))
        self.assertEqual(len(result["batch_results"][2]["requests"]),4)
        self.assertIn("suite_complete",phases)

    def test_suite_respects_budget(self):
        result=run_suite("qwen",time.monotonic()+1,stream_fn=fake_stream)
        self.assertEqual(len(result["skipped"]),6)
        self.assertEqual(len(result["case_results"]),0)

    def test_log_extracts_weight_and_ple_evidence(self):
        sample = """[2026-11-04 06:01:00] Load weight begin.
[2026-11-04 06:01:30] Load weight end. elapsed=30.0 s, type=Qwen
[2026-11-04 06:01:31] Engine startup timings (s): load_weight=30.0
[2026-11-04 06:01:32] mamba match rid=abc mamba_host=0
[2026-11-04 06:01:33] Warmup ended
"""
        report = parse_startup_log(sample)
        self.assertEqual(report["reported_weight_load_sum_s"],30.0)
        self.assertEqual(report["patterns"]["ple_backend"]["total_matching_lines"],1)
        self.assertIn("load_weight=30.0",report["engine_timing_raw"])

if __name__=="__main__":
    unittest.main()
