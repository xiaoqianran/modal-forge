"""Postprocess Qwen cache/C4/PLE experiments without touching GPU or Modal.

Reads existing result.json files and produces a raw summary plus one Markdown
table; no cross-run claim is made without repeated controlled measurements.
"""
from __future__ import annotations
import gzip
import json
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent.parent
RESULTS=ROOT/"results"/"qwen_optimization"
HISTORIC=ROOT/"results"/"qwen_flash_next_v2"/"infer_80g_20261104T073426Z.json"


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return {}


def summary(path:Path) -> dict:
    x=_read(path)
    s=x.get("profile_suite") or {}
    cache=x.get("compiler_cache") or {}
    comp=x.get("compiler_event_counts") or {}
    warm={i.get("shape"):i for i in x.get("shape_warmups") or []}
    cases={i.get("case"):i for i in s.get("case_results") or []}
    batches={i.get("clients"):i for i in s.get("batch_results") or []}
    billing=_read(path.parent/"billing.json")
    result={
        "dir":str(path.parent),"run":x.get("opt_run","historic"),
        "success":x.get("success"),"error":x.get("error"),
        "cpu":x.get("cpu_cores"),"ram_request_gib":x.get("ram_gib"),
        "startup_s":x.get("startup_s"),"traffic_ready_s":x.get("traffic_ready_s"),
        "first_useful_answer_s":x.get("first_useful_answer_s"),
        "total_s":x.get("elapsed_s"),
        "weight_s":(x.get("log_phase_report") or {}).get("reported_weight_load_sum_s"),
        "tilelang_compilations":comp.get("tilelang_begin"),
        "engine_running_max_observed":x.get("engine_running_max_observed"),
        "cache_fingerprint":cache.get("fingerprint"),
        "cache_restore_s":(cache.get("restore") or {}).get("restore_s"),
        "cache_publish_s":(cache.get("publication") or {}).get("publish_s"),
        "cache_files":(cache.get("publication") or {}).get("file_count"),
        "cache_archive_bytes":(cache.get("publication") or {}).get("archive_bytes"),
        "warmup_8k":_select(warm.get("warmup")),
        "warmup_32k":_select(warm.get("wlongXX")),
        "formal_8k":_select(cases.get("medium")),
        "formal_32k":_select(cases.get("long")),
        "throughput_2":(batches.get(2) or {}).get("aggregate_completion_tok_s"),
        "throughput_4":(batches.get(4) or {}).get("aggregate_completion_tok_s"),
        "c4_batch_s":(batches.get(4) or {}).get("batch_s"),
        "all_requests_succeeded":all(b.get("all_requests_succeeded") for b in batches.values()),
        "profile_status":(x.get("ple_profile") or {}).get("status"),
        "profile_trace_volume":(x.get("ple_profile") or {}).get("trace_volume_path"),
        "actual_billed_usd":billing.get("total_usd"),
    }
    return result


def _select(d):
    if d is None:
        return None
    return {k:d.get(k) for k in ("input_tokens","output_tokens","ttft_s",
                                  "total_s","tpot_ms","decode_tok_s")}


def fm(x,nd=2):
    return f"{x:.{nd}f}" if isinstance(x,(float,int)) else "—"


def report(rows):
    r0=next((x for x in rows if x["run"]=="historic"),None)
    def metric_row(name, field,fmt=lambda x:fm(x)):
        return "| "+name+" | "+" | ".join(fmt(r.get(field)) if r else "—" for r in rows)+" |"
    header=["历史基线","R1 写缓存","R2 读缓存","R3 C4"]
    order=[next((r for r in rows if r["run"]==label),None)
           for label in ("historic","r1","r2","r3")]
    lines=[
        "# Qwen3.8-Flash-Next 编译缓存 / 真实并发 / PLE 实测对照",
        "",f"生成 UTC：{datetime.now(timezone.utc).isoformat()}",
        "",
        "**提醒：** 单次不同容器不是严格的同宿主 A/B。启动时间与权重加载"
        "受 Volume 缓存、CPU 平台和内核缓存影响。任何对比都需要结合 JIT 命中证据，"
        "不能把所有改进归功于缓存。",
        "",
        "| 指标 | "+" | ".join(header)+" |",
        "|---|---:|---:|---:|---:|",
    ]
    for label,field in [
        ("API ready / s","startup_s"),("Traffic ready / s","traffic_ready_s"),
        ("First useful answer / s","first_useful_answer_s"),("weight load / s","weight_s"),
        ("TileLang compile 次数","tilelang_compilations"),
        ("8K 目标预热 TTFT / s","warmup_8k"),("8K 正式 TTFT / s","formal_8k"),
        ("32K 正式 TTFT / s","formal_32k"),
        ("C2 聚合 tok/s","throughput_2"),("C4 客户端聚合 tok/s","throughput_4"),
        ("引擎实际运行并发上限","engine_running_max_observed"),
        ("缓存恢复 / s","cache_restore_s"),("缓存发布 / s","cache_publish_s"),
        ("Modal 实际账单 / USD","actual_billed_usd"),
    ]:
        if field in ("warmup_8k","formal_8k","formal_32k"):
            lines.append(metric_row(label,field,lambda v:fm((v or {}).get("ttft_s"))))
        else:
            lines.append(metric_row(label,field))
    lines += ["","## 本轮重要证据",""]
    for x in rows:
        lines.append(
            f"- **{x['run']}**: success={x['success']}, "
            f"JIT={x['tilelang_compilations']}, cache={x['cache_fingerprint']}, "
            f"PLE profile={x.get('profile_status')}, raw={x['dir']}"
        )
    lines += [
        "",
        "## 如何判定",
        "",
        "- 编译缓存跨容器复用必须同时满足 R2 SHA 校验恢复成功、"
        "真实 TileLang compile 行数下降，才可以说缓存复用成功。",
        "- 对端到端性能应比较 API Ready、Traffic Ready、首次正式请求总完成，"
        "而不只是正式 8K TTFT（预热可能只是提前花费时间）。",
        "- 只有 SGLang 日志确认 #running-req >=4，才能认定 R3 真正四路同时运行。",
        "- profiler trace 若生成，仅用于定位 PLE gather 核心路径；"
        "Profiler 模式吞吐不与普通请求直接比较。",
    ]
    return "\n".join(lines)+"\n"


def main():
    rows=[]
    if HISTORIC.is_file():
        rows.append(summary(HISTORIC))
    for name in ("r1","r2","r3"):
        paths=sorted(RESULTS.glob(name+"_*/result.json"),key=lambda p:p.stat().st_mtime)
        if paths:
            rows.append(summary(paths[-1]))
    RESULTS.mkdir(parents=True,exist_ok=True)
    out=RESULTS/"optimization_comparison.json"
    out.write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding="utf-8")
    reportpath=ROOT/"docs"/"inference"/"QWEN_OPTIMIZATION_RESULTS_20261104.md"
    reportpath.write_text(report(rows),encoding="utf-8")
    print("COMPARISON_JSON="+str(out))
    print("COMPARISON_REPORT="+str(reportpath))
    for x in rows:
        print(json.dumps({k:v for k,v in x.items() if k in (
            "run","success","startup_s","first_useful_answer_s",
            "tilelang_compilations","actual_billed_usd","profile_status",
        )},ensure_ascii=False))


if __name__=="__main__":
    main()
