# 2026-11-04 - yt-dlp cloud test, attempt 02

Video: https://www.youtube.com/watch?v=g7AE4szmZWU

## Local environment
- `modal[api-proxy-support]` installed
- Local tests: 8/8 passed
- Windows GBK console output failed once with Unicode checkmark; setting `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` fixed terminal output

## Remote attempts
1. Cloud run `ap-uujXkCdGbIslikt89u2q6b`: successfully initialized; Modal image build was started, but the run aborted because Secret `youtube-cookies` was absent from the `main` environment. Session elapsed approximately 23.7 seconds.
2. Unauthenticated metadata-only run `ap-ljRgj12gekp7LZts8LpE4h`: also initialized but aborted at application definition because the same required Secret was missing. Session elapsed approximately 31.9 seconds.

## Stage timings
| Stage | Observed result |
| --- | --- |
| PC2 to Modal API | Success (both runs initialized) |
| Remote image build | Started, completion not verified |
| Secret lookup | Failed: `youtube-cookies` absent in `main` |
| Container worker startup | Not reached |
| YouTube metadata extraction | Not reached |
| Video/audio download | Not reached |
| FFmpeg merge to MKV | Not reached |
| Volume commit | Not reached |

No confirmed downloaded video. Next action: configure a valid Cookie Secret in Modal environment `main`; then retry with UTF-8 terminal output and measure worker stages.
