# 项目分类迁移记录（2026-11-04）

## 目的与范围

对 `005-jpezzulli-sglang-rtxpro6000` 进行**目录和导入路径整理**，不更改模型架构、GPU 配置、Penny Royal 镜像、推理参数或 Modal 模型 Volume。保留稳定运行入口，隔离历史版本与专项实验。

## 实际迁移

| 分类 | 新位置 | 文件 |
|---|---|---|
| 稳定入口 | 项目根目录 | `qwen_modal_v2.py`、`qwen_download_v2.py` |
| 运行共享模块 | `qwen_core/` | `storage.py`（原 `qwen_storage_v2.py`）、`hardware.py`（原 `qwen_hardware.py`）、`profile.py`（原 `qwen_profile.py`） |
| 专项测试与分析 | `benchmarks/` | 16 个文件：JIT 缓存、并发/PLE、RAM/PCIe、Volume v1/v2、硬件探针、报告与 `qwen_pointer_chase.c` |
| 旧版与原始探针 | `legacy/` | `app.py`、`qwen_modal_v1.py`、`qwen_download_v1.py`、`qwen_storage_v1.py` |
| 离线回归 | `tests/` | 四个原有 `test_qwen_*.py` |
| 旧 GPU 探测结果 | `results/default_gpu/` | `results_t4.json`、`results_l40s.json` |
| 原始实验数据 | `results/` | 原目录保持不变，不重写历史日志与 JSON |
| 文档 | `docs/` | 保留现有 experiments / storage / hardware-io / inference / cost 分类 |

**共迁移 29 个文件**，并新增四个包的 `__init__.py`。未重命名或覆盖原有实验的 JSON、日志和账单。

## 导入和 Modal 打包修复

- 稳定版：`qwen_core.storage`、`qwen_core.hardware`、`qwen_core.profile`。
- 历史 v1：`legacy.qwen_storage_v1`，保留原有 Volume v1 配置。
- 专项实验：`benchmarks.qwen_compiler_cache`、`benchmarks.qwen_opt_ple_profile`、`benchmarks.qwen_mem_bench_core`。
- Modal Image 现在通过 `.add_local_python_source("qwen_core")`、`.add_local_python_source("benchmarks")` 或 `.add_local_python_source("legacy")` 打包完整包。
- 已调整分析器和历史脚本的 `Path(__file__)` 相对路径，避免结果写入 `benchmarks/results` 或 `legacy/results`；原始 GPU 探针现在输出到 `results/default_gpu/`。
- C 语言微基准的 `.add_local_file()` 使用随脚本定位的绝对路径。
- 因入口移入 Python 包，采用 `python -m modal run -m 包.模块` 的调用方式；不要再用迁移前的根目录脚本路径调用实验与旧版入口。

## 离线验证命令

从项目根目录执行：

```powershell
uv run --locked python -m compileall -q qwen_modal_v2.py qwen_download_v2.py qwen_core benchmarks legacy tests
uv run --locked python -m unittest discover -s tests -p "test_*.py" -v

uv run --locked python -m modal run -m qwen_modal_v2 --help
uv run --locked python -m modal run -m qwen_download_v2 --help
uv run --locked python -m modal run -m benchmarks.qwen_opt_experiment --help
uv run --locked python -m modal run -m legacy.qwen_modal_v1 --help
```

以上 `--help` 不会执行 GPU 任务。实际执行 `--stage infer`、下载或内存基准需要单独确认预算。

## 完成后的验证结果

- 迁移后运行全部 **20 项**离线测试：原有 17 项 + 3 项针对目录结构的回归，全部通过。
- `compileall` 检查正常；常用稳定、实验、历史 Modal 入口的 `run -m ... --help` 均可加载，未申请任何 GPU。
- 文件移动前后 68 份原始结果逐一 SHA-256 校验一致，2 份早期探测 JSON 挪入 `results/default_gpu/` 后哈希一致。
- 之前改名遗留的 Windows `modal.exe` 启动器路径失效已修复：离线重装**相同版本** `modal==1.6.3`，`uv run modal --help` 已恢复；锁文件和依赖版本未变。
- README 中的 Markdown 路径、模块目录、离线验证命令已更新；保留实验原始数据中记录的旧绝对路径以便追溯。

## 数据校验

迁移前 `results/` 中 **68 个文件、13,583,894 字节**；按相对路径和 SHA-256 拼接的树摘要：

`83de48c4e2d0376aea45431f2c8429d462c6ff934fc5b1a84441b1dcf069dbca`

移动时已逐项重新计算，**68 个文件字节一致**。旧的 `results_t4.json` 和 `results_l40s.json` 也分别在新位置做了文件 SHA-256 对照。注意后来新添加的 `results/default_gpu/` 改变了整体 results 树结构，因此复核该基线时应排除 `results/default_gpu/`。

历史 Markdown、JSON 中写入的旧绝对路径保留为当时实验的元数据；若需要实际重新运行，以当前 README 和本记录为准。

## 边界

本次未执行付费 Modal GPU、没有重新下载模型、没有操作 Modal Volume，也没有清理或覆盖相邻项目的 Git 未提交修改。迁移后依赖锁文件 `uv.lock` 不变。