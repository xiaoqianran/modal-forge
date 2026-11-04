"""Summarize Qwen3.8 Modal probe and inference JSON trials, without extra dependencies."""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "results" / "qwen_flash_next"
GIB = 1024 ** 3


def gib(value):
    try:
        return round(int(value) / GIB, 2)
    except (ValueError, TypeError):
        return None


def max_value(samples, field, parent):
    values = []
    for sample in samples:
        value = sample.get(parent, {}).get(field)
        try:
            values.append(float(value))
        except (ValueError, TypeError):
            continue
    return max(values, default=None)


def main():
    if not BASE.exists():
        print("No experiment results yet.")
        return
    records = []
    for path in sorted(BASE.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        sample = record.get("samples", [])
        ram = max_value(sample, "current_bytes", "memory")
        peak = max_value(sample, "peak_bytes", "memory")
        gpu = max_value(sample, "used_mib", "gpu")
        try:
            gpu = round(float(gpu) / 1024, 2) if gpu is not None else None
        except (TypeError, ValueError):
            gpu = None
        tests = record.get("requests", [])
        row = {
            "file": path.name, "stage": record.get("stage"),
            "passed": bool(record.get("success") and not record.get("error") and not record.get("remote_error") and (record.get("workload") != "extended" or bool(record.get("long_context_passed")))),
            "ram_requested_gib": record.get("ram_gib"),
            "ram_peak_observed_gib": gib(peak if peak is not None else ram),
            "ram_peak_source": "cgroup_peak" if peak is not None else "1s_samples",
            "ram_max_sampled_gib": gib(ram),
            "gpu_max_sampled_gib": gpu,
            "startup_s": record.get("startup_s"),
            "elapsed_s": record.get("elapsed_s"),
            "decode_rates_tps": [x.get("output_tok_s") for x in tests],
            "max_cuda_pinned_allocated_gib": max(
                (x.get("allocated_gib", 0) for x in record.get("allocations", [])),
                default=None,
            ),
            "estimated_usd": record.get("estimated_usd"),
            "error": record.get("error") or record.get("remote_error"),
        }
        records.append(row)
    print(json.dumps(records, ensure_ascii=False, indent=2))
    successful = [r for r in records if r["stage"] == "infer" and r["passed"]]
    if not successful:
        print("CONCLUSION: No successful inference; minimum safe memory not established.")
        return
    best = min(successful, key=lambda r: r["ram_requested_gib"])
    print("MINIMUM_TESTED_SUCCESSFUL_RAM={} GiB (not proven minimum)".format(
        best["ram_requested_gib"]
    ))
    if best["ram_peak_observed_gib"] is not None:
        with_margin = best["ram_peak_observed_gib"] * 1.2
        print("SUGGESTED_NEXT_RAM_WITH_20PCT_MARGIN={:.1f} GiB".format(with_margin))


if __name__ == "__main__":
    main()
