# Qwen3.8-Flash-Next：RTX PRO 6000 首次真实负载专项性能分析

测试日期：2026-11-04，PC2，Modal App：`ap-pZT5OHNvbDiacMnR5S1kQ8`

[Modal 运行记录](https://modal.com/apps/seachenxyt/main/ap-pZT5OHNvbDiacMnR5S1kQ8)

## 一、实际运行条件与证据

- 模型：`RadixArk/Qwen3.8-Flash-Next-NVFP4`；revision `7b719225242aacd3dbd3f9407468c2ee9a9d2594`
- Penny Royal 镜像：`ghcr.io/jpezzulli/sglang-rtxpro6000:v3.1.5`
- 存储：Volume v2，419 文件 / 135,253,622,894 字节，**没有重新下载或覆盖权重**
- GPU：1×RTX PRO 6000 Blackwell；CPU：4 cores；申请 RAM：80 GiB；HiCache：8 GB；PLE backend：`ram`；NIXL：off
- GPU serving 引擎 `MAX_RUNNING_REQUESTS=2`，未改变。4 客户端会排队，不能认为模型真正并行执行 4 路
- 运行方式：一次 Modal `infer` GPU 实例，原服务起来后，先做原有两条烟雾测试，再短/中/长上下文，最后 1/2/4 客户端并发
- 14 项本地离线回归通过；此次 GPU 所有请求成功，无跳过项，算术答案校验通过
- 记录原始 JSON：`results/qwen_flash_next_v2/infer_80g_20261104T073426Z.json`
- 完整原始日志（gzip）：`results/qwen_flash_next_v2/infer_80g_20261104T073426Z.log.gz`。**解压后的** SHA-256：`4f361adad4baaa6d50d0bff0a7c1c09c80e4ceaf9c80eacd151df9b357f713f2`
- 分项详细 Markdown：`results/qwen_flash_next_v2/PROFILE_REPORT_infer_80g_20261104T073426Z.md`

## 二、冷启动时间与瓶颈

| 指标 | 本轮结果 | 说明 |
|---|---:|---|
| API /v1/models 就绪 | **312.66 s** | 从 GPU 函数实际开始执行到 API 返回模型 |
| 权重加载总计 | **116.98 s** | 引擎报告值，含主模型 104.12 s + MTP 12.86 s |
| KV Cache 分配 | 2.35 s | 引擎报告，可能嵌套 |
| scheduler_e2e | 216.08 s | 引擎内部累计阶段；不能简单与 weight 累加 |
| tokenizer_e2e | 237.03 s | 引擎内部累计阶段；不能简单与 scheduler 累加 |
| CUDA Graph target verify | 9.65 s | 引擎总计 |
| CUDA Graph draft decode | 9.55 s | 引擎总计 |
| CUDA Graph draft extend | 3.50 s | 引擎总计 |
| 引擎 Warmup ended | 07:33:43 UTC | 结构化输出 warmup |
| API ready | 07:33:44 UTC | 首次 API 返回模型 |
| 原有两条 smoke 全部结束 | 约 07:34:04 UTC | **API ready 后还用了约 19.2 秒** |
| 本轮完整函数含请求 | **354.54 s** | 不是只有启动 |

旧 v2 的可参考历史：2026-11-04 05:xx 启动约 327.11 s、load_weight=180.92 s。新值 312.66 s、116.98 s。**不能宣称代码优化使得权重快了 64 秒**：两次并非控制严格的缓存/宿主重复试验，差异可能来自 Volume 后端 cache、JIT cache 和云端宿主状态。

分段直观上，116.98s 的权重载入约占 312.66s API 就绪时间的 37.4%；其余阶段仍有很大优化空间。不要将所有引擎内部 e2e 时间直接相加。

## 三、真实请求速度：测量依据是 SSE 流 + 服务端 usage

| 阶段 | 输入 tokens | 输出 tokens | TTFT 秒 | TPOT ms | Decode tok/s | 总耗时 s | 正确 |
|---|---:|---:|---:|---:|---:|---:|---|
| Short | 46 | 211 | 0.3708 | 3.888 | 257.21 | 1.1873 | 是 |
| Medium | **8,103** | 139 | **7.5582** | 3.254 | 307.28 | 8.0073 | 是 |
| Long | **32,253** | 137 | **2.6756** | 2.978 | 335.84 | 3.0806 | 是 |

**关键发现：8K 请求比 32K 请求 Prefill 更慢，是首次运行时 Kernel 编译的强烈信号。**
- 8K 远端引擎日志：`initial_prefill_elapsed=7499.54ms`；期间发生两次 `TileLang begins to compile kernel`，07:34:05→07:34:09、07:34:09→07:34:10。
- 32K 引擎日志：`initial_prefill_elapsed=2130.51ms`，这段期间没有再次触发对应 TileLang 编译。
- 两者引擎 `cached_input_len=0` 且 mamba 日志 `host_hit=0`，说明**不能用已命中相同 prefix 来解释这两者的差异**。
- 但一次实验不能证明整个 TTFT 差值全部来自编译；还有已热 Kernel、调度器、内存/cache 状态和输入形状影响。

**优化价值：** 在 API 就绪前提前触发需要的 TileLang/CUDA Kernel 编译，或者将可复用的编译缓存安全持久化。应以 API Ready、第一条真实请求 TTFT 和总计费时间联合衡量，不允许只把耗时从请求阶段移到启动阶段后就宣布优化成功。

## 四、并发与真实排队

| 并发客户端 | 批次完成用时 | 聚合真实 output tokens/s | 首 Token 现象 |
|---|---:|---:|---|
| 1 | 0.8722 s | 293.50 | TTFT 0.1002 s |
| 2 | 1.2760 s | **397.35** | 两条 TTFT 约 0.19 s |
| 4 | 2.5774 s | **397.29** | 前两条 TTFT 约 0.19 s，后两条 **1.33s / 1.48s** |

4 客户端总吞吐未高于 2 客户端，因为引擎运行上限为 2。引擎 ReqTimeStats 还明确显示后两条的 `queue_duration` 超过 **1.1–1.28 秒**，说明显著排队。

**优化价值：** 下一次如果业务目标是并发，最直接的单变量试验是 `MAX_RUNNING_REQUESTS=4`，但这可能增加启动阶段 CUDA Graph capture、CPU/GPU RAM 和显存压力，必须单独保留基线进行 A/B。当前没有测试 4 路真正同时执行。

## 五、内存与 CPU PLE 证据

- GPU 显存最高采样：**80.884 GiB**；GPU 总显存约 95.6 GiB。
- CPU RAM 1s 采样最高：**107.739 GiB**；任务结束前约 66.5 GiB。Modal 申请的是 80 GiB，但实际使用可能超过这个值，计费按平台实际报告。
- 容器 cgroup v1 本次没有提供可用 `memory.peak`，因此不能把 107.739 GiB 声称为毫秒级**精确峰值**。它是 1s 采样最大值。
- `PLE: host RAM | HiCache: true | Host tier: 8 GB` 已在引擎日志出现；此外记录 14 条 `mamba match`，代表可见的 mamba/cache 路径信息，**不是 PLE 查表延迟的直接测量**。
- 本轮引擎镜像是 cgroup v1，`/sys/fs/cgroup/cpu.stat` 未提供 CPU 使用时间，故本次 **没有有效的 CPU 核心使用率样本**。后续代码已补充 cgroup v1 `cpuacct.usage` 兼容回退，需在下一次运行才有真实数据。
- 已真实执行 `lscpu`、`numactl --hardware`、`nvidia-smi -q`、`cat /proc/cpuinfo`，四项 exit=0；`lstopo` 不在 Penny Royal 运行镜像中（因其不支持 apt-get，不修改生产镜像安装，结果标记不可用）。CPU 型号 `unknown`，DDR 型号未知。

要**确认 CPU PLE 是否真正卡住稳态 Token**，下一轮必须对 Penny Royal/ SGLang 的 PLE 数据访问路径做采样或增加计时：实际命中率、随机查表次数、CPU 耗时、H2D 小块传输以及 GPU 等待。现阶段不能据此认定 PLE 已经是最大瓶颈。

## 六、真实计费

本次 App ID：`ap-pZT5OHNvbDiacMnR5S1kQ8`。2026-11-04 Modal Billing Report 在本次查询时返回：

| 计费项 | 实际记录 |
|---|---:|
| RTX PRO 6000 | $0.27948705 |
| CPU | $0.01745180 |
| RAM | $0.05903357 |
| Network egress | $0.00000000 |
| **合计** | **$0.35597242** |

程序事前的 `$0.815` 是 760s×申请量的安全估算门槛，不是实际消费，更不是平台账户硬限额。程序结果中的 `estimated_usd=0.3912` 也是估计而非账单。平台账单可能随后修订。

此前一次失败发生在构建镜像步骤，未进入 GPU 实际运行；此次完整模型启动只有一次。

## 七、下一步最小必要 A/B（不在本轮追加付费 GPU）

**P0：先解决首条长上下文 Kernel JIT 延迟。** 用已有日志确定具体 TileLang Kernel 和缓存目录；在启动前预热对应 kernel，比较优化前后的 *API Ready + First Useful Response* 而非单看 TTFT。必须证明缓存命中和相同工作负载下的净收益。

**P1：再决定是否改真实运行并发上限。** 只有目标确实包含多个同时用户才将 `MAX_RUNNING_REQUESTS` 从 2 改成 4，测试单位成本、P95 TTFT、显存峰值和长上下文稳定性。

**P1：定位真实 PLE 性能。** 目前 CPU RAM 与 pinned/GPU 微基准已做，下一步必须用真实模型的 PLE 调用次数和热点函数支持优化结论，避免泛用 CPU RAM 测试和模型内部实际路径脱节。

**P2：优化权重加载。** 历史从 180.92s 到本轮 116.98s 差异很大，但缓存和宿主变量未控；应先重复可靠基线，不能单凭单次结果就引入复杂的权重预取/SSD 复制方案。

所有新实验都须保存原始 JSON、压缩日志、模型 revision、镜像、gpu/cpu/ram、配置指纹及真实账单。一次只修改一个关键变量，不为 GLM 或 ComfyUI 额外运行 GPU。
