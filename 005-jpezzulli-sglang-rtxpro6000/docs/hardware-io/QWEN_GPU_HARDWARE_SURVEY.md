# Modal 五种 GPU 的 CPU / NUMA / 硬件信息轻量探针

时间：2026-11-04。项目：005-Default-GPU-Memory，PC2。

## 固定自动记录

已新增 `qwen_hardware.py` 的 `capture_hardware()`，在 `qwen_modal_v1.py`、`qwen_modal_v2.py` 的 `_machine()` 的运行前采样里自动执行以下四项：

```bash
lscpu
numactl --hardware
nvidia-smi -q
cat /proc/cpuinfo
```

每项记录完整 stdout、stderr、exit_code、截断标记，保存在推理 JSON 的 `before.hardware_commands.commands`。运行结束时的 `after` 只采原来的轻量指标，不会再次保存整个大文本。

`qwen_gpu_hardware_survey.py` 独立轻量探针采用 Debian Slim + util-linux + numactl，**每 GPU 只请求 1 CPU / 1024 MiB RAM**、无模型、无 GPU 计算或内存压力；产出 `results/gpu_hardware/` 的单独 JSON。L4 容量不足则不创建虚假的测试结果。

## 实测记录

| GPU 请求 | 实际 GPU | CPU Vendor | Family / Model | NUMA 显示 | 四条命令执行 | 结果 |
|---|---|---|---|---|---|---|
| T4 | Tesla T4 | GenuineIntel | 6 / 85 | 1 个可见节点 | 4/4 exit=0 | 成功 |
| L4 | — | — | — | — | 未获得容器 | Modal GPU_L4 worker 无容量，两次排队后停止 |
| L40S | NVIDIA L40S | AuthenticAMD | 25 / 1 | 1 个可见节点 | 4/4 exit=0 | 成功 |
| A100 | NVIDIA A100-SXM4-40GB | GenuineIntel | 6 / 85 | 1 个可见节点 | 4/4 exit=0 | 成功 |
| RTX PRO 6000 | NVIDIA RTX PRO 6000 Blackwell Server Edition | AuthenticAMD | 26 / 2 | 1 个可见节点 | 4/4 exit=0 | 成功 |

四种成功实例的 `CPU model name` 均为 `unknown`，`numactl` 没有暴露每节点实际内存容量。因此**本次没有直接读取 DDR4 / DDR5 型号和速率的硬件证据**。

基于 AMD 官方 EPYC 识别文档，family 25/model 1 符合 3rd Gen EPYC Milan（Zen3）范围；family 26/model 2 符合 5th Gen EPYC Turin（Zen5）范围。按已知平台规格，Milan 以 DDR4 为主、Turin 采用 DDR5，因此 L40S 更可能 DDR4、RTX PRO 6000 更可能 DDR5，属于**推断**，不是 Modal 官方保证。T4/A100 family 6/model 85 可与 Skylake/Cascade Lake 服务器代际相符，也更可能 DDR4，但虚拟化 CPU ID 可能不是宿主精确型号。

## 数据文件

- `results/gpu_hardware/t4_20261104T061638Z.json`
- `results/gpu_hardware/a100_20261104T062007Z.json`
- `results/gpu_hardware/rtx_pro_6000_20261104T062019Z.json`
- `results/gpu_hardware/l40s_20261104T062048Z.json`
- `results/gpu_hardware/l4_capacity_unavailable_20261104.json`

每个成功 JSON 保存各四条命令的原始输出和参数，包含 CPU flags、NUMA、PCIe/GPU 详细信息。L4 的失败记录只说明云端容量缺失，不能用于比较 DDR。

## 费用与约束

实际 Modal Billing Report 中已出现的本次消费（可能尚未包含所有未结算时间段）：
- 首次 T4 + 等待 L4 的 App `ap-g6WgZrC3MT6LbVsHeNntl7`：约 $0.00611，其中 T4 约 $0.00557。
- A100 App `ap-ma78DSsXhEKwYaQDmIocsl`：约 $0.00120。
- L40S / RTX PRO 6000 的资源账单当时未全部出现，不可把上述两项加总当作最终完整费用。

探针端到端时间包括 GPU 调度等候和镜像启动，**不是运行时硬件性能指标**。无模型权重下载、无推理，已停止 L4 等候应用避免无限排队。

## 参考

- AMD 官方 EPYC CPUID 识别：https://docs.amd.com/r/en-US/57404-AOCL-user-guide/24.1.1.-On-Linux
- Modal GPU 型号：https://modal.com/docs/guide/gpu
