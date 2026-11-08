# Modal yt-dlp timing experiment - attempt 01

- Date: 2026-11-04
- Video: https://www.youtube.com/watch?v=g7AE4szmZWU
- Host: PC2 (Windows)
- Project: 006-yt-dlp
- Cloud Volume: modal-forge-006-yt-dlp-downloads
- Destination within Volume: modal-forge/006-yt-dlp-downloads/videos/
- Secret reference: youtube-cookies (existence not verified)
- Format policy: best video + best audio, merge MKV without re-encoding
- Command: uv run --locked python -m modal run app.py --url https://www.youtube.com/watch?v=g7AE4szmZWU --download

## Measured stages

| Stage | Duration | Result |
| --- | ---: | --- |
| Local unit tests | 8 passed | Passed |
| Modal CLI invocation + initial connection | 62.930 seconds | Failed |
| Modal image build | N/A | Not started |
| Modal worker cold start | N/A | Not started |
| YouTube metadata extraction | N/A | Not started |
| Video/audio transfer | N/A | Not started |
| FFmpeg merge | N/A | Not started |
| Volume publish and commit | N/A | Not started |

## Failure

Modal CLI returned: `Could not connect to the Modal server.`

The command failed before any remote worker execution or yt-dlp download. No downloaded video or verified Volume artifact was produced in this attempt.

Supplementary connection diagnosis: DNS resolution for `api.modal.com` succeeded, and a basic HTTPS request reached a server but returned HTTP 415. This does not establish that the authenticated Modal client API or its transport is healthy.

## Next action

Diagnose Modal CLI transport/account connectivity and retry. Do not infer Cookie or YouTube access failure from this attempt.
