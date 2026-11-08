# Qwen3.8-Flash-Next / RTX PRO 6000：真实推理剖析报告

生成时间（UTC）：2026-11-04T07:35:27.274088+00:00
源 JSON：`D:\a_programming_list\Ai-application\A-modal\modal-forge\005-Default-GPU-Memory\results\qwen_flash_next_v2\infer_80g_20261104T073426Z.json`
Modal App：`ap-pZT5OHNvbDiacMnR5S1kQ8`
原始日志压缩归档：`D:\a_programming_list\Ai-application\A-modal\modal-forge\005-Default-GPU-Memory\results\qwen_flash_next_v2\infer_80g_20261104T073426Z.log.gz`

## 实验条件与完成状态

- 模型：`RadixArk/Qwen3.8-Flash-Next-NVFP4`
- 镜像：`ghcr.io/jpezzulli/sglang-rtxpro6000:v3.1.5`
- HF Commit：`7b719225242aacd3dbd3f9407468c2ee9a9d2594`
- RAM 申请：80 GiB；CPU：4；GPU：1×RTX PRO 6000
- CPU PLE 后端：`ram`；HiCache：8 GB；NIXL：`off`
- 引擎 MAX_RUNNING_REQUESTS=2，不为 4 客户端改变生产参数
- 整体成功：**True**，profile_suite_ok：**True**
- 错误：`无`

## 冷启动与资源峰值

- 从函数执行至 API /v1/models 就绪：**312.66 s**
- GPU 函数总耗时（含测试）：**354.54 s**
- CPU RAM cgroup 最大实际峰值：**未测得 GiB**
- 采样到的 CPU RAM 最大值：**107.74 GiB**
- GPU VRAM 最大采样：**80.88 GiB**
- GPU 利用率最大采样：**100.00%**
- GPU 电功率峰值采样：**486.17 W**

### 函数阶段计时标记

| 阶段 | 从函数开始（秒） | 时间戳（UTC） |
|---|---:|---|
| hardware_recorded | 0.411 | 2026-11-04T07:28:32.728644+00:00 |
| volume_manifest_checked | 2.356 | 2026-11-04T07:28:34.673923+00:00 |
| pennyroyal_process_start | 2.357 | 2026-11-04T07:28:34.674924+00:00 |
| api_models_ready | 312.661 | 2026-11-04T07:33:44.978702+00:00 |
| smoke_warmup | 312.661 | 2026-11-04T07:33:44.978715+00:00 |
| profile_suite_start | 331.852 | 2026-11-04T07:34:04.169781+00:00 |
| single_short | 331.852 | 2026-11-04T07:34:04.170056+00:00 |
| single_medium | 333.040 | 2026-11-04T07:34:05.357492+00:00 |
| single_long | 341.047 | 2026-11-04T07:34:13.365043+00:00 |
| concurrency_1 | 344.128 | 2026-11-04T07:34:16.445976+00:00 |
| concurrency_2 | 345.001 | 2026-11-04T07:34:17.318252+00:00 |
| concurrency_4 | 346.277 | 2026-11-04T07:34:18.594269+00:00 |
| suite_complete | 348.854 | 2026-11-04T07:34:21.171752+00:00 |
| shutdown_begin | 348.854 | 2026-11-04T07:34:21.171832+00:00 |

### Penny Royal 引擎原生事件

- 权重加载每段报告秒数：`[104.12, 12.86]`
- 片段求和（仅参考）：`116.98` 秒
- 引擎原生阶段摘要：`[2026-11-04 07:33:26] Engine startup timings (s): load_weight=116.98, kv_cache_allocation=2.35, scheduler_e2e=216.08, cuda_graph={prefill=0.00, decode=0.00, target_verify=9.65, draft_prefill=0.00, draft_decode=9.55, draft_extend=3.50}, tokenizer_e2e=237.03`

| 类别 | 命中日志行数 | 重要原文（首条） |
|---|---:|---|
| weight_begin | 2 | `[2026-11-04 07:29:54] Load weight begin. avail mem=94.18 GB` |
| weight_end | 2 | `[2026-11-04 07:31:38] Load weight end. elapsed=104.12 s, type=Qwen4ExpForConditionalGeneration, quant=modelopt_fp4, quant_algo=NVFP4, avail mem=23.20 GB, mem usage=70.97 GB.` |
| engine_timings | 1 | `[2026-11-04 07:33:26] Engine startup timings (s): load_weight=116.98, kv_cache_allocation=2.35, scheduler_e2e=216.08, cuda_graph={prefill=0.00, decode=0.00, target_verify=9.65, draft_prefill=0.00, dra` |
| cuda_graph | 10 | `[2026-11-04 07:32:49] Capture target verify CUDA graph begin. backend=full, num_tokens_per_req=8, bs=[1], avail mem=18.60 GB` |
| warmup | 3 | `[2026-11-04 07:33:26] Running warmup structured_output` |
| api_ready | 3 | `[2026-11-04 07:33:43] INFO:     Application startup complete.` |
| ple_backend | 15 | `  PLE: host RAM / HiCache: true / Host tier: 8 GB` |
| compilation | 13 | `[2026-11-04 07:31:55] Running FlashInfer autotune with cache: /tmp/penny-cache/sglang/flashinfer/autotune/0.7.0.post1/sm120/9e402277b2a65968/rank_tp0_pp0_dp0.json` |

注意：mamba/PLE 命中日志只能说明引擎访问路径；本次没有直接测到每次 PLE 查表纳秒数。引擎官方摘要与用户态计时基准不同，存在嵌套阶段，不能相加。

## 单请求：冷/短/中/长上下文

| 请求 | 实际输入 Token | 实际输出 Token | TTFT s | TPOT ms | 解码 tokens/s | 总用时 s | 检查 |
|---|---:|---:|---:|---:|---:|---:|---|
| 原有预热#1 | 17 | 24 | 18.51 | — | 66.85 | 18.85 | 历史 smoke |
| 原有预热#2 | 20 | 74 | 0.11 | — | 316.49 | 0.34 | 历史 smoke |
| short | 46 | 211 | 0.37 | 3.89 | 257.21 | 1.19 | True |
| medium | 8103 | 139 | 7.56 | 3.25 | 307.28 | 8.01 | True |
| long | 32253 | 137 | 2.68 | 2.98 | 335.84 | 3.08 | True |

## 客户端并发与排队

| 同时客户端 | 引擎运行上限 | 批次总耗时 s | 总吞吐 tok/s | 完成成功 | 答案检查 |
|---|---:|---:|---:|---|---|
| 1 | 2 | 0.87 | 293.50 | True | True |
| 2 | 2 | 1.28 | 397.35 | True | True |
| 4 | 2 | 2.58 | 397.29 | True | True |

### 并发 1 客户端逐条

| 请求 | 输入 Token | 输出 Token | TTFT s | TPOT ms | Decode tok/s | 总秒数 | 失败 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 59 | 256 | 0.10 | 3.02 | 330.67 | 0.87 | 无 |

### 并发 2 客户端逐条

| 请求 | 输入 Token | 输出 Token | TTFT s | TPOT ms | Decode tok/s | 总秒数 | 失败 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 59 | 256 | 0.19 | 4.26 | 234.64 | 1.28 | 无 |
| 2 | 59 | 251 | 0.19 | 4.14 | 241.77 | 1.23 | 无 |

### 并发 4 客户端逐条

| 请求 | 输入 Token | 输出 Token | TTFT s | TPOT ms | Decode tok/s | 总秒数 | 失败 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 59 | 256 | 0.19 | 4.13 | 242.24 | 1.24 | 无 |
| 2 | 59 | 256 | 0.19 | 4.67 | 214.14 | 1.38 | 无 |
| 3 | 59 | 256 | 1.33 | 4.79 | 208.63 | 2.56 | 无 |
| 4 | 59 | 256 | 1.48 | 4.30 | 232.61 | 2.57 | 无 |

## 测试局限与下一步

- 4 客户端会排队；此项是固定 MAX_RUNNING_REQUESTS=2 下的容量测试，不能推断真实 4 路同时计算性能。
- TTFT 从可见 SSE 内容事件开始；若模型先输出思考内容，也计为首次内容；TPOT 为可见首事件到 SSE 完成的平均耗时。
- 前缀缓存/内核缓存可能影响后续请求；中长提示词使用不同前缀，但仍不能保证底层缓存完全冷却。
- 记录的是真实引擎日志和 cgroup 指标，没有补充虚构的 CPU PLE 专用 profiler 时间。
- 跳过项：`[]`
- 实际 Modal 账单应单独通过 billing report 查证，估算费用不是硬性预算上限。
