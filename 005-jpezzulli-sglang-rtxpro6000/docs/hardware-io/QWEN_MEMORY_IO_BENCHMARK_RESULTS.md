# Qwen3.8-Flash-Next / RTX PRO 6000：CPU RAM、PCIe、Volume v1/v2 实测

**日期：2026-11-04；项目：005-Default-GPU-Memory；目标：定位单卡 RTX PRO 6000 + Penny Royal + CPU PLE 的优化方向。**

## 1. 结论概览

本轮只执行 microbenchmarks，**不重新下载 126.9 GiB 模型、不启动完整 Qwen，也不构成真实 Qwen PLE 吞吐测试**。

**已证实：**
1. RTX PRO 6000 节点的 **4 CPU 核 STREAM Triad = 133.13 GB/s**，比本轮其他 GPU 节点更高；但 256 MiB 指针追逐随机访问为 **145.45 ns**，并非最低。
2. RTX PRO 6000 使用 **Pinned CPU Memory** 时，128 MiB 的 H2D 有效速率约 **54,097 MiB/s (52.83 GiB/s)**；D2H 约 **53,671 MiB/s**。连续 PCIe 传输很快，但这不等于实际 PLE 随机取数速度。
3. CPU-only 模型 Volume v1/v2 首次顺序读取约 1.6–2.8 GiB/s（各次、各请求区间不同），同容器重复读取可显著加快；数据受文件页缓存影响，不能外推为纯存储硬件带宽。
4. RTX PRO 6000 上 256 MiB 真正的 Volume→RAM→Pinned RAM→GPU 路径，**GPU 上传仅约 0.005s**；文件第一次读取 0.639–1.156s、CPU→Pinned 复制约 0.076–0.089s。在这类顺序路径上，文件读取更值得优化。
5. CPU 型号、NUMA 物理拓扑和 DDR4/DDR5 均**未直接得到完整宿主信息**。hwloc 在 PRO6000 上成功运行，但只展示容器可见的单 NUMA 节点和 CPU 核心列表，无法验证实际 DDR 型号。

## 2. 四卡 RAM / PCIe 基准

所有测试相同：**4 CPU 核、8 GiB 申请 RAM、同一 CUDA 12.8.1 Runtime 镜像、不加载模型**。STREAM 使用官方 stream.c，数组 50,000,000 double ×3，约 1.12 GiB，8 次迭代；随机测试使用可复现的随机单链指针追逐（8、64、256 MiB），2,000,000 次依赖访问；GPU 使用同步 CUDA Runtime API 测量 Pageable/Pinned H2D、D2H 各 1/32/128 MiB，返回 3 次中位数。

| GPU | STREAM Triad 1 核 GB/s | STREAM Triad 4 核 GB/s | 随机 256 MiB 延迟 ns | Pinned H2D 128 MiB GiB/s | Pinned D2H 128 MiB GiB/s |
|---|---:|---:|---:|---:|---:|
| T4 | 12.85 | 48.38 | 89.10 | 5.83 | 6.15 |
| A100 40GB | 17.77 | 51.90 | 116.26 | 24.34 | 22.42 |
| L40S | 30.79 | 66.11 | 107.48 | 12.52 | 12.30 |
| **RTX PRO 6000** | **47.18** | **133.13** | **145.45** | **52.83** | **52.41** |

对 RTX PRO 6000 的 128 MiB 传输：
- **Pageable H2D**：35,412 MiB/s（约 34.58 GiB/s）
- **Pinned H2D**：54,097 MiB/s（约 52.83 GiB/s）
- **Pinned D2H**：53,671 MiB/s（约 52.41 GiB/s）

**解读：** Pinned RAM 对 PRO6000 连续传输确实有明显收益。但 PLE 的访问可能是大量随机、小粒度、延迟敏感的查询；不能因为 53 GiB/s 的大块 H2D 就认定 PLE 没有瓶颈。

**局限：** 随机指针追逐包含 CPU Cache/TLB/NUMA 和虚拟化影响；工作集最大仅 256 MiB，远小于约 48 GiB PLE；同一 GPU 仅测一次；`libgomp` 对核心/插槽拓扑报出读取警告但 STREAM 完成并通过数值校验。这里量的是**实际容器、申请 4 核的有效吞吐**，不是物理 DDR 的满插内存通道峰值。不同 GPU 对应的 CPU 宿主不一致，不能简单认为差异全部由 GPU 芯片造成。

原始记录：
- `results/qwen_benchmark/memory_t4_20261104T064905Z.json`
- `results/qwen_benchmark/memory_a100_20261104T065006Z.json`
- `results/qwen_benchmark/memory_l40s_20261104T065015Z.json`
- `results/qwen_benchmark/memory_pro6000_20261104T065027Z.json`

## 3. CPU-only 的 Volume v1/v2 实际文件读取

两卷均完整存储同一个模型 commit `7b719225242aacd3dbd3f9407468c2ee9a9d2594` 的 419 文件；同一个模型分片 `model-bf16-00011.safetensors`，在独立 CPU-only 容器里依次测试，交换了两轮测试顺序。**未向 Volume 写入任何数据**。

| 第一遍读取 | v1 顺序 v1→v2 | v2 顺序 v1→v2 | v1 顺序 v2→v1 | v2 顺序 v2→v1 |
|---|---:|---:|---:|---:|
| 1 GiB，MiB/s | 1849.54 | 1817.99 | 2054.47 | 1626.73 |
| 4 GiB，MiB/s | 2821.79 | 2414.21 | 2574.55 | 2284.84 |

同容器第二遍 4GiB 可达到 v1 8,354–10,088 MiB/s、v2 7,190–7,506 MiB/s，**明显受页缓存/存储缓存影响**，不代表远程 Volume 冷读性能。256 次 4 KiB 与 64 KiB 随机 `pread` 请求结果波动很大，不能仅用一次 IOPS 决定 v1/v2 胜负。

**就本轮首次顺序读取来说 v1 略快，但前序同一 GPU 的小片段测试又显示 v2 更快；目前只能把它当待复现的趋势，而不能说 v2 在任何情况下都更慢。**

原始记录：
- `results/qwen_benchmark/volume_cpu_v1_v2_20261104T064809Z.json`
- `results/qwen_benchmark/volume_cpu_v2_v1_20261104T064847Z.json`

## 4. 同一张 RTX PRO 6000 的 Volume→CPU→GPU

GPU 容器**同时只读挂载 v1 和 v2**，用同一文件的首 256 MiB，先 v1→v2，再反转为 v2→v1；每次记录读取、拷贝到 Pinned CPU RAM 和 GPU H2D 用时。

| 测试 | v1 | v2 |
|---|---:|---:|
| 第一次 256MiB 文件读取 | 1.156s | 0.639s |
| 第一次 CPU→Pinned RAM 拷贝 | 0.089s | 0.076s |
| 第一次 Pinned→GPU | 0.00498s | 0.00495s |
| 第一次端到端总时间 | **1.250s** | **0.725s** |
| 第二次端到端总时间 | 0.203s | 0.175s |
| 本地预取+读取+GPU（在缓存预热后执行） | 0.336s | 0.290s |

**绝对不能把“预取+读取”与第一遍冷读对比就宣称本地预取更快**：本地预取测试是在多轮读取、缓存已经变热之后进行的。本实验没有证明“先复制到本地 SSD”能缩短完整模型首次加载。此处 `/tmp` 所在存储类型也未确认为独立 SSD。

注意第一遍的数据顺序是 v1→v2，而第二遍是 v2→v1；系统页缓存仍可主导差异。**这只是顺序 IO 的路径分解，并非 GPU Direct Storage 或真实 SGLang 权重加载。**

原始记录：`results/qwen_benchmark/volume_gpu_20261104T065113Z.json`

## 5. 对我们单卡 Qwen 的优化优先级

结合此前真实完整 Qwen v1/v2 A/B：
- 80 GiB RAM 申请、4 CPU 核、单张 PRO6000、8GB HiCache，完整模型启动均成功。
- 对照启动：v1 **286.71s** / v2 **327.11s**；预热后短请求生成速度约 **339–362 tokens/s**。
- v2 引擎日志中 `load_weight=180.92s`，整段 API 就绪 `327.11s`，因此权重加载阶段是重要优化目标，但不是唯一瓶颈。

| 优先级 | 优化方向 | 依据和预期验证 |
|---|---|---|
| P0 | **权重加载阶段精确埋点** | 将 v1/v2 的 `load_weight`、存储读、权重反序列化、CPU PLE 建表、GPU 初始化分开记时；目前只有 v2 `load_weight=180.92s`，无法分摊 40.4s 差异 |
| P0 | **CPU PLE 随机查表与 CPU→GPU 小块传输** | PRO6000 顺序带宽较强，但 256MiB 随机指针访问为 145ns；需对实际 Penny Royal 查表调用做 Nsight Systems/CPU profiler 采样，不能用大块 memcpy 结论代替 |
| P1 | **Weight loader IO 与分片并发** | 初次文件读取远慢于预热缓存，优先研究 safetensors 并行加载、mmap 与缓存行为；必须按同一 commit、同 GPU 和反向顺序重复验证 |
| P1 | **Pinned RAM → GPU 传输** | 128MiB Pinned H2D≈52.83GiB/s，相比 Pageable≈34.58GiB/s；连续大块路径已有高吞吐，重点检查真实 PLE 是否大量小拷贝、同步和数据重复拷贝 |
| P1 | **CUDA Graph / Warmup / Kernel 编译** | 服务就绪不等于文件读完；此前引擎调度器和预热仍占有时间，应单独记录并争取缓存或预热路径复用 |
| P2 | **本地临时盘预取、GPUDirect Storage** | 目前没有预取缩短完整 Qwen 冷启动、或 Volume 支持 GDS 的证据；先做可证明收益的分段数据路径对照，再决定是否增加复杂度 |
| P2 | **RAM 容量与并发数调优** | 历史 80 GiB 申请量、实际加载 RAM 峰值约 107.7 GiB；需结合 Modal 按实际占用计费规则、CPU PLE 峰值以及双并发的真实负载稳定性，不要盲目扩内存 |

**本轮 4 核 / 8 GiB 的微基准并不是 80 GiB 的真实 PLE RAM 部署测试。** 对 48GiB 真实随机访问、2 路长输出并发、满上下文的实际推理性能，仍需要真实服务 profiler 才能判断。按成本与风险考虑，我们暂未启动一轮完整大模型再测试。

## 6. 成本边界

按 Modal `billing report --for today --resolution h --show-resources --json` 返回的本轮已出账任务：
- 四卡微基准：T4 $0.002342；A100 $0.005229；L40S $0.002446；PRO6000 $0.001824，**合计约 $0.01184**。
- 两轮 Volume CPU-only IO：$0.002110 + $0.001547 ≈ **$0.00366**。
- 同 GPU 的 Volume→CPU→GPU：约 **$0.003649**。
- 首次调试时 image/CPU 任务记录：$0.000685；另一失败应用及后续 hwloc 探针可能晚些才计费。

可确认的以上小计 **约 $0.01983**，不是最终账单上限，云平台后续结算可能变化。不包含 Volume 的持久存储长期计费。

本轮不申请 >8GiB 的微基准内存、不执行高负载模型推理、不重新下载两份 126.9GiB 权重，没有无限等待 GPU 排队的任务。

## 7. 可复现命令与工具

```powershell
# CPU-only，读两份已存在的 Volume，交替次序
uv run --locked python -m modal run -m benchmarks.qwen_volume_cpu_benchmark --order v1-v2
uv run --locked python -m modal run -m benchmarks.qwen_volume_cpu_benchmark --order v2-v1

# 四卡轻量 microbench，单次只运行一张卡
uv run --locked python -m modal run -m benchmarks.qwen_mem_benchmark --gpu t4
uv run --locked python -m modal run -m benchmarks.qwen_mem_benchmark --gpu a100
uv run --locked python -m modal run -m benchmarks.qwen_mem_benchmark --gpu l40s
uv run --locked python -m modal run -m benchmarks.qwen_mem_benchmark --gpu pro6000

# 单张 PRO6000、两份 Volume 同时只读、各用 256MiB 分段验证
uv run --locked python -m modal run -m benchmarks.qwen_volume_gpu_benchmark

# 完全离线的单元测试（不产生云端账单）
uv run python -m unittest test_qwen_cache.py test_qwen_microbenchmark.py -v
```

- STREAM 官方源码：https://www.cs.virginia.edu/stream/FTP/Code/stream.c
- hwloc 文档：https://hwloc.readthedocs.io/
- tinymembench：https://github.com/ssvb/tinymembench （本次随机延迟用可控工作集的自实现指针追逐，而不是运行 tinymembench 原始程序）
- NVIDIA CUDA bandwidthTest：https://github.com/NVIDIA/cuda-samples （本轮使用同等底层的 libcudart 同步拷贝，而非 cuda-samples 二进制）。
- 当前独立的 hwloc 实测：`results/gpu_hardware/rtx_pro_6000_20261104T065514Z.json`（容器只展示可见 NUMA 和 17 个逻辑核心，DDR 未知）。

**结论：保留 Volume v1/v2 两套完整模型和 A/B 入口；下一轮首选加强真实 Penny Royal 的分段计时与 CPU PLE profiler，而不是凭 DDR 代际或单次 token/s 决策。**
