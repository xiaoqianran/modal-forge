# YouTube 8 MiB HTTP chunk download — successful Modal test

- Date: 2026-11-04
- Video: https://www.youtube.com/watch?v=og3AR_xu6U8
- Title: 6.1《带上她的眼睛》刘慈欣 卡通版视频
- Modal run: https://modal.com/apps/seachenxyt/main/ap-CqhE60tEO8ZRyc8rKj6aeC
- Result: SUCCESS
- Mode: `--strategy chunked --fragments 1`, yt-dlp native HTTP with `http_chunk_size=8*1024*1024`
- Default application mode remains `native` (original behavior; no HTTP chunking)
- Authentication: current Modal `youtube-cookies` secret; successful authenticated extraction
- Output: only in Modal Volume; no PC transfer

## Transfer

| Stage | Worker cumulative timestamp | Isolated elapsed |
| --- | ---: | ---: |
| Cookie ready | 0.003 s | — |
| Metadata extracted | 4.028 s | — |
| First media transfer began | 9.009 s | — |
| Video finished | 30.674 s | 21.665 s from first progress |
| Audio finished | 32.029 s | 1.355 s |
| Download + merge done | 33.239 s | 1.210 s |
| Volume committed | 36.688 s | 3.449 s |
| Host API elapsed | 40.759 s | — |

- Video: 141,930,516 bytes (135.36 MiB), format 137, MP4, HTTPS
- Audio: 7,191,475 bytes (6.86 MiB), format 251, WebM, HTTPS
- Approx video speed: 6.10 MiB/s (yt-dlp)
- Audio speed: 5.07 MiB/s (yt-dlp)
- Final output container: MKV, without intended re-encoding
- Cloud path: `/data/006-yt-dlp-downloads/videos/3474f0dd3f3e4d7bb99cbb5cb1cb79b8/`
- Job ID: `3474f0dd3f3e4d7bb99cbb5cb1cb79b8`
- `modal volume ls` verified the MKV file and `manifest.json` both exist.

## Comparison with aria2c attempt (same video)

- aria2c 4 connections: video ~135.36 MiB in ~56 s, ~2.39 MiB/s; 6.8 MiB audio observed ~31–33 KiB/s and CN:1. Test aborted intentionally after excessive duration; no complete media artifact.
- yt-dlp 8 MiB chunked: video 21.67 s, audio 1.36 s; full result completed and committed in 36.69 s.
- Video transfer sped up about 2.58x compared with aria2c. This is not a full end-to-end comparison because the aria2 attempt was aborted.
- Interpretation: consistent with Google's documented throttling of HTTP responses >~10 MB; not a proven causal packet-level diagnosis.

## Production decision

The user explicitly requested restoring the previous default downloader; `native` remains the default. `chunked` remains an opt-in strategy with demonstrated improvement for this video. `aria2` also remains an opt-in benchmark strategy.

Reproduce:
```powershell
uv run --locked python -m modal run app.py --url "https://www.youtube.com/watch?v=og3AR_xu6U8" --download --strategy chunked --fragments 1
```
