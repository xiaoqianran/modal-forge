# 009 Pika H3 Flex · SGLang fixed workflow

## Mandatory separate model download (CPU only)

Model download and GPU inference are now **separate commands**. Both HTTP
service (`app.py`) and batch mode (`run_batch.py`) require a completed
CPU download. They use the same `modal-forge` Volume.

First run (or whenever updating weights):

    uv run modal run download_model.py

CPU downloads the full `Pika-Labs/Pika-H3-Flex` repository to
`/009-pika-h3-flex/hub` inside `modal-forge`, checks that weight files
exist and writes `/009-pika-h3-flex/model-ready.json` only after completion.
The GPU reads that marker and passes an **absolute local snapshot path** to
SGLang. `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` prevent automatic
Hugging Face downloads in inference. A missing or invalid marker causes an
immediate error rather than a fallback download on GPU.

Then run inference:

    uv run modal run run_batch.py --workflow workflow_t2va.json --task tasks/t2va_demo.json

Alternatively, deploy the HTTP service:

    uv run modal deploy app.py

Downloading is not automatically triggered by either inference entrypoint.
Running the CPU download again uses Hugging Face caching to avoid re-fetching
unchanged files. The GPU still needs to load model weights into VRAM at startup.
Do not update weights while an inference process is using them.

Pika-H3-Flex native six-step stochastic re-noising; both T2VA (text-to-video-and-audio) and FL2VA (first+last frames + prompt) share one FL2VA model partition.

## System

- app.py: Modal RTX PRO 6000 (96GB), SGLang speed mode, bf16-base architecture; no explicit quantization or CPU-offload.
- proxy.py: public port 30011, waits for SGLang health on internal port 30010, stages inline frame bytes in the SAME running container and translates them into official keyframe conditions.
- workflow_t2va.json / workflow_fl2va.json: fixed video parameters (5 seconds, 480p short edge, six steps).
- tasks/*.json: prompt lists. FL2VA items have first_frame + last_frame relative to this module directory.
- batch_run.py: run every item, resume completed and unchanged MP4s, download files, save run JSONs.
- generate.py: legacy single-request client, for low-level testing; does not upload local images.

## Deploy

    cd 009-pika-h3-flex
    uv sync
    uv run modal deploy app.py

Service: modal-forge-009-pika-h3-flex-fl2va
Default GPU: RTX-PRO-6000; min_containers=0, max_containers=1, scaledown_window=2.
Modal Proxy Auth is disabled; the endpoint is publicly accessible and does not need tokens.
Weights cache in existing modal-forge Volume, /009-pika-h3-flex subpath.

## Batch generation (Windows PowerShell)

    $url = "https://yuqueaaa--modal-forge-009-pika-h3-flex-fl2va-serve.us-east.modal.run"

    uv run python batch_run.py --endpoint $url --workflow workflow_t2va.json --task tasks/t2va_demo.json
    uv run python batch_run.py --endpoint $url --workflow workflow_fl2va.json --task tasks/fl2va_demo.json

To generate 10 clips, add 10 entries to the task JSON. All fixed video parameters remain in the workflow JSON.

FL2VA mode uses two images with frame_index=0 and -1, role=keyframe. The local client base64-encodes PNG/JPEG/WebP images into ONE video submission; the HTTP gateway saves them to per-container /tmp, translates to file:// URI and forwards the request to internal SGLang. No public image host, R2, or extra upload call is needed.

Output: results/<mode>/<task name>/<id>.mp4, <id>.json, report.json. Completed jobs are skipped ONLY when prompt, workflow, seed, model, frames and MP4 checksum still match. Changed inputs regenerate output, failures write <id>.error.json. Start with one GPU container and serial requests to avoid duplicate GPU loading.

Important: the SGLang video job registry lives in the GPU container. Very short idle scale-down (2 seconds) may interrupt a gap between polling calls, so the client polls every second. If a GPU container is interrupted anyway, rerun the task; already saved MP4 files are skipped.

Do not use MiniMax-H3 original Euler sampler or force flow_shift; Pika model requires its trained six-step schedule.

## Verification and limits

SGLang official reference:
https://github.com/sgl-project/sglang/blob/main/docs/cookbook/diffusion/MiniMax/MiniMax-H3.mdx

The batch format and local tests are not proof of actual successful GPU model inference. Full GPU model loading, VRAM peak, and MP4 validation must be separately checked.

The API is public with no authentication. Anyone who knows the URL may trigger GPU inference and incur cost. Keep the endpoint confidential or add access control when needed.

## Modal run (recommended batch entrypoint, without deployment)

Compatibility fix (2026-11-08): The original `lmsysorg/sglang:v0.5.23` language-model CLI rejected Pika-specific Diffusion arguments. Both inference entrypoints use `lmsysorg/sglang:dev` and the Diffusion CLI with `--model-path` set to the downloaded local snapshot. The default FL2VA partition handles both T2VA and FL2VA. To verify the Diffusion runtime and Pika model registry without allocating a GPU, run `uv run modal run run_batch.py --preflight`. The dev Docker tag is mutable and should be pinned to a stable compatible release when available.


run_batch.py is independent from app.py. Each invocation starts one Modal GPU container, loads Pika H3 Flex only once, sequentially generates videos, then exits. No HTTP URL or Proxy Token required. app.py stays available as an optional HTTP service.

Both entrypoints reuse the SAME "modal-forge" Volume checkpoint cache subdirectory "009-pika-h3-flex". Cached checkpoint files survive container shutdown, but GPU-loaded weights do not.

PowerShell:

    cd D:\a_programming_list\Ai-application\A-modal\modal-forge\009-pika-h3-flex
    uv run modal run run_batch.py --workflow workflow_t2va.json --task tasks/t2va_demo.json
    uv run modal run run_batch.py --workflow workflow_fl2va.json --task tasks/fl2va_demo.json

To run ONLY the first item:

    uv run modal run run_batch.py --workflow workflow_fl2va.json --task tasks/fl2va_demo.json --limit 1

Images may use paths relative to this module or absolute paths. Images are uploaded once to the existing Volume rather than passed as Base64 Modal arguments. The GPU uses those images as first/last keyframes through file:// conditions. This path uses six Pika steps, SGLang performance=speed and no explicit quantization or CPU Offload.

Results: results/<mode>/<task name>/<run id>/*.mp4, *.json, report.json.
Cloud: 009-pika-batch/<mode>/<task name>/<run id>/ in the Volume.
After every completed video the cloud output is committed. Use the SAME --run-id on subsequent invocations to resume. Matching videos and hashes are skipped; changed prompts, frames or workflow regenerate. Failures stop the batch without starting further items.

Offline tests (no GPU):

    uv run python -m unittest discover -s tests -v
