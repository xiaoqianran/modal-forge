# 006-yt-dlp：并发下载第一轮实测（认证阻断）

- 日期：2026-11-04
- 视频 ID：`g7AE4szmZWU`
- Modal 运行：https://modal.com/apps/seachenxyt/main/ap-NmsLwCewJOM7iNdpNUYs6D
- 测试策略：`chunked`，8 MiB HTTP 分块，DASH/HLS 最多 4 分片并发
- 状态：**未进入媒体下载，不能得出下载速度结论**

## 已确认

1. 本地 `uv run --locked python -m unittest -v test_app`：13/13 通过。
2. 本地使用真实 yt-dlp 分派器进行离线验证：HTTPS → `Aria2cFD`（`aria2` 策略）；DASH → `DashSegmentsFD`；HLS → `HlsFD`。
3. Modal 已完成加入 aria2 的镜像构建并启动远程 Worker。
4. 元数据提取期间 yt-dlp 提示 Cookie 已轮换/失效，随后 YouTube 返回 `Sign in to confirm you're not a bot`。
5. 失败发生在媒体传输之前；无新视频文件和有效吞吐量样本。原始基线仍为 841.26 MiB 视频约 126 秒，总 Worker 162.57 秒。

## 测试策略及风险

- `native`：默认 HTTP 下载，用于基线。
- `chunked`：原生 8 MiB HTTP 请求，顺序执行；若媒体协议非 HTTP，设置可能不生效。
- `aria2`：普通 HTTP(S) 最多 4 连接；DASH/HLS 保留 yt-dlp 原生分片下载。
- **不能把 aria2 的 `--min-split-size=4M` 误读成最大单请求 4 MiB**；四路下载大范围媒体仍可能触发 YouTube 对大 Range 的限速。
- 遇到机器人验证后暂停自动重试；先恢复正常的账户访问和 Cookie 有效性。无任何策略保证零风控。

## 认证恢复后的对照顺序

1. 先完成一次合法、低频率的元数据检查，确认没有验证阻断。
2. 对同一视频按顺序测 `chunked`（8 MiB）和 `aria2`（先 2 连接，再视成功与稳定性测 4 连接）；保持分辨率/格式、云端区域一致。
3. 记录每次选中格式协议、视频/音频各自时间、合并时间、Volume 提交时间、403/429 及重试次数。
4. 不并行启动多个完整任务，不在 403、429 或机器人验证后持续加大并发。

## 说明

此次失败不能用于推断 `chunked` 的速度；尚未实际运行 aria2 的 YouTube 媒体下载。账号 Cookie 属于敏感凭据，报告与代码中不记录其内容。
