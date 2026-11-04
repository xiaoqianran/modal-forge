"""Generate a complete, source-linked markdown audit from a real Qwen profile JSON."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DIR = HERE / "results" / "qwen_flash_next_v2"
GIB = 1024**3


def n(value, digits=2) -> str:
    if value is None:
        return "未测得"
    try:
        return f"{float(value):.{digits}f}"
    except (ValueError, TypeError):
        return "未测得"


def peak(samples, parent, key, scale=1):
    vals = []
    for s in samples:
        raw = s.get(parent, {}).get(key)
        try:
            vals.append(float(raw) / scale)
        except (ValueError, TypeError):
            pass
    return max(vals, default=None)


def report(record: dict, source: Path, app_id: str = "未指定") -> str:
    samples = record.get("samples") or []
    suite = record.get("profile_suite") or {}
    lines = [
        "# Qwen3.8-Flash-Next / RTX PRO 6000：真实推理剖析报告",
        "",
        f"生成时间（UTC）：{datetime.now(timezone.utc).isoformat()}",
        f"源 JSON：`{source}`",
        f"Modal App：`{app_id}`",
        f"原始日志压缩归档：`{record.get('raw_log_archive_path','未保存')}`",
        "",
        "## 实验条件与完成状态",
        "",
        f"- 模型：`{record.get('model')}`",
        f"- 镜像：`{record.get('image')}`",
        f"- HF Commit：`{record.get('model_cache',{}).get('revision','unknown')}`",
        f"- RAM 申请：{record.get('ram_gib')} GiB；CPU：{record.get('cpu_cores')}；GPU：1×RTX PRO 6000",
        f"- CPU PLE 后端：`{record.get('ple_backend')}`；HiCache：{record.get('hicache_gb_decimal')} GB；NIXL：`{record.get('nixl')}`",
        "- 引擎 MAX_RUNNING_REQUESTS=2，不为 4 客户端改变生产参数",
        f"- 整体成功：**{record.get('success')}**，profile_suite_ok：**{record.get('profile_suite_ok')}**",
        f"- 错误：`{record.get('error','无')}`",
        "",
        "## 冷启动与资源峰值",
        "",
        f"- 从函数执行至 API /v1/models 就绪：**{n(record.get('startup_s'))} s**",
        f"- GPU 函数总耗时（含测试）：**{n(record.get('elapsed_s'))} s**",
        f"- CPU RAM cgroup 最大实际峰值：**{n(peak(samples,'memory','peak_bytes',GIB))} GiB**",
        f"- 采样到的 CPU RAM 最大值：**{n(peak(samples,'memory','current_bytes',GIB))} GiB**",
        f"- GPU VRAM 最大采样：**{n(peak(samples,'gpu','used_mib',1024))} GiB**",
        f"- GPU 利用率最大采样：**{n(peak(samples,'gpu','utilization_pct'))}%**",
        f"- GPU 电功率峰值采样：**{n(peak(samples,'gpu','power_w'))} W**",
        "",
        "### 函数阶段计时标记",
        "",
        "| 阶段 | 从函数开始（秒） | 时间戳（UTC） |",
        "|---|---:|---|",
    ]
    for m in record.get("phase_marks") or []:
        lines.append(f"| {m.get('phase')} | {n(m.get('elapsed_s'),3)} | {m.get('timestamp_utc')} |")
    phase_data = record.get("log_phase_report") or {}
    lines += [
        "",
        "### Penny Royal 引擎原生事件",
        "",
        f"- 权重加载每段报告秒数：`{phase_data.get('reported_weight_load_segments_s')}`",
        f"- 片段求和（仅参考）：`{phase_data.get('reported_weight_load_sum_s')}` 秒",
        f"- 引擎原生阶段摘要：`{phase_data.get('engine_timing_raw','缺失')}`",
        "",
        "| 类别 | 命中日志行数 | 重要原文（首条） |",
        "|---|---:|---|",
    ]
    for key,value in (phase_data.get("patterns") or {}).items():
        first=(value.get('first_lines') or ['无'])[0]
        lines.append(f"| {key} | {value.get('total_matching_lines')} | `{first[:200].replace('|','/')}` |")
    lines += [
        "",
        "注意：mamba/PLE 命中日志只能说明引擎访问路径；本次没有直接测到每次 PLE 查表纳秒数。"
        "引擎官方摘要与用户态计时基准不同，存在嵌套阶段，不能相加。",
        "",
        "## 单请求：冷/短/中/长上下文",
        "",
        "| 请求 | 实际输入 Token | 实际输出 Token | TTFT s | TPOT ms | 解码 tokens/s | 总用时 s | 检查 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for i,smoke in enumerate(record.get("requests") or []):
        lines.append(
            f"| 原有预热#{i+1} | {smoke.get('input_tokens')} | {smoke.get('output_tokens')} "
            f"| {n(smoke.get('ttft_s'))} | — | {n(smoke.get('output_tok_s'))} "
            f"| {n(smoke.get('total_s'))} | 历史 smoke |"
        )
    for case in suite.get("case_results") or []:
        lines.append(
            f"| {case.get('case')} | {case.get('input_tokens','失败')} | "
            f"{case.get('output_tokens','失败')} | {n(case.get('ttft_s'))} "
            f"| {n(case.get('tpot_ms'))} | {n(case.get('decode_tok_s'))} "
            f"| {n(case.get('total_s'))} | {case.get('contains_391',case.get('error','未知'))} |"
        )
    lines += [
        "",
        "## 客户端并发与排队",
        "",
        "| 同时客户端 | 引擎运行上限 | 批次总耗时 s | 总吞吐 tok/s | 完成成功 | 答案检查 |",
        "|---|---:|---:|---:|---|---|",
    ]
    for batch in suite.get("batch_results") or []:
        lines.append(
            f"| {batch.get('clients')} | {batch.get('engine_max_running_requests')} "
            f"| {n(batch.get('batch_s'))} | {n(batch.get('aggregate_completion_tok_s'))} "
            f"| {batch.get('all_requests_succeeded')} | {batch.get('all_answer_checks')} |"
        )
    for batch in suite.get("batch_results") or []:
        lines += [
            "",
            f"### 并发 {batch.get('clients')} 客户端逐条",
            "",
            "| 请求 | 输入 Token | 输出 Token | TTFT s | TPOT ms | Decode tok/s | 总秒数 | 失败 |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for i,r in enumerate(batch.get('requests') or []):
            lines.append(
                f"| {i+1} | {r.get('input_tokens')} | {r.get('output_tokens')} "
                f"| {n(r.get('ttft_s'))} | {n(r.get('tpot_ms'))} "
                f"| {n(r.get('decode_tok_s'))} | {n(r.get('total_s'))} "
                f"| {r.get('error','无')} |"
            )
    lines += [
        "",
        "## 测试局限与下一步",
        "",
        "- 4 客户端会排队；此项是固定 MAX_RUNNING_REQUESTS=2 下的容量测试，不能推断真实 4 路同时计算性能。",
        "- TTFT 从可见 SSE 内容事件开始；若模型先输出思考内容，也计为首次内容；TPOT 为可见首事件到 SSE 完成的平均耗时。",
        "- 前缀缓存/内核缓存可能影响后续请求；中长提示词使用不同前缀，但仍不能保证底层缓存完全冷却。",
        "- 记录的是真实引擎日志和 cgroup 指标，没有补充虚构的 CPU PLE 专用 profiler 时间。",
        f"- 跳过项：`{suite.get('skipped',[])}`",
        "- 实际 Modal 账单应单独通过 billing report 查证，估算费用不是硬性预算上限。",
    ]
    return "\n".join(lines)+"\n"


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--app-id",default="not-recorded")
    args=parser.parse_args()
    candidates=[]
    for path in DIR.glob("infer_80g_*.json"):
        try:
            d=json.loads(path.read_text("utf-8"))
        except (ValueError,OSError):
            continue
        if d.get("workload")=="profile":
            candidates.append((path,d))
    if not candidates:
        raise SystemExit("No profile workload JSON in "+str(DIR))
    path,datum=max(candidates,key=lambda x:x[0].stat().st_mtime)
    out=DIR/("PROFILE_REPORT_"+path.stem+".md")
    out.write_text(report(datum,path,args.app_id),encoding="utf-8")
    print("PROFILE_REPORT_FILE="+str(out))


if __name__=="__main__":
    main()
