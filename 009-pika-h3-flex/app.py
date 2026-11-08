"""Pika H3 Flex SGLang Diffusion server on Modal."""
import os
import subprocess
import threading

import modal

MODEL = "Pika-Labs/Pika-H3-Flex"
VARIANT = os.getenv("PIKA_VARIANT", "fl2va").lower()
if VARIANT not in {"fl2va", "ref2va"}:
    raise ValueError("PIKA_VARIANT must be fl2va or ref2va")
GPU = os.getenv("PIKA_GPU", "RTX-PRO-6000")
PORT = 30010

app = modal.App(f"modal-forge-009-pika-h3-flex-{VARIANT}")
volume = modal.Volume.from_name("modal-forge", create_if_missing=True)
image = (
    modal.Image.from_registry("lmsysorg/sglang:v0.5.23")
    .entrypoint([])
    .env({"HF_HOME": "/root/.cache/huggingface"})
)


@app.function(
    image=image,
    gpu=GPU,
    cpu=12,
    memory=131072,
    volumes={
        "/root/.cache/huggingface": volume.with_mount_options(
            sub_path="/009-pika-h3-flex"
        ),
    },
    min_containers=0,
    max_containers=1,
    scaledown_window=2,
    timeout=7200,
)
@modal.concurrent(max_inputs=1)
@modal.web_server(port=PORT, startup_timeout=3600, requires_proxy_auth=True)
def serve():
    """Launch a six-step Pika H3 Flex server without changing its sampler."""
    args = [
        "sglang", "serve", "--model-path", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--model-variant", VARIANT,
        "--performance-mode", "speed",

    ]
    print(f"Starting Pika H3 Flex: variant={VARIANT} gpu={GPU}", flush=True)
    process = subprocess.Popen(args)

    def monitor():
        print(f"SGLang exited: {process.wait()}", flush=True)
        try:
            volume.commit()
        except Exception as exc:
            print(f"Volume commit failed: {exc}", flush=True)

    threading.Thread(target=monitor, daemon=True).start()
