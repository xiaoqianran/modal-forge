# 005 — Modal 默认 GPU 内存测试

最小测试项目：分别启动 T4、L4、L40S，不加载模型，不显式指定 `memory` 或 `cpu`。

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
uv sync
uv run modal run app.py --gpu T4
uv run modal run app.py --gpu L4
uv run modal run app.py --gpu L40S
```

也可以使用 `uv run modal run app.py` 按顺序测试全部 GPU；若某种 GPU 排队较久，建议单独测试以避免阻塞其他型号。

采集 `nvidia-smi`、`/proc/meminfo`、cgroup v1/v2 的内存限制与当前使用量，结果保存到 `results_<gpu>.json`。

**特别注意**：`/proc/meminfo` 以及 cgroup 内存上限可能反映宿主或容器的可见限制，不等于 Modal 为 Function 保证提供的独占 RAM，更不能推断实际按该内存容量收费。GPU、CPU 和系统内存依 Modal 计费规则分别计量。
