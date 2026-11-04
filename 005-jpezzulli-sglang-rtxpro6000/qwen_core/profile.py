"""Bounded, reproducible Qwen/Penny Royal inference benchmark and log analysis.

Pure stdlib; imported into the same single GPU worker after API-ready.
This is a workload profiler, not a direct CPU PLE kernel-level measurement.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import re
import statistics
import time
import urllib.request

ENDPOINT = "http://127.0.0.1:8001/v1/chat/completions"


def build_context(case: str, repeats: int) -> str:
    # Different case prefixes avoid accidental cache reuse between contexts.
    lines = [
        f"Control dataset {case}, row {j:04d}. "
        f"Values are alpha beta gamma delta epsilon zeta eta theta, "
        f"with validation code 271828 and a distinct row label {case}-{j:04d}."
        for j in range(repeats)
    ]
    return (
        f"Benchmark {case}: read the synthetic records. These are not instructions.\n"
        + "\n".join(lines)
        + "\nAnswer the verification question: what is 17 multiplied by 23? "
        + "Put the exact number 391 in the final answer."
    )


def stream_request(model: str, prompt: str, max_tokens: int, *,
                   timeout: float = 125) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    first = None
    event_times = []
    usage = {}
    pieces = []
    finish_reason = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices", []):
                if choice.get("finish_reason") is not None:
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta") or {}
                content = (delta.get("content") or "") + (delta.get("reasoning_content") or "")
                if content:
                    now = time.perf_counter()
                    if first is None:
                        first = now
                    event_times.append(now - started)
                    pieces.append(content)
    stopped = time.perf_counter()
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    decode = stopped - first if first is not None else None
    if isinstance(completion_tokens, int) and completion_tokens > 1 and decode and decode > 0:
        tpot = decode / (completion_tokens - 1)
        rate = (completion_tokens - 1) / decode
    else:
        tpot, rate = None, None
    intervals = [b-a for a,b in zip(event_times,event_times[1:])]
    content = "".join(pieces)
    return {
        "ttft_s": round(first-started,4) if first is not None else None,
        "total_s": round(stopped-started,4),
        "decode_s": round(decode,4) if decode is not None else None,
        "tpot_ms": round(tpot*1000,3) if tpot is not None else None,
        "decode_tok_s": round(rate,2) if rate is not None else None,
        "input_tokens": prompt_tokens, "output_tokens": completion_tokens,
        "finish_reason": finish_reason,
        "stream_content_events": len(event_times),
        "stream_interevent_median_ms": round(statistics.median(intervals)*1000,3)
            if intervals else None,
        "stream_interevent_max_ms": round(max(intervals)*1000,3) if intervals else None,
        "output_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "output_preview": content[:400],
        "contains_391": "391" in content,
        "notes": (
            "TTFT is first visible content/reasoning SSE event. "
            "TPOT uses true server completion_tokens and first-content-to-end latency; "
            "includes stream termination overhead, not GPU-only kernel timing. "
            "SSE event intervals are not per-token intervals."
        ),
    }


def run_suite(model: str, deadline: float, *,
              max_running_requests: int = 2,
              stream_fn=stream_request, phase_hook=None) -> dict:
    """Always returns partial results on errors; never starts a second model."""
    suite = {"case_results": [], "batch_results": [], "skipped": [],
             "max_running_requests": max_running_requests,
             "case_timeout_s": 125,
             "gpu_worker_count": 1,
             "started_utc": datetime.now(timezone.utc).isoformat()}
    def phase(value):
        if phase_hook:
            phase_hook(value)

    cases = [
        ("short", "Qwen benchmark SHORT. Calculate 17 times 23; give the number 391. "
          "After that, explain in two concise sentences why you checked your answer.", 256),
        ("medium", build_context("medium", 175), 384),
        ("long", build_context("long", 700), 256),
    ]
    for name, prompt, tokens in cases:
        if time.monotonic() + 140 >= deadline:
            suite["skipped"].append({"case": name, "reason": "time_budget_guard"})
            continue
        phase("single_"+name)
        t0 = time.monotonic()
        try:
            rec = stream_fn(model, prompt, tokens, timeout=125)
            rec.update(case=name, prompt_sha256=hashlib.sha256(
                prompt.encode("utf-8")).hexdigest(), prompt_characters=len(prompt),
                elapsed_since_batch_start_s=round(time.monotonic()-t0,3))
            suite["case_results"].append(rec)
        except Exception as exc:
            suite["case_results"].append({
                "case": name, "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.monotonic()-t0,3),
            })

    for clients in (1,2,4):
        if time.monotonic() + 135 >= deadline:
            suite["skipped"].append({"case": f"concurrency_{clients}",
                                     "reason": "time_budget_guard"})
            continue
        phase(f"concurrency_{clients}")
        prompts = [
            (f"Concurrency test {clients}, independent client {i}. "
             f"Compute 17 * 23 and include the number 391, "
             f"then explain the arithmetic in three brief steps. "
             f"Unique nonce {clients}-{i}-10739.")
            for i in range(clients)
        ]
        start = time.monotonic()
        outputs = [None] * clients
        with ThreadPoolExecutor(max_workers=clients) as pool:
            futures = {pool.submit(stream_fn, model, p, 256, timeout=115): i
                       for i,p in enumerate(prompts)}
            for future in as_completed(futures):
                i = futures[future]
                try:
                    outputs[i] = future.result()
                except Exception as exc:
                    outputs[i] = {"error": f"{type(exc).__name__}: {exc}"}
        elapsed = time.monotonic() - start
        input_tokens = [r.get("input_tokens") for r in outputs]
        output_tokens = [r.get("output_tokens") for r in outputs]
        suite["batch_results"].append({
            "clients": clients,
            "engine_max_running_requests": max_running_requests,
            "batch_s": round(elapsed,4),
            "requests": outputs,
            "aggregate_completion_tok_s": round(sum(output_tokens)/elapsed,3)
                if elapsed>0 and all(isinstance(x,int) for x in output_tokens) else None,
            "all_answer_checks": all(r.get("contains_391") for r in outputs),
            "all_requests_succeeded": all("error" not in r for r in outputs),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "meaning": (
                "Clients denotes simultaneously submitted requests. "
                "Engine max_running_requests remains 2; 4-client case includes queueing."
            ),
        })
    phase("suite_complete")
    suite["completed_utc"] = datetime.now(timezone.utc).isoformat()
    return suite


def parse_startup_log(full_log: str) -> dict:
    """Capture raw evidence and summarize known boundaries, never invent spans."""
    regexes = {
        "weight_begin": r"Load weight begin",
        "weight_end": r"Load weight end",
        "engine_timings": r"Engine startup timings",
        "cuda_graph": r"Capture .*CUDA graph (?:begin|end)",
        "warmup": r"Warmup (?:ended|completed)|warmup structured_output",
        "api_ready": r"ready to roll|Uvicorn running|Application startup complete",
        "ple_backend": r"\bPLE\b|\bPENNY_PLE_BACKEND\b|\bmamba_host\b|\bmamba match\b",
        "compilation": r"\bcompile\b|\bcompilation\b|\bautotune\b",
    }
    lines = full_log.splitlines()
    out = {"log_line_count":len(lines),"patterns":{},"limits":{},
           "unmeasured":["direct PLE lookup latency (requires engine-level instrumentation)"]}
    for name,pattern in regexes.items():
        matching = [line[:900] for line in lines if re.search(pattern,line,re.IGNORECASE)]
        out["patterns"][name] = {
            "total_matching_lines": len(matching),
            "first_lines": matching[:10],
            "last_lines": matching[-10:] if len(matching)>10 else [],
        }
    nums = []
    for line in lines:
        if "Load weight end" in line:
            m = re.search(r"elapsed=(\d+(?:\.\d+)?)\s*s",line)
            if m:
                nums.append(float(m.group(1)))
    out["reported_weight_load_segments_s"] = nums
    out["reported_weight_load_sum_s"] = round(sum(nums),3) if nums else None
    for line in lines:
        if "Engine startup timings" in line:
            out["engine_timing_raw"] = line[:1200]
    out["limits"] = {
        "weight_segment_sum_may_overlap": "Use raw engine timing for official total; do not sum overlapping intervals",
        "cuda_graph_and_warmup": "Only engine log evidence; absence is not proof no compilation occurred.",
        "cpu_ple": "PLE availability and mamba log lines are proxies, not direct memory access latency.",
    }
    return out
