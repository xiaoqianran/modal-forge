# R2 — C2/12，跨容器恢复编译缓存

- Modal App: `ap-kGTCTgnUA59KfyQON2c1BF`
- 恢复 SHA/manifest 校验通过：1,277文件，恢复1.748s；TileLang 编译事件 **0 次**
- 8K 预热 TTFT **0.826s**，正式8K TTFT0.589s；API ready273.78s，Traffic ready288.65s
- 权重加载145.63s较R1的106.24s慢；无法证明整体冷启动加速
- SGLang 12-step trace 原始卷及本地压缩归档存在，真实 PLE gather kernel 12次约0.189ms（非关键路径等待）
- 实际 Modal 账单 $0.34474059
- 原始证据：同目录 `result.json`、`result.log.gz`、`billing.json`；Trace见 `../traces/`；总体结论见 `../../../docs/inference/QWEN_OPTIMIZATION_JIT_C4_PLE_FINAL_20261104.md`
