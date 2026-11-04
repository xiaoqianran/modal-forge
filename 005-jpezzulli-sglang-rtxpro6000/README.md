# 005-jpezzulli-sglang-rtxpro6000

单卡 **RTX PRO 6000** 上的 Qwen3.8-Flash-Next-NVFP4 / Penny Royal (SGLang) Modal 运行与实测项目。使用上游预构建镜像 `ghcr.io/jpezzulli/sglang-rtxpro6000:v3.1.5`，**本目录不是上游 SGLang 源码的 Git fork**。

## 项目结构

```text
005-jpezzulli-sglang-rtxpro6000/
├── qwen_modal_v2.py          # 稳定的 Qwen 推理 / 监测入口
├── qwen_download_v2.py       # 模型 Volume v2 检查与下载
├── qwen_core/                # 正常推理共享模块
│   ├── storage.py            # v2 模型 Volume
│   ├── hardware.py           # 资源信息采集
│   └── profile.py            # 流式请求测量
├── benchmarks/               # JIT、C2/C4、PLE、GPU/RAM/IO/Volume 测试和报告工具
├── legacy/                   # v1 历史实现 + 早期默认 GPU 内存探针 app.py
├── tests/                    # 离线回归测试
├── docs/                     # 按主题归档的实验说明与结论
└── results/                  # 原始 JSON、日志、trace、账单；default_gpu/ 存早期探测结果
```

**注意：** `qwen_core/`、`benchmarks/`、`legacy/` 和 `tests/` 均为 Python 包。Modal 对包使用 `.add_local_python_source("qwen_core")` 等方式打包；迁移后从项目根目录使用 **`modal run -m 模块路径`**，避免依赖脚本执行时的当前目录。

## 开始使用

在本项目根目录执行，以下命令只做本地检查，不启动云端 GPU：

```powershell
uv sync --locked
uv run --locked python -m unittest discover -s tests -p "test_*.py" -v
uv run --locked python -m modal run -m qwen_modal_v2 --help
uv run --locked python -m modal run -m qwen_download_v2 --help
uv run --locked python -m modal run -m benchmarks.qwen_opt_experiment --help
```

经明确决定要使用 Modal 云端资源时再执行（**可能产生账单**）：

```powershell
# 只检查 v2 模型缓存（CPU 计费）
uv run --locked python -m modal run -m qwen_download_v2 --stage check

# 单卡 Qwen 实际推理测试（RTX PRO 6000 GPU 计费）
uv run --locked python -m modal run -m qwen_modal_v2 --stage infer --cpu-cores 4 --ram-gib 80 --hicache-gb 8 --max-seconds 540 --budget-usd 1.5 --workload smoke
```

独立历史和基准测试入口：`legacy.qwen_modal_v1`、`legacy.qwen_download_v1`、`legacy.app`、`benchmarks.qwen_mem_benchmark`、`benchmarks.qwen_volume_cpu_benchmark`、`benchmarks.qwen_volume_gpu_benchmark`、`benchmarks.qwen_opt_experiment`。例如用 `uv run --locked python -m modal run -m legacy.app --help` 验证旧入口可加载。

## 稳定推理入口：可选 JIT 编译缓存

默认 --compiler-cache off，行为与此前一致；不会自动恢复或发布编译缓存。
需要复用已验证的 C2/12 编译缓存时，指定 --compiler-cache restore：

    uv run --locked python -m modal run -m qwen_modal_v2 --stage infer --cpu-cores 4 --ram-gib 80 --hicache-gb 8 --max-seconds 540 --budget-usd 1.5 --workload smoke --compiler-cache restore

该命令真实申请 Modal RTX PRO 6000 GPU 并产生费用，请仅在需要时执行。
缓存放在独立 Volume modal-forge-qwen38-compile-v2；恢复前核对模型 revision、容量 C2/12、HiCache、依赖版本、启动脚本指纹和 SHA-256。
缓存缺失或不兼容时返回错误，不会静默退回无缓存推理。稳定入口只读编译缓存，不负责新建或覆盖；模型权重 Volume 不变。
已有测试确认 TileLang 编译事件 3 → 0，但尚不能证明整体冷启动缩短。去掉 --compiler-cache restore 即可回退。

## 历史沿革

项目原名 `005-Default-GPU-Memory`，最初的 `legacy/app.py` 用于探测 T4、L4、L40S 等 GPU 的默认内存与硬件信息，无需模型，探测结果现写入 `results/default_gpu/results_<gpu>.json`。这一旧实验仍可用：

```powershell
# 会申请 Modal GPU 并产生费用；仅需复现时执行
uv run --locked python -m modal run -m legacy.app --gpu T4
```

历史 JSON、日志和实验 Markdown 中出现的旧绝对路径代表当时的环境，**作为原始证据保留，不等于现在的文件位置**。本次迁移没有重新下载权重、调整 Penny Royal 运行参数或修改 Modal Volume 数据。早期 `/proc/meminfo` / cgroup 可见内存不一定等于云平台保证的独占 RAM，Modal GPU/CPU/RAM 计费应按实际账单核对。

## Qwen3.8-Flash-Next 文档导航

当前项目同时保留稳定推理、硬件基准、JIT/C4/PLE 实验及历史版本。专题文档已按用途放入 `docs/`，以下链接以本 README 为基准。

| 类别 | 文档 | 内容与使用顺序 |
|---|---|---|
| 实验说明 | [QWEN_FLASH_NEXT_TEST](docs/experiments/QWEN_FLASH_NEXT_TEST.md) | 原始实验设计、模型缓存与启动说明；部分内容是历史版本，需结合后续报告 |
| 项目目录 | [PROJECT_LAYOUT_MIGRATION_20261104](docs/experiments/PROJECT_LAYOUT_MIGRATION_20261104.md) | 文件归类、模块迁移与验证记录 |
| 存储 | [QWEN_V2_VALIDATION](docs/storage/QWEN_V2_VALIDATION.md) | Volume v2 下载、文件完整性、运行验证 |
| 存储 | [QWEN_VOLUME_AB](docs/storage/QWEN_VOLUME_AB.md) | Volume v1/v2 独立代码与实验方案 |
| 存储 | [QWEN_VOLUME_AB_RESULTS](docs/storage/QWEN_VOLUME_AB_RESULTS.md) | v1/v2 文件读取、启动耗时、成本实测 |
| 硬件/IO | [QWEN_GPU_HARDWARE_SURVEY](docs/hardware-io/QWEN_GPU_HARDWARE_SURVEY.md) | T4、L40S、A100、RTX PRO 6000 的硬件采集，L4 容量不足 |
| 硬件/IO | [QWEN_MEMORY_IO_BENCHMARK_RESULTS](docs/hardware-io/QWEN_MEMORY_IO_BENCHMARK_RESULTS.md) | RAM 带宽、随机延迟、PCIe 与 Volume→CPU→GPU 数据 |
| 推理性能 | **[QWEN_REAL_INFERENCE_PROFILE_20261104](docs/inference/QWEN_REAL_INFERENCE_PROFILE_20261104.md)** | 首次真实 Qwen 性能基线（2026-11-04） |
| 优化设计 | **[QWEN_OPTIMIZATION_JIT_C4_PLE_DESIGN_20261104](docs/inference/QWEN_OPTIMIZATION_JIT_C4_PLE_DESIGN_20261104.md)** | 实验实施前设计与测试计划（已由下方实测报告验证） |
| **优化实测** | **[QWEN_OPTIMIZATION_JIT_C4_PLE_FINAL_20261104](docs/inference/QWEN_OPTIMIZATION_JIT_C4_PLE_FINAL_20261104.md)** | **最新 R1/R2/R3 全流程结论：跨容器缓存成功、C4 首批变慢、PLE Trace** |
| 详细对照 | [QWEN_OPTIMIZATION_RESULTS_20261104](docs/inference/QWEN_OPTIMIZATION_RESULTS_20261104.md) | 三轮 API Ready、TTFT、并发和费用自动汇总表 |
| 费用 | [QWEN_COST_ANALYSIS](docs/cost/QWEN_COST_ANALYSIS.md) | 历史 GPU/CPU/RAM 成本分析；最新单次账单见下方结果目录 |

**原始证据不搬家**：`results/` 中的 JSON、Penny Royal 原始 `.log.gz`、自动生成的 `PROFILE_REPORT_*.md` 保持和对应实验在一起，便于复核。最新三轮优化结果位于 `results/qwen_optimization/`，R1/R2/R3 各自保存原始 JSON、完整引擎日志和 billing.json；之前的真实推理基线仍位于 `results/qwen_flash_next_v2/`，自动明细报告与其 JSON 保持原位。

历次 Markdown 可含迁移前的命令和路径；优先使用本 README 的当前入口与 [目录迁移记录](docs/experiments/PROJECT_LAYOUT_MIGRATION_20261104.md)。
