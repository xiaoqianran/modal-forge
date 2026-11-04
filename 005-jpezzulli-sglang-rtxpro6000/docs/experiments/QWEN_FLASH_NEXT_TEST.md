# Qwen3.8 Flash-Next：Modal 单卡与 Volume v2 模型缓存

本实验目录中的 \`app.py\` 和历史测试 JSON 保持不变。新的模型下载和加载沿用
\`modal-comfyui-caru-ini\` 中已实现的高速缓存架构，**只支持 Volume v2**，不保留
旧版 v1 加载、数据迁移或回退路径。

## 实现结构

- \`qwen_storage_v2.py\`：唯一的模型存储契约，创建 \`modal-forge-qwen38-flashnext-model-v2\`（\`version=2\`），检查完整权重索引和成功发布记录。
- \`qwen_download_v2.py\`：CPU-only 下载，HF revision 固定为真实 commit，16 GB 均衡分片、默认最多 8 个 CPU 下载容器、每容器 2 个文件下载线程，使用 Hugging Face 原生 \`hf_xet\`。
- \`qwen_modal_v2.py\`：单卡 GPU 推理、性能/成本记录及 PLE CPU 卸载；只挂载 \`/cache\` 的 v2 Volume，使用 \`/tmp/pennyroyal-model\` 的目录软链接加载经过验证的权重，**不在推理容器下载模型**。
- \`qwen_report.py\`：汇总历史/新增实验 JSON。
- \`test_qwen_cache.py\`：不访问 Modal 的分片、完整性与发布可见性回归测试。

## 模型缓存生命周期

1. CPU 下载器向 Hugging Face 查询完整文件清单、大小和 SHA256 / Git blob SHA1，并将 resolved commit 固定到 \`/cache/.qwen-model-pin.json\`；普通重试不会偷偷切换新版本。
2. 检查 Volume 中当前 revision 的缓存命中情况。将缺失文件按大小均衡分组到多个 CPU-only 容器，每个文件独立且稳定地存到 \`/cache/.download-staging/<revision>/...\`。完成文件能复用，损坏文件会重试。
3. 每个新下载文件都经过内容哈希检查。任何分片失败则停止发布，已下载的分片仍可恢复；不会生成成功标记。
4. 所有分片成功后，合并任务通过同一个 Volume 内的重命名/软链接发布到 HF 原生布局：\`/cache/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/blobs/\` 和 \`snapshots/<revision>/\`。
5. 先 \`commit()\` 完整权重，再发布并 \`commit()\` \`/cache/.qwen-model-ready.json\`；GPU 只接受后者指向的 snapshot。
6. GPU 端检查全部清单文件大小与 \`model.safetensors.index.json\` 的权重文件是否存在，随后创建软链接并交给 Penny Royal 启动，不需要额外复制整份 126.9 GiB 权重。

**约束：同一时间只启动一个完整模型下载任务。** 内部不同文件分片可并发，但不要同时执行两个 \`download\` 或 \`update\` 作业，以免同一缓存发生并行合并/覆盖。更新模型是显式 \`--update\` 操作。

## 命令（此轮仅更新代码，未执行下列云端命令）

在此目录运行：

\`\`\`powershell
# 检查 v2 缓存是否有完整已发布的模型；只使用 CPU。
uv run --locked python -m modal run -m qwen_download_v2 --stage check

# 首次 v2 下载；CPU 并行、断点续传、校验与发布，不使用 GPU。
uv run --locked python -m modal run -m qwen_download_v2 --stage download --shard-gb 16 --max-shards 8 --workers 2

# 只有要主动更新 HF 模型 commit 时才运行：
uv run --locked python -m modal run -m qwen_download_v2 --stage download --update

# 查看当前硬件（会产生少量 GPU 费用）。
uv run --locked python -m modal run -m qwen_modal_v2 --stage probe --budget-usd 1

# 真正执行 CPU PLE 卸载的单卡推理（会产生 GPU 费用）。
uv run --locked python -m modal run -m qwen_modal_v2 --stage infer --cpu-cores 4 --ram-gib 80 --hicache-gb 8 --max-seconds 540 --budget-usd 1.5

# 不运行任何云端任务的本地汇总/测试。
uv run --locked python -m benchmarks.qwen_report
uv run python -m unittest test_qwen_cache.py -v
\`\`\`

\`--budget-usd\` 是程序的启动前估算门槛，不是 Modal 平台账户硬性消费上限。账单应以平台实际 usage 为准；当运行期 CPU RAM 高于申请值时，预估费用可能偏低。

## 旧卷处理与历史结果

新版代码**彻底移除了**旧 v1 卷的引用和兼容分支，不提供迁移入口，也不会读取旧数据。新 v2 Volume 的首次运行必须重新下载权重（旧 v1 中下载的 126.9 GiB 文件不会自动出现）。

\`results/qwen_flash_next/\` 的 128 / 96 / 80 GiB 推理 JSON 是历史 v1 缓存下的有效测量记录，继续保留用于对比；它们不是 v2 新代码的已验证结果。旧项目专用 v1 Volume `modal-forge-qwen38-flashnext-model` 已在 2026-11-04 通过 Modal CLI 删除，且随后列表检查未再列出该卷。旧权重不可恢复；新的 v2 卷不复用旧数据。此次没有执行 GPU 推理、模型下载或 v2 部署。

## 当前已有实验基础（旧卷）

- RTX PRO 6000 Blackwell，单卡约 95.6 GiB 显存，原方案 128 GiB/8 核成功。
- 历史 96 GiB、80 GiB 与 80 GiB/4 核均通过短请求推理；训练和长时间高并发尚未验证。
- GPU 显存峰值约 81 GiB；CPU 内存加载峰值约 108 GiB，运行末段约 66–67 GiB。
- 历史预热后单条短请求约 319–338 tok/s；不能外推到长上下文或任意并发。
- 旧卷与新卷使用不同的存储后端；只有实际运行后才能比较新 Volume v2 的模型加载耗时。

## 离线验证

\`\`\`powershell
uv run --locked python -m compileall -q qwen_modal_v2.py qwen_download_v2.py qwen_core benchmarks legacy tests
uv run python -m unittest test_qwen_cache.py -v
\`\`\`
