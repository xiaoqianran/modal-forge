# 009 Pika H3 Flex — SGLang Diffusion

This module serves the Pika-Labs/Pika-H3-Flex model with its native SIX-STEP stochastic re-noising sampler (not generic MiniMax-H3 6-step Euler).

Official guide:
https://github.com/sgl-project/sglang/blob/main/docs/cookbook/diffusion/MiniMax/MiniMax-H3.mdx

## Deploy

Default GPU RTX PRO 6000 96GB. Explicitly uses --performance-mode speed (resident components); no CPU offload or explicit quantization flags are enabled. Actual peak VRAM usage has not yet been measured.
Official SGLang image: lmsysorg/sglang:v0.5.23.
Modal settings: min_containers=0, max_containers=1, scaledown_window=2.
HF model cache is on modal-forge Volume, subpath /009-pika-h3-flex.
Proxy auth enabled.

PowerShell:
    cd 009-pika-h3-flex
    uv sync
    uv run modal deploy app.py

For Ref2VA, deploy a separate app:
    $env:PIKA_VARIANT = "ref2va"
    uv run modal deploy app.py

## Generate text + audio video (5 seconds, native 480p)

Edit only the prompt in request.example.json. Set Modal Proxy Token environment variables
MODAL_PROXY_KEY and MODAL_PROXY_SECRET first.

    uv run python generate.py --endpoint "https://<your-modal-server>"

The client calls POST /v1/videos, GET /v1/videos/{id}, and GET
/v1/videos/{id}/content, then saves both MP4 and a JSON timing record.

For first/last image conditioning or Ref2VA, supply conditions with an accessible
URI on the server side. Local Windows drive paths are not visible in Modal.

Pika H3 Flex requires exactly six denoiser updates and the original trained
sampling schedule. Do NOT override flow_shift/audio_flow_shift or use an
arbitrary MiniMax-H3 LoRA loader. Native outputs: 480p or 768p, 5-15 seconds.

## Validation

Code is newly implemented; do not infer production inference success from
the fact that deployment succeeds. Record real GPU peak memory and end-to-end
MP4 results after full inference validation.
