# Qwen3.8 Flash-Next / 单卡 RTX PRO 6000：三项优化实施设计

> 原始设计日期：2026-11-04。**R1、R2、R3 已于当日执行完成**；本文保留实施前方案，最终数据以 [实测结论](QWEN_OPTIMIZATION_JIT_C4_PLE_FINAL_20261104.md) 为准。
>
> 只讨论 ① 首次请求 TileLang JIT/编译缓存，② 实际 4 路运行并发，③ PLE RAM 表的真实 GPU 访问；不优化其他模型，不下载权重，不修改生产推理代码，不进行付费测试。

## 0. 已有、可信的基线

- 模型：`RadixArk/Qwen3.8-Flash-Next-NVFP4`；HF SHA `7b719225242aacd3dbd3f9407468c2ee9a9d2594`；Penny Royal `ghcr.io/jpezzulli/sglang-rtxpro6000:v3.1.5`。
- GPU 1× RTX PRO 6000；4 CPU；RAM 80 GiB 申请，实测 1 秒内存采样最大 107.739 GiB；HiCache 8 GB；PLE 在 RAM；NIXL=off。
- 2026-11-04 运行 `ap-pZT5OHNvbDiacMnR5S1kQ8`：API 就绪 312.66s；load_weight=116.98s；GPU VRAM 最大采样 80.884GiB；Modal 已查出消费 $0.35597242。
- 8,103 输入 Token 的 TTFT 7.5582s，SGLang initial_prefill_elapsed=7499.54ms；期间有约 5s TileLang JIT；随后 32,253 输入 Token TTFT 2.6756s，initial_prefill_elapsed=2130.51ms。两者 cached_input_len=0；区别可能还含调度器、后续 shape 复用和其他缓存，**不能把全部 5s 差异归结为 TileLang**。
- 引擎 `MAX_RUNNING_REQUESTS=2`、`MAX_MAMBA_CACHE_SIZE=12`；1/2/4 个提交客户端输出聚合约 293.50/397.35/397.29 tokens/s；4 个客户端中后两条 TTFT 约 1.33/1.48s，后两条后端 queue_duration >1.1s。证明当前 C4 会排队，但**不证明 GPU 真正 C4 的吞吐上限**。
- 原始结果 `../../results/qwen_flash_next_v2/infer_80g_20261104T073426Z.json`，完整日志 `../../results/qwen_flash_next_v2/infer_80g_20261104T073426Z.log.gz`；当前分析：`QWEN_REAL_INFERENCE_PROFILE_20261104.md`。

## 1. 统一实验控制与计量

**保持不变：** 模型 revision、Penny Royal image digest/代码 commit、TP1、RTX PRO 6000、4 CPU、80 GiB RAM 请求、HiCache=8、MTP policy=tiered、NIXL=off、`MAX_TOTAL_TOKENS=131072`、同样的分词与采样选项、同一批输入。

**必须记录：** GPU/CPU/NUMA、环境变量和有效 ServerArgs、Penny Royal/Git/CUDA/Torch/TileLang/Triton/FlashInfer 版本、Volume v2 数据集 manifest、编译缓存 manifest、每次请求真正的 prompt/output tokens、TTFT/TPOT/P50/P95（样本少时不宣称稳定 P95）、每批输出 tokens/端到端秒、队列时间、`#running-req`、MTP accept len/rate、RAM/VRAM/cgroup、完整 Penny Royal 日志、真实 Modal Billing。

**主观测指标**：

- `T_api_ready`：Modal Function 进入时刻 → 模型 /v1/models 返回。
- `T_traffic_ready`：Function 进入 → 必要预热请求完全结束，能够接正式流量。
- `T_first_useful_answer`：Function 进入 → 预热结束后首条正式请求完成；优化 JIT 时最重要的端到端口径。
- `T_first_8k_ttft`：经过预热后首条非同一文本 8K 请求从提交至首个 SSE 内容片段的时间；必须把服务端 compilation events 对齐。
- `T_run_decode`：稳态输出 tokens 除以从首个内容片段到末尾的秒数；同时记录服务端的真实 post-prefill 时间。
- `T_batch_complete`：全部并发任务的最后一个请求完成时间 - 同步提交时间；吞吐 = 全部真实 completion tokens / T_batch_complete。
- `T_ple_critical_path`：GPU 计算实际等待 PLE gather 的时间；不是把所有 kernel 耗时相加，也不是 CPU-only 随机指针追逐。

连续计时使用 monotonic/perf_counter；日志时间戳辅助对齐但不同进程时钟不能盲目相减。每个实验 ID 和结果文件唯一，拒绝覆盖旧实验。失败项留错误/空值，不填 0。

## 2. 优化一：首次请求 TileLang/JIT 与缓存

### 2.1 代码证据

Penny Royal 启动脚本默认把 `TILELANG_CACHE_DIR` 定位在 `$CACHE_BASE/tilelang`，还将 `TRITON_CACHE_DIR`、`TORCHINDUCTOR_CACHE_DIR`、`CUDA_CACHE_PATH`、`FLASHINFER_WORKSPACE_BASE`、`SGLANG_JIT_CACHE_DIR` 放在相同根目录。我们的 `qwen_modal_v2.py` 给 `CACHE_BASE=/tmp/penny-cache`，容器销毁后无法期待其磁盘缓存持续存在。

参照：
- https://github.com/jpezzulli/sglang-rtxpro6000/blob/pennyroyal-main-sm120-final/configs/pennyroyal/serve-flash-next-frspec.sh
- https://github.com/tile-ai/tilelang/blob/main/tilelang/env.py
- https://modal.com/docs/sdk/py/latest/Volume

**实现顺序：**

1. **离线检查**：明确当前 v3.1.5 镜像的实际 `CACHE_BASE` / `TILELANG_CACHE_DIR`、编译器及驱动版本；审计 Python 代码和脚本覆盖顺序。**不能假定公开 main branch 一定与 v3.1.5 镜像完全相同。**
2. **单实例预热验证**：在 API ready 后，提交一个与正式测试同 token shape 但不同文本内容的 8K 输入（最小输出量），可选 32K；记录预热自身耗时、JIT 行数与第一次正式 8K 请求。已有 `--warmups=structured_output` 不足以覆盖该 shape，不能将同一前缀重复输入冒充 JIT 复用。
3. **持久化编译缓存**：单独创建名为 `modal-forge-qwen38-compile-v2` 的新 Volume v2（实际创建前检查名称冲突），只存编译产物/manifest，**不写已有两个模型 Volume**。
4. **本地 staging**：运行时仍用 `/tmp/penny-cache` 作为 `CACHE_BASE`。进程启动前从单独 Volume 恢复编译产物到同一固定绝对路径；模型启动、JIT、CUDA graph 均在本地临时文件系统运行。
5. **完成后发布**：在服务子进程结束且无编译写入后，按用途复制/打包 compiler cache，校验内容和完整 manifest，原子发布到编译 Volume，再 `commit()`。首期只允许单写者；失败不发布成功标记。先测单次产物体积/小文件数量，决定 tar/未压缩归档，以免 CPU 压缩开销反噬。
6. **指纹失配即隔离**：至少包含 image digest、PennyRoyal commit、Torch/TileLang/Triton/FlashInfer 版本、CUDA target `sm120`、影响二进制的环境参数，以及模型/形状选项。不要跨不兼容版本共享 `.so` 或 cubin。模型权重文件不存入编译缓存。

**A/B**：
- A 历史原配置：提供参照，但非同时/同主机严格对照。
- B 相同 C2 配置、空独立编译缓存、加入目标 8K/32K 预热，并保存产生的缓存。
- C 相同 C2 配置、**重启新 Modal 容器**、恢复 B 的编译缓存、执行同一预热及正式请求，检验跨容器命中率。
- B/C 必须同一镜像 digest、模型 commit 和 workload；记录 compiler event 数量与 cache hit/miss，不能只比较一个 TTFT 数字。

**保留条件**：C 相比 B，减少首次正式 8K TTFT、`T_first_useful_answer` 或真实成本中至少一个业务关键指标，同时服务稳定、输出正确；仅将 5s JIT 移到启动阶段但整体变慢则不算成功。

## 3. 优化二：真实 C4 并发

Penny Royal 上游 `configs/pennyroyal/request-capacity.sh` 当前默认：`MAX_RUNNING_REQUESTS=4`、`MAX_MAMBA_CACHE_SIZE=24`；我们覆盖为 2/12。两参数是**耦合的容量配置**：C4 要求对应的 Mamba 状态池，并可能改变 CUDA graph capture 和 VRAM 占用。

参考：https://raw.githubusercontent.com/jpezzulli/sglang-rtxpro6000/pennyroyal-main-sm120-final/configs/pennyroyal/request-capacity.sh

| 实验 | MAX_RUNNING_REQUESTS | MAX_MAMBA_CACHE_SIZE | 其他 |
|---|---:|---:|---|
| C2 对照（与持久化缓存验收同一次 GPU） | 2 | 12 | 原样 |
| C4 候选 | 4 | 24 | 同镜像、模型、NIXL、MTP policy、HiCache 等 |

验证顺序：
- API 先 smoke，后同时发送 4 条不同前缀、长度/输出预算尽量一致的请求；成功不代表内部 C4，必须从引擎 `#running-req:4`、`#queue-req` 与 `ReqTimeStats.queue_duration` 确认。
- 请求矩阵：同一启动生命周期下 C1、C2、C4 各 3 小批（每批目标 512-1024 真正输出 Token/请求，缺乏长输出则保留真实 token 数，不补造）；再 4 个中等上下文的小规模安全测试；每一批记录显存、CPU RAM、kv/mamba pool 占用、出错与超时。
- 比较 C2-C4 时引擎必须先 Warmup，关闭 profiler 以免额外 GPU trace 开销；同时保留 C4 额外的 capture/jit 与启动成本。
- **短时紧急回退**：若 OOM、CUDA graph 捕获失败、实际 state-pool 限制导致有效 C2、显存余量不足、错误回复或成本升高且吞吐未提升，则恢复 2/12，不修改 MTP tiered 策略或 KV 页面格式。

**保留条件**：在可比工作负载下持续聚合吞吐至少稳定提升约 10%，且请求成功、长上下文和首 Token 延迟仍可接受。10% 是筛选阈值而不是统计置信保证；边界结果需要重复运行确认。

## 4. 优化三：PLE 的真实 GPU 主机内存访问

**机制纠正**：Flash-Next 的约 47.68GiB PLE FP8 N-gram 表放在 CPU locked/pinned RAM；由 GPU 侧 Triton/UVA gather 读取需要的行，且可能与首个 decoder block 的计算重叠。并不是 CPU 核自己不断随机查表再显式 `cudaMemcpy` 到 GPU。CPU 指针追逐的 145 ns 和 Pinned bulk H2D 的 52.83 GiB/s 均**不是这个 gather 的实测延迟**。

参考：
- https://www.lmsys.org/blog/2026-08-26-qwen-flash-next/
- https://github.com/sgl-project/sglang/blob/main/docs/docs/developer_guide/benchmark_and_profiling.mdx

**先用原生工具，后最小侵入：**

1. 阅读 v3.1.5 镜像中实际 SGLang/GDN/PLE 源码，锁定 host-registered FP8 lookup 的调用函数、gather kernel 名、执行 CUDA stream 和 consumer wait 点；不要按网上的最新版文件/行号直接 patch 生产镜像。
2. 若运行时支持 SGLang 原生 `/start_profile` 和 `/stop_profile`，在已完成预热的服务中只抓 **10–30 个 decode steps** 和一段 8K prefill。优先记录 CPU/GPU trace、Kernel 列表与耗时、CUDA Graph 事件、stream 依赖、进程 CPU usec；trace 可 gzip 归档，限制大小、采样时间，并检查 GPU profiler 在 Modal 容器内是否允许。若接口不存在，则留错误并停止此路线，不假定成功。
3. PLE gather 确实成为热点且原生 trace 不够时，才在源代码中添加只读、采样式埋点：`PLE_ENQUEUE_CPU_US`、`PLE_GATHER_GPU_US`、`PLE_CONSUMER_WAIT_US`、访问行数/字节、`PREFILL/DECODE/VERIFY` 分组、C1/C2/C4 分组。CUDA 事件在正确流录制，并异步延后读取；**不能每 Token `torch.cuda.synchronize()`**，否则会人为破坏与模型计算的 overlap。
4. 将 gather 原始执行耗时与有效**关键路径等待**分开：gather 可能与计算重叠，不能把其整段时长当成推理损失。并以 SGLang MTP、PLE 表 CPU RAM 消耗及 CUDA graph 输出复核正确性。
5. 若 PLE 只占很小的关键路径，不再为它做进一步 CUDA 内核重写、NVMe PLE 或 CPU 大内存实验。

**终止条件**：拿不到可靠的 GPU 时间线且 SGLang 原生分析接口受限 → 先回退到低开销内核/系统日志分析，不增加容器权限或强行安装调试驱动。任何 profiling 效果只能与关闭 profiler 的相同配置对比，不能拿 profiler 模式的 tokens/s 直接当生产性能。

## 5. 最小付费测试顺序（每次只启动一张完整 GPU）

| 次序 | 目标 | 本轮运行内完成的内容 | 是否必要 |
|---|---|---|---|
| R0 | 历史基线 | 本次既有 JSON 和原始日志复用，无付费 GPU | 已完成 |
| R1 | 编译缓存写入 + 定向预热 | C2/12，空编译缓存，8K/32K warmup + 正式 8K + C1/C2/C4 提交测试；成功后归档缓存 | 必须 |
| R2 | 跨容器缓存复用 + C2 对照 | C2/12，恢复编译缓存；正式 8K + C1/C2/C4，最后可尝试短时原生 PLE profiler | 必须 |
| R3 | 实际 C4 | C4/24，固定相同配置，正式请求及可选短时 PLE profiler | 仅 R2 数据支持 |
| R4 | 深度 PLE Kernel 埋点 | 只在 R2/R3 发现 PLE gather 是实际瓶颈且原生 profiler 不够时开展 | 可选 |

R1/R2 预热/缓存以**新容器启动**为实验单位；R3 不盲目复用 R2 二进制缓存中与 C4 shape 不兼容的部分，仍需实际捕获 C4 CUDA graph。任何测试都不能只因请求数量为 4 就宣称“真实四路并行”。

按历史单次完整 GPU $0.356 作为参照，R1–R3 可以先以**每次约 $0.35–$0.60**规划；这不是费用上限或未来收费保证。各 run `max_seconds` / `timeout` / `budget_usd` 限制明确，若某阶段失败/无收益，不自动跑后续阶段。

特别提示：首次缓存生成本身就需 GPU 编译，不能只跑一个零模型的 CPU 探针来假设 SM120 JIT 缓存已存在。

## 6. 代码组织与原始数据

现有稳定入口 `qwen_modal_v2.py`、`qwen_storage_v2.py` 不改变默认行为，另建实验入口 `qwen_opt_experiment.py` 或显式实验参数，用少量配置表达三个正交开关：

```text
compiler_cache: ephemeral | persistent
shape_warmup: off | 8k | 8k-32k
engine_capacity: c2 | c4    # c2=2/12; c4=4/24
ple_profile: off | sglang-short | sampled-kernel
```

绝不按组合矩阵全扫，仅按 R1–R3 顺序启用需要的几个组合。测试输入尽量复用 `qwen_profile.py`；真实 Token 长度和后端 queue_duration 保留；另建少量 JSON 解析与缓存 manifest 校验回归测试。

新结果位置：`results/qwen_optimization/<UTC_run_id>/`

每次至少输出 `config.json`、`timings.json`、`requests.json`、`resources.json`、`engine.log.gz`、`billing.json`、`comparison.md`；启用 profiler 时追加对应压缩 trace（带原始 hash）。禁止覆盖旧日志或擦除已有 Volume。**现金账单取 Modal Billing Report，估价仅作启动前预算检查。**

## 7. 设计结论

- **先编译缓存与定向预热**：目前证据最强、修改范围最小。
- **再做 C4/24**：这是 Penny Royal 上游支持的有效容量路线；必须看 `running_req=4` 与 Mamba 状态池。
- **PLE 最后深入**：正确方向是测量 GPU UVA gather、stream overlap 和关键路径，而不是重复 CPU RAM pointer-chase。
- 不为 ComfyUI 或 GLM 额外测试。它们未来若需要，可直接借用实验记录规范，但本方案只服务 Qwen。
- **实际执行后状态：** 缓存 Volume 已创建，R1/R2/R3 已完成，原始生产入口未修改，实测总账单见 [最终报告](QWEN_OPTIMIZATION_JIT_C4_PLE_FINAL_20261104.md)。本段其余内容为实施前的设计意图。
