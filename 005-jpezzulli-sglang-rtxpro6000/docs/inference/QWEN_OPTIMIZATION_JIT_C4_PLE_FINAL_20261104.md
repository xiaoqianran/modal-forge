# Qwen3.8-Flash-Next / RTX PRO 6000：JIT、真正 C4、PLE 三项优化实测结论

> 实测时间：2026-11-04。状态：**R1 / R2 / R3 均已完成，GPU 任务已结束**。模型权重 Volume v1/v2 未修改、未重新下载权重。三轮均为单卡 RTX PRO 6000、4 CPU、80 GiB RAM 请求、8 GB HiCache、TP1、NIXL off，镜像为 `ghcr.io/jpezzulli/sglang-rtxpro6000:v3.1.5`。

**决定：编译缓存技术有效，可继续作为候选功能；暂不把 C4/24 作为默认生产配置；PLE 暂不重写 Kernel。** 这一判断基于真实请求、Penny Royal 进程日志、Modal 账单和 SGLang Profiler Trace。当前样本数不足以证明总体冷启动有统计意义的加速。

## 1. 真实实验设置

| 运行 | App ID | 引擎请求上限 / Mamba 缓存 | 编译缓存 | 额外预热 | 状态 |
|---|---|---|---|---|---|
| R0 历史 | `ap-pZT5OHNvbDiacMnR5S1kQ8` | 2 / 12 | 临时 | 原始 smoke | 成功 |
| R1 | `ap-bv8z1SnCbsetXa4nOF4Rjl` | 2 / 12 | 首次生成、归档 | 8K、32K | 成功 |
| R2 | `ap-kGTCTgnUA59KfyQON2c1BF` | 2 / 12 | 独立 Volume 恢复、SHA 校验 | 同 R1 | 成功 |
| R3 | `ap-h0cjfHhBlltfgkCCClPWLt` | 4 / 24 | 临时，**与 R2 缓存不同** | 同 R1 | 成功 |

R1/R2 测量使用相同版本指纹 `a0ad50b34806e2cb25cca621f8f33907aa472fdba75b03d4514f80dd127e2243`。CPU-only 镜像审查确认原版启动脚本读取 `CACHE_BASE` 和 `TILELANG_CACHE_DIR`。各运行的真实输入 Token 数和服务端 usage 均保存在原始 JSON。这里的“8K/32K”是口语标签，实际 shape warmups 为 **8,454 / 35,055** Token；正式中/长请求为 **8,103 / 32,253** Token。

**注意 R3 不是 R2 的严格单变量对照**：R3 容量从 C2/12 改为 C4/24，但编译缓存也从持久化切换为临时缓存。C4 稳态的首次批次结果仍值得重视，但不能把它用于判断整体启动的容量因果效应。R1 vs R2 新容器也存在不同宿主和文件页缓存干扰。

## 2. JIT 缓存：明确成功的部分

| 指标 | R1 首次生成 | R2 跨容器恢复 |
|---|---:|---:|
| TileLang `begins to compile` 日志数 | **3** | **0** |
| 8K 定向预热 TTFT | 7.174 s | **0.826 s** |
| 8K 正式请求 TTFT | 0.570 s | 0.589 s |
| API Ready | **252.08 s** | 273.78 s |
| Traffic Ready（含预热） | **277.39 s** | 288.65 s |
| First Useful Answer 完成 | **278.29 s** | 289.49 s |
| 引擎权重加载 | 106.24 s | 145.63 s |

**证实：** 恢复一份已发布的 35,696,640 字节 compiler-cache tar（1,277 个文件、有效载荷33,391,571字节），恢复只花 **1.748 秒**，跨新容器复用全部 3 个目标 TileLang 编译产物，R2 无可见重新编译事件。R1 缓存发布到独立 Volume v2 仅 **1.216 秒**。

**没有证实：** 整体冷启动加速。R2 比 R1 的 API ready 晚约 21.7 秒，主要伴随权重加载从 106.24s 变为145.63s。文件/宿主缓存状态不受控；`traffic_ready` 也没有缩短。因此不能声称冷启动已经优化成功，不能通过减去 JIT 时长的方式推导最终总收益。

**工程建议：** 保留独立 compiler cache Volume 与恢复逻辑作为候选，生产默认入口 `qwen_modal_v2.py` 仍保持原样。缓存复用指纹已覆盖模型 revision、image tag、Torch/TileLang/Triton/FlashInfer/SGLang 版本、Penny Royal 配置脚本 SHA、架构 sm120、容量参数。正式生产化之前需进一步锁定**镜像 digest / GPU 驱动 ABI**，避免同名镜像 tag 发生变化而错误复用编译二进制。

## 3. 实际四路并发：请求真正同时运行，但首批性能很差

R3 启用 `MAX_RUNNING_REQUESTS=4` 和 `MAX_MAMBA_CACHE_SIZE=24`，Penny Royal 日志确认 `max_running_requests=4`、GDN recovery graph buckets=[2,3,4]，且 Decode batch 出现 **`#running-req: 4`**。不是因为调度器限制才没有跑上去。

| R3 任务 | 总吞吐（真实输出 Tokens/批次秒） | 批次耗时 |
|---|---:|---:|
| 1 客户端 | 289.63 tok/s | 0.884 s |
| 2 客户端 | **410.48 tok/s** | 1.223 s |
| **4 客户端** | **149.91 tok/s** | **6.831 s** |

四路每条都成功、各输出 256 Token，但 TTFT 分别为 **5.1615、5.4376、5.4371、5.4368 秒**。

**日志级原因定位**：
- 四个请求的 `queue_duration` 分别约0.58、0.94、0.61、0.69毫秒，均不到1ms；**不是排队**。
- 对应的 `initial_prefill_elapsed` 约5342.57、5154.72、5342.52、5342.27毫秒；5秒以上延迟发生在请求进入引擎后的 **首批 Prefill**。
- C4 期间没有新 `TileLang begins to compile` 日志；启动时已 capture batch size 2/3/4 的 GDN/CUDA Graph。**不能说是已发现的 TileLang 编译使 C4 变慢**。
- 本次是**唯一的一次 C4 批次**。不能断言后续批次也必然维持149.9 tok/s；可能有未在日志明确标注的 C4 首次形状初始化、图恢复、Triton 首次调用或同步开销。还没有证据分辨。

**决定：目前不把生产默认值调整到4/24，保持2/12。** 如果未来业务确实需要超过两路同时运行，下一次专门验证应在**同一 C4 GPU 生命周期内连续重复三轮相同的4客户端批次**，分别记录第一批与后续热批 `initial_prefill_elapsed`、TTFT、MTP 接受率及累积吞吐；只有后续热批稳定改善后再考虑保留 C4。切勿根据一个首批就断言稳态 C4 失败，也不应为了这项测试马上再付费启动模型。

## 4. PLE 原生 GPU Trace：拿到证据，但关键路径尚未证明

R2 完成正常推理基准之后，调用 Penny Royal 中 SGLang 原生 `/start_profile`，采集12步 CPU/GPU Trace，**不会混入生产性能计时**。

- 压缩 trace：`results/qwen_optimization/traces/r2_20261104T082923_17439d.tar.gz`，原始存储在独立编译 Volume 的 `profile_traces/`。
- 归档 SHA-256：`2682e5809370778c0388861a4240b44f2adb56031068affc71e93477686adeb3`。
- Trace 原始事件约 **298,199** 条，其中显式 `cat=kernel` 的 GPU Kernel 事件约 **30,862** 条。
- 真实 `_gather_ple_embedding_from_pinned_kernel`：**12 次调用，Kernel 执行时长总和约 0.189 ms**（只对这12个采样步骤有效）。
- 误判纠正：早期直接搜索子串 `ple` 会误匹配 C++ `tuple`，导致错误统计约1,397条/79.7ms；分析程序已经改成带单词边界的匹配，仅报告精确 PLE 核心名。**0.189ms 不是 PLE Critical-Path Stall 时间**。
- CUDA 图、其他 Kernel 可能异步重叠；Trace 需进一步求解依赖边与 Consumer Wait 才能确定 PLE 导致的用户可感知延迟。Profiler 请求自身的吞吐因工具开销显著下降，绝不能作为正常生成速度。

**决定：暂不重写 PLE Gather、扩展 CPU RAM、切换 NIXL 或安装危险的驱动级 profiler。** 先在已有 Trace 上继续做 stream overlap / wait 归因；如果 Gather 被计算重叠，优化它不一定改变 tokens/s。

## 5. GPU 资源与费用（当次查询的真实 Modal Billing）

| 任务 | GPU | Memory | CPU | 合计 |
|---|---:|---:|---:|---:|
| R1 | $0.25118513 | $0.05305560 | $0.01568456 | **$0.31992529** |
| R2 | $0.27066853 | $0.05717091 | $0.01690115 | **$0.34474059** |
| R3 | $0.26616324 | $0.05621930 | $0.01661983 | **$0.33900237** |
| **三轮总计** | | | | **$1.00366825** |

Network Egress 当次查询均为$0；账单可能有后续调整。**不包含** CPU-only 预检和 compiler Volume 的长期存储费用。每轮独立设置函数超时和预算估算检查，模型 Volume v1/v2 没有重下或复制。

R3 最大采样 GPU VRAM约 **80.883 GiB**、CPU RAM约 **107.763 GiB**；R3 未因 C4 立即发生 OOM。内存数据为采样峰值，并非微秒级瞬时上限。

## 6. 最终操作建议及回退

| 模块 | 当前决策 | 推理默认设置 |
|---|---|---|
| 编译缓存 | **验证成功，保留独立实验与缓存**；进一步控制宿主/文件缓存条件比较总启动 | 不切换默认生产入口 |
| 8K/32K 定向预热 | 正式8K TTFT 改善的机制成立，但预热会延后 traffic-ready | 默认预热策略暂不改 |
| C4/24 | 真四路运行成功；**首批吞吐大幅下降**，不通过生产保留条件 | **继续 C2/12** |
| PLE gather | Trace 已精确定位，尚无关键路径瓶颈证据 | 维持当前 RAM PLE 实现 |

所有新实验都在独立入口 `qwen_opt_experiment.py`，模型推理默认入口 `qwen_modal_v2.py` 保持原状态；缓存逻辑在 `qwen_compiler_cache.py`，低成本 CPU 探针及单元测试分别位于 `qwen_opt_image_audit.py`、`qwen_opt_cache_preflight.py`、`test_qwen_compiler_cache.py`。不向 ComfyUI、GLM 项目注入额外实验。

本轮详细指标自动表：`QWEN_OPTIMIZATION_RESULTS_20261104.md`。

完整原始数据：
- `results/qwen_optimization/r1_20261104T082240Z_809854cf/`
- `results/qwen_optimization/r2_20261104T082939Z_e8cd0b30/`
- `results/qwen_optimization/r3_20261104T083619Z_d62d9131/`
- `results/qwen_optimization/optimization_comparison.json`
- `results/qwen_optimization/traces/r2_20261104T082923_17439d.tar.analysis.json`

**明确的下一实验（需要时才进行）：在同一容器内重复 C4 热批，区别第一次 Prefill 开销与可持续吞吐。下一步不必重新测试 DDR、Volume 或完整编译缓存。**
