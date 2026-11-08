# yt-dlp Modal cloud benchmark — successful run

Date: 2026-11-04
Video ID: `g7AE4szmZWU`
URL: https://www.youtube.com/watch?v=g7AE4szmZWU
Modal run: https://modal.com/apps/seachenxyt/main/ap-8n64N26mofnYNRGfFhwDtb
Job ID: `8748ecf7da644a1884d7cd8fae692b41`
Result: **success**
Cloud-only download: **yes** (no Windows transfer)

## Destination
- Volume: `modal-forge-006-yt-dlp-downloads`
- Mount: `/data`
- Directory in Volume: `modal-forge/006-yt-dlp-downloads/videos/8748ecf7da644a1884d7cd8fae692b41/`
- Media: `+_+_1_50 [g7AE4szmZWU].mkv`
- Manifest: `manifest.json`
- Verified using `modal volume ls`: both media and manifest present.

## Timings

| Measurement | Time |
| --- | ---: |
| Entire client session (including image construction and app lifecycle) | 226.193 s |
| Local host entrypoint remote call elapsed | 167.910 s |
| Worker start (relative to worker entry) | 0.003 s |
| Cookie loaded | 0.005 s |
| Video metadata ready | 4.761 s |
| Video stream download started | 6.090 s |
| Video stream fully downloaded | 131.514 s |
| Audio stream fully downloaded | 143.680 s |
| Download and merge completed | 156.536 s |
| Volume committed | 162.566 s |

Note: Worker timing values are cumulative timestamps, not individual durations. Modal CLI full session and host-entrypoint timings use different start points and should not be subtracted to infer an exact isolated image-build duration.

## Media transfer
- Video stream: 841.26 MiB, 00:02:06, yt-dlp-reported average ~6.67 MiB/s
- Audio stream: 92.02 MiB, 00:00:12, yt-dlp-reported average ~7.57 MiB/s
- Combined stream bytes (before remux): 933.28 MiB
- Final container: MKV, without intentional re-encoding

## Environment
- `modal[api-proxy-support]` in host project environment
- UTF-8 forced on Windows for Modal CLI output
- Modal secret: `youtube-cookies` (values not logged)
- Python image: Debian slim + ffmpeg + Deno + yt-dlp 2026.10.26 + yt-dlp-ejs 0.8.0
- CPU: 2, no GPU requested

## Observations
- First run required image building, including apt packages; cached reruns should be measured separately.
- YouTube emitted a warning about some web_embedded formats lacking URLs, but extraction and download succeeded.
- The complete media and manifest were verified as present in the cloud Volume.
- No proof of a full codec-level integrity scan has been gathered; result is based on yt-dlp/FFmpeg success and cloud files existence.

## Suggested next benchmark
Repeat same URL with image cache warm and record total time, transfer time, and Volume commit latency. Distinguish repeated download jobs (job IDs differ) from cache reuse.
