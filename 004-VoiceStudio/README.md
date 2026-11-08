# 004 — VoiceStudio on Modal

An independent Modal GPU deployment of the official [VoiceStudio](https://github.com/debpalash/VoiceStudio) CUDA Docker image. No ComfyUI integration or source fork is needed. The upstream project is AGPL-3.0; model licenses must be checked separately.

## Setup (Windows PowerShell)

Before deployment, create a Modal Secret named `modal-forge-004-voicestudio` containing a strong, unique `OMNIVOICE_API_KEY`. Do not commit the key to Git. The endpoint remains publicly reachable without Modal login, so protect administrative sessions and sensitive content.

```powershell
cd D:\a_programming_list\Ai-application\A-modal\modal-forge\004-VoiceStudio
$env:MODAL_GPU = "L40S"
uv run modal deploy app.py
```

Linux:

```bash
cd 004-VoiceStudio
MODAL_GPU=L40S uv run modal deploy app.py
```

This uses the upstream registry image `ghcr.io/debpalash/voicestudio:stable` and launches its `backend/docker_entrypoint.py` on port 3900. The shared Modal Volume `modal-forge` uses the dedicated subdirectory `004-VoiceStudio` (Modal storage path: `modal-forge/004-VoiceStudio`). That subdirectory is mounted as `/app/omnivoice_data` for voices, model cache and application data. A background commit every 60 seconds persists writes from the long-lived server (a recent write may be lost if the instance terminates without a final commit).

The HTTPS URL is public (no Modal login). VoiceStudio requires the API key supplied through the Modal Secret for administrative sessions, including model licence acceptance. The browser must create its own authenticated session; server-side health checks do not log a browser in. Anyone can reach the service, so stop the deployment after testing and do not upload confidential audio.

`min_containers=1` holds one running GPU container and incurs idle GPU charges; it does not guarantee every TTS engine remains loaded in VRAM. Set `MODAL_GPU` before deploying to change GPU. This repository only defines the deployment and does not download models or incur GPU charges until deployment.

## Model licence initialization

The server reports the default OmniVoice licence state on startup. A licence not yet accepted must be reviewed and accepted once in the VoiceStudio Model Catalogue. The record is saved in the mounted persistent data and reused across restarts; changed terms require a fresh acknowledgement. The script **does not fabricate acceptance**.

Query the live endpoint after deployment (use the deployed HTTPS URL):

```powershell
uv run python license_check.py --url https://YOUR-MODAL-URL
```

The helper exits with code 0 when accepted, 3 when acceptance is required, and 2 for connectivity errors. The startup checker runs separately and never blocks web service startup.

## Download models using parallel CPU containers

The downloader reads upstream `/app/backend/config/models.yaml` from the official Docker image. Exact Hugging Face files are split into balanced shards by file size (up to 16 parallel Modal CPU containers), with two transfer threads inside each container. Files are verified using upstream LFS SHA-256 or Git blob SHA-1, then published by one merge container. All tasks write to the shared Volume `modal-forge/004-VoiceStudio/huggingface` and commit their completed caches. It uses the existing HF cache for repeat runs.

```powershell
# Download all catalogue repositories by default (including MLX and gated entries)
uv run modal run download_models.py

# Inspect all catalogued HF repos and their approximate sizes without downloading
uv run modal run download_models.py --all --list

# Full file-size and hash verification (queries pinned HF metadata)
uv run modal run download_models.py --all --check

# Download remaining catalogued repositories, across 4 CPU containers
uv run modal run download_models.py --parallel 4 --workers 2

# Deploy GPU separately
uv run modal deploy app.py
```

**Important:** `--all` includes platform-specific MLX packages, gated repos, and models with restrictive licences; some may be unusable on L40S or require separate upstream access and acknowledgement. `--list` is a fast cache-presence scan; `--check` checks exact file sizes and hashes but requires upstream metadata. It does not prove runtime model compatibility. Download failures are reported per repository; reruns reuse cached files. This does not automatically accept model licences and does not install non-Hugging Face native engine bundles.
