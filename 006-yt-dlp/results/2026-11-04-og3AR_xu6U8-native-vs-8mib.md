# yt-dlp 原版 vs 强制 8 MiB 分块：同视频实测

日期：2026-11-04
视频：https://www.youtube.com/watch?v=og3AR_xu6U8
标题：6.1《带上她的眼睛》刘慈欣 卡通版视频
环境：PC2 发起 Modal 云端执行；Secret 为已有 `youtube-cookies`；不把媒体下载到 Windows。
可用格式一致：视频 137（141,930,516 字节，135.36 MiB，MP4，HTTPS），音频 251（7,191,475 字节，6.86 MiB，WebM，HTTPS）。完成后均无意进行视频重编码，最终为 MKV。

## 四次真实下载结果

| 执行顺序 | 策略 | 视频流耗时（秒） | 音频流耗时（秒） | Worker 完整耗时（秒） | PC2 入口 remote 耗时（秒） | Job ID |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | 原生 yt-dlp，显式 8 MiB 分块 | 21.665 | 1.355 | 36.688 | 40.759 | `3474f0dd3f3e4d7bb99cbb5cb1cb79b8` |
| 2 | 原版 yt-dlp（不覆盖分块） | 2.751 | 0.197 | 16.487 | 20.987 | `1b22dac431884d659d583f481458fc74` |
| 3 | 原生 yt-dlp，显式 8 MiB 分块 | 10.800 | 0.483 | 25.678 | 29.637 | `27528be7121540f1a57cd2b2141591d5` |
| 4 | 原版 yt-dlp（不覆盖分块） | 4.559 | 0.543 | 24.954 | 30.114 | `274260c85efe4d37afb2004302169074` |

> 视频耗时从首次出现下载进度至第一条媒体流完成；音频耗时从视频流完成至音频流完成。
> Worker 完整耗时从 Worker 函数开始至 Volume.commit() 返回。PC2 入口时间不包含整个 Modal CLI 会话的其他启动/清理开销。

- 原版 Worker 平均：20.7205 秒（两次）；强制 8 MiB 平均：31.183 秒（两次）。
- 原版 Worker 平均耗时降低约 33.6%；两次都比配对的 8 MiB 结果短。
- 原版视频流平均约 3.655 秒；强制 8 MiB 视频流平均约 16.233 秒。注意 CDN/路由/缓存的变化，不能把比值归结为某一个单一参数。
- 之前同视频 aria2c 四连接：视频 135.36 MiB 约 56 秒，音频出现约 31–33 KiB/s 的异常低速，测试中止，不能计入完成任务的速度平均值。

## Modal 证据与持久化

1. 强制 8 MiB 第一次：[Modal run](https://modal.com/apps/seachenxyt/main/ap-CqhE60tEO8ZRyc8rKj6aeC)
2. 原版第一次：[Modal run](https://modal.com/apps/seachenxyt/main/ap-q5WcYpHURxm4iM3tX5jyEt)
3. 强制 8 MiB 第二次：[Modal run](https://modal.com/apps/seachenxyt/main/ap-apvFhc29WLTzIZksNPmipC)
4. 原版第二次：[Modal run](https://modal.com/apps/seachenxyt/main/ap-euCFcIWlkcWaFXEOumT0vp)

通过 `modal volume ls` 复核原版第二次、分块第二次目录：`manifest.json` 和 `6.1 [og3AR_xu6U8].mkv` 均存在；原版第一次、分块第一次此前也已验证。

## 结论：默认保持原版 native

- 下载默认：`strategy=native`，`fragments=1`；保留 `chunked` / `aria2` 作为显式测试模式。
- 原版没有手工设置 `http_chunk_size`，不代表 yt-dlp / YouTube 提取器内部没有自己的 HTTP 分块处理；不能将原版表述为“禁止所有分块”。
- 不能由两次样本保证其它视频、其它区域、其它 CDN 或时间段均同样排序。
- 元数据探测仍匿名优先，在明确登录要求时自动使用 Cookie；正式下载使用 Secret 中 Cookie。

默认运行：
```powershell
uv run --locked python -m modal run app.py --url "https://www.youtube.com/watch?v=og3AR_xu6U8" --download
```

显式 8 MiB 对照：
```powershell
uv run --locked python -m modal run app.py --url "https://www.youtube.com/watch?v=og3AR_xu6U8" --download --strategy chunked --fragments 1
```
