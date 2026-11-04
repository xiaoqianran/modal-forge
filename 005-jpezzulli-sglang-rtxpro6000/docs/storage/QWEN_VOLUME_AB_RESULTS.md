# Volume v1 / v2：Qwen3.8 Flash-Next 同条件对照实测

测试日期：2026-11-04。项目：`005-Default-GPU-Memory`。

## 一、对照条件

- 固定模型：`RadixArk/Qwen3.8-Flash-Next-NVFP4`
- 固定 Hugging Face Commit：`7b719225242aacd3dbd3f9407468c2ee9a9d2594`
- 模型大小：135,253,622,894 字节（约 126.9 GiB），419 文件
- 推理框架：Penny Royal v3.1.5，单卡 RTX PRO 6000 Blackwell
- GPU 参数：`cpu_cores=4`、`ram_gib=80`、`hicache_gb=8`、`PENNY_PLE_BACKEND=ram`、`NIXL=off`、`workload=smoke`、`max_seconds=540`
- 下载参数：`shard_gb=16`、`max_shards=8`、`workers=2`、相同 SHA
- **唯一有意改变的主要变量：Modal Volume v1 或 v2。** 云端宿主、磁盘缓存和网络状况无法固定。

| 版本 | 独立代码 | 云端卷名 | 持久化模型 |
|---|---|---|---|
| v1 | `qwen_{storage,download,modal}_v1.py` | `modal-forge-qwen38-flashnext-model-v1-ab` | 419 文件，ready=true |
| v2 | `qwen_{storage,download,modal}_v2.py` | `modal-forge-qwen38-flashnext-model-v2` | 419 文件，ready=true |

## 二、4 GiB safetensors 顺序读取（CPU-only）

单个相同模型权重文件 `model-bf16-00011.safetensors`；每次各读 4 GiB；同为 4 CPU 核、8 GiB RAM；测试顺序两轮交替。

| 重复 | v1 (MiB/s) | v2 (MiB/s) |
|---|---:|---:|
| 第 1 次：v1→v2 | 1144.47 | 816.74 |
| 第 2 次：v2→v1 | 1485.43 | 1031.02 |
| 第 3 次：v2→v1 | 1623.53 | 1490.39 |
| **均值** | **1417.81** | **1112.72** |
| 中位数 | 1485.43 | 1031.02 |

**观察：v1 在这三组顺序读取样本中均较快，均值约高 27.4%。** 但样本量小、均使用同一个文件，可能存在远程宿主和页缓存效应；既不代表所有文件/随机读取，也不是全模型 GPU 加载吞吐。

原始结果：
- `results/qwen_volume_ab/io_20261104T054806Z.json`
- `results/qwen_volume_ab/io_20261104T054906Z.json`

## 三、完整模型 GPU 冷启动

| 指标 | v1 | v2 |
|---|---:|---:|
| API 就绪时间 (startup_s) | **286.71s** | 327.11s |
| Function 内总耗时 | 306.84s | 348.53s |
| GPU VRAM 峰值 | 80.883 GiB | 80.884 GiB |
| CPU RAM 峰值 | 107.756 GiB | 107.753 GiB |
| 预热后第 2 个短请求速度 | 339.39 tok/s | 361.50 tok/s |
| 实际 API 回答正确 | 是 | 是 |
| 实际 GPU+CPU+内存账单 | **$0.33355** | $0.37780 |

本轮 **v1 服务就绪比 v2 早 40.40 秒**；以 v1 为分母，v2 启动慢约 14.1%。考虑只有各一次完整同条件冷启动，结果仍不足以确认 Volume 版本为唯一原因。

v2 日志明确记录：`Load weight end` 主模型 168.98 秒、MTP 11.94 秒，`Engine startup timings: load_weight=180.92s`；v1 日志早期因采集上限被多线程进度行占满，没有完整的权重加载结束事件，因此**无法得出 v1 与 v2 的精确权重加载耗时差**。

实验记录：
- v1：`results/qwen_flash_next_v1/infer_80g_20261104T055457Z.json`，Modal `ap-K11scXrzBjHFYaiVFHFLcb`
- v2：`results/qwen_flash_next_v2/infer_80g_20261104T060132Z.json`，Modal `ap-3rus4Vm9UZ6aHLRSOBjTZu`

## 四、模型下载及真实计费

v1 首轮采用同一个分片下载器，但一个 Hugging Face Xet/CAS 文件重建出现 I/O 错误导致全量发布中止。第二轮复用 418 个已下载文件，只补齐 1 个文件并最终发布。

| 下载情况 | v1 | v2 |
|---|---:|---:|
| 首轮下载 | 约 417.7s，因单分片失败终止 | **260.2s，成功** |
| v1 故障恢复 | 再用 318.55s，最终成功 | 不适用 |
| 同 SHA、文件数、字节数 | 相同 | 相同 |
| 首次运行 + 恢复的账单 | **$0.22536** | **$0.18806** |

**这不是纯粹的 Volume 写入速度对照**：v1 的网络 CAS 错误和恢复哈希校验显著影响时长。v1 完成后分片可复用，说明容错有效。下载器对两版均已补充文件级异常重试、损坏文件校验和可恢复发布。

Modal 账单（2026-11-04，按 App ID 筛选）：
- v1 下载失败：`ap-6CL9Mj4xXYS5lcu5ofM7pH`，约 $0.19954
- v1 下载恢复：`ap-Nc0Z4YMrfboafjnD7KfKwG`，约 $0.02581
- v2 首次下载：`ap-86cS1umKd0GHKvP78bAQpz`，约 $0.18806
- v1 GPU：`ap-K11scXrzBjHFYaiVFHFLcb`，约 $0.33355
- v2 GPU：`ap-3rus4Vm9UZ6aHLRSOBjTZu`，约 $0.37780
- CPU-only 顺序读实验：$0.00155 + $0.00255

## 五、初步判断与下一步建议

这次结果不支持“v2 一定能加速 GPU 模型加载”：样本中 v1 读取与启动更快。不过**不能只凭这一轮宣布 v1 在所有场景优于 v2**。v2 仍具有更适合大量文件及多写入者的设计优势；我们的 v2 下载一次成功并完成模型验证。

建议**同时保留两套代码和两份模型 Volume**，未来可按相同输入重复 2–3 轮 GPU 冷启动、交换 v1/v2 测试顺序，并从启动日志中分离 `load_weight`、PLE、Warmup 阶段。当前只有 v2 的完整 `load_weight=180.92s`；没有完成受控的 GPU 权重加载耗时分解。没有充分证据应立即删除任意一套 Volume。

报告来源：本地 JSON、Modal Billing Report；所有账单数据取自当前工作区按资源拆分的实际费用，后续平台结算可能修订。
