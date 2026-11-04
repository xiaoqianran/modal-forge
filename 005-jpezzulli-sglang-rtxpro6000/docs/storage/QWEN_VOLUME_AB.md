# Qwen3.8 Flash-Next — Modal Volume v1 与 v2 受控对照

本目录维护两套独立的实验入口，不共享模型缓存目录或同一个云端 Volume。

| 对照项目 | v1 | v2 |
|---|---|---|
| 存储代码 | `qwen_storage_v1.py` | `qwen_storage_v2.py` |
| CPU 下载入口 | `qwen_download_v1.py` | `qwen_download_v2.py` |
| GPU 运行入口 | `qwen_modal_v1.py` | `qwen_modal_v2.py` |
| Volume 名称 | `modal-forge-qwen38-flashnext-model-v1-ab` | `modal-forge-qwen38-flashnext-model-v2` |
| Volume 版本 | `version=1` | `version=2` |
| 模型版本 | `7b719225242aacd3dbd3f9407468c2ee9a9d2594` | 同一 commit |
| 分片下载 | 16 GB × 最多 8 容器，每容器 2 线程 | 同参数 |
| GPU 资源 | RTX PRO 6000，4 CPU、80 GiB RAM、8 GB HiCache | 同参数 |
| GPU JSON 结果 | `results/qwen_flash_next_v1/` | `results/qwen_flash_next_v2/` |
| 读取实验 | `qwen_io_benchmark.py`（同一个脚本分别挂载 v1/v2） | 同左 |

## 命令

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

# 两套 CPU-only 下载，不启用 GPU
uv run --locked python -m modal run -m legacy.qwen_download_v1 --stage download --shard-gb 16 --max-shards 8 --workers 2
uv run --locked python -m modal run -m qwen_download_v2 --stage download --shard-gb 16 --max-shards 8 --workers 2

# 先检验模型已完整发布（避免从缺失模型的空盘启动 GPU）
uv run --locked python -m modal run -m legacy.qwen_download_v1 --stage check
uv run --locked python -m modal run -m qwen_download_v2 --stage check

# CPU-only 的真实 safetensors 顺序读取比较（各读 4GiB）
uv run --locked python -m modal run -m benchmarks.qwen_io_benchmark --read-gib 4 --repeats 1 --order v1-v2

# GPU 端相同设置下冷启动 + 生成测试，两个命令严格串行
uv run --locked python -m modal run -m legacy.qwen_modal_v1 --stage infer --cpu-cores 4 --ram-gib 80 --hicache-gb 8 --max-seconds 540 --budget-usd 1.5 --workload smoke
uv run --locked python -m modal run -m qwen_modal_v2 --stage infer --cpu-cores 4 --ram-gib 80 --hicache-gb 8 --max-seconds 540 --budget-usd 1.5 --workload smoke
```

每次 CUDA 测试均限制 540 秒，预算门槛只是预估，不是 Modal 账户硬性计费上限。建议固定同一个 GPU 类型、配置、代码版本、输入、上下文、并发数，并交替运行顺序重复测量至少两轮，避免将云宿主和缓存随机差异误判为 Volume 差异。

## 解释边界

- **下载速度**：相同并行方式、相同文件集时，才能合理比较 Volume 版本对多容器下载和持久化的影响；HF 网络、抢占等因素仍可影响结果。
- **顺序读取速度**：CPU-only 读 4GiB 文件，排除了 GPU 初始化，仍受 Linux 页缓存、网络和宿主影响。建议多次读且交换顺序。
- **服务就绪时间**：从推理函数开始到 API 就绪；包含读文件、CUDA 初始化、GPU 权重、PLE、Warmup。不是 Volume IO 时间。
- **测试结果**：先记录各次样本，再从中位数、范围和显著差异判断；不要从一次 240s/387s 推断 v2 必然慢。
- **存储成本**：两套模型权重各约 126.9GiB，测试期间双份持久存储都计费。完成对照后可按需求保留两卷或删除不再需要的一个。
- **历史结果**：`results/qwen_flash_next/` 为此前旧路径 JSON，保留不改；新 v1/v2 的结果存储在对应版本目录。

当前 v2 已有完整模型；v1 使用**独立新卷**下载。同一模型版本固定 SHA，保持可复现。
