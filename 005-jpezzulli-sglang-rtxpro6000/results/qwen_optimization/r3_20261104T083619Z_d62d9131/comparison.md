# R3 — C4/24，实际四路并发

- Modal App: `ap-h0cjfHhBlltfgkCCClPWLt`
- 真实 max_running_requests=4，引擎日志确认 `#running-req:4`；四请求均成功，GPU VRAM最大采样约80.88GiB
- C2双客户端总吞吐410.48tok/s，C4四客户端首批总吞吐**149.91tok/s**，耗时6.83s
- C4四条 `queue_duration` 均小于1ms，但 `initial_prefill_elapsed` 达5.15–5.34s；不是排队，不见C4期间新增TileLang编译；仅一批，不代表稳态
- 决策：默认生产保持C2/12；下一次必要时同一容器内重复C4热批，不盲目再启动付费GPU
- 实际 Modal 账单 $0.33900237
- 原始证据：同目录 `result.json`、`result.log.gz`、`billing.json`；总体结论见 `../../../docs/inference/QWEN_OPTIMIZATION_JIT_C4_PLE_FINAL_20261104.md`
