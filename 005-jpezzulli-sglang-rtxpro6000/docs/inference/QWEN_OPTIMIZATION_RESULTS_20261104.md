# Qwen3.8-Flash-Next 编译缓存 / 真实并发 / PLE 实测对照

生成 UTC：2026-11-04T08:40:26.475379+00:00

**提醒：** 单次不同容器不是严格的同宿主 A/B。启动时间与权重加载受 Volume 缓存、CPU 平台和内核缓存影响。任何对比都需要结合 JIT 命中证据，不能把所有改进归功于缓存。

| 指标 | 历史基线 | R1 写缓存 | R2 读缓存 | R3 C4 |
|---|---:|---:|---:|---:|
| API ready / s | 312.66 | 252.08 | 273.78 | 267.04 |
| Traffic ready / s | — | 277.39 | 288.65 | 292.10 |
| First useful answer / s | — | 278.29 | 289.49 | 293.11 |
| weight load / s | 116.98 | 106.24 | 145.63 | 104.16 |
| TileLang compile 次数 | — | 3.00 | 0.00 | 3.00 |
| 8K 目标预热 TTFT / s | — | 7.17 | 0.83 | 6.94 |
| 8K 正式 TTFT / s | 7.56 | 0.57 | 0.59 | 0.58 |
| 32K 正式 TTFT / s | 2.68 | 2.23 | 2.26 | 2.25 |
| C2 聚合 tok/s | 397.35 | 401.62 | 377.19 | 410.48 |
| C4 客户端聚合 tok/s | 397.29 | 411.75 | 395.54 | 149.91 |
| 引擎实际运行并发上限 | — | 2.00 | 2.00 | 4.00 |
| 缓存恢复 / s | — | — | 1.75 | — |
| 缓存发布 / s | — | 1.22 | — | — |
| Modal 实际账单 / USD | — | 0.32 | 0.34 | 0.34 |

## 本轮重要证据

- **historic**: success=True, JIT=None, cache=None, PLE profile=None, raw=D:\a_programming_list\Ai-application\A-modal\modal-forge\005-Default-GPU-Memory\results\qwen_flash_next_v2
- **r1**: success=True, JIT=3, cache=a0ad50b34806e2cb25cca621f8f33907aa472fdba75b03d4514f80dd127e2243, PLE profile=None, raw=D:\a_programming_list\Ai-application\A-modal\modal-forge\005-Default-GPU-Memory\results\qwen_optimization\r1_20261104T082240Z_809854cf
- **r2**: success=True, JIT=0, cache=a0ad50b34806e2cb25cca621f8f33907aa472fdba75b03d4514f80dd127e2243, PLE profile=published, raw=D:\a_programming_list\Ai-application\A-modal\modal-forge\005-Default-GPU-Memory\results\qwen_optimization\r2_20261104T082939Z_e8cd0b30
- **r3**: success=True, JIT=3, cache=19c76c78cd6929ada208e3610c00f61608e8203a8837950c38716ce20efb0c1b, PLE profile=None, raw=D:\a_programming_list\Ai-application\A-modal\modal-forge\005-Default-GPU-Memory\results\qwen_optimization\r3_20261104T083619Z_d62d9131

## 如何判定

- 编译缓存跨容器复用必须同时满足 R2 SHA 校验恢复成功、真实 TileLang compile 行数下降，才可以说缓存复用成功。
- 对端到端性能应比较 API Ready、Traffic Ready、首次正式请求总完成，而不只是正式 8K TTFT（预热可能只是提前花费时间）。
- 只有 SGLang 日志确认 #running-req >=4，才能认定 R3 真正四路同时运行。
- profiler trace 若生成，仅用于定位 PLE gather 核心路径；Profiler 模式吞吐不与普通请求直接比较。
