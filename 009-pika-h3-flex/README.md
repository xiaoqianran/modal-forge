# 009 Pika H3 Flex · SGLang fixed workflow

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
