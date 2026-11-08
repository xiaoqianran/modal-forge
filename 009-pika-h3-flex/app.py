"""Pika H3 Flex SGLang Diffusion + inline FL2VA frame proxy on Modal."""
import os
import subprocess
import threading
from pathlib import Path

import modal

MODEL = "Pika-Labs/Pika-H3-Flex"
GPU = os.getenv("PIKA_GPU", "RTX-PRO-6000")
SG_PORT = 30010
PROXY_PORT = 30011

app = modal.App("modal-forge-009-pika-h3-flex-fl2va")
volume = modal.Volume.from_name("modal-forge", create_if_missing=True)
image = (
    modal.Image.from_registry("lmsysorg/sglang:v0.5.23")
    .entrypoint([])
    .env({"HF_HOME": "/root/.cache/huggingface"})
    .add_local_file(str(Path(__file__).with_name("proxy.py")), "/opt/pika/proxy.py")
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
@modal.web_server(port=PROXY_PORT, startup_timeout=3600, requires_proxy_auth=True)
def serve():
    """Serve T2VA / FL2VA through one six-step model and HTTP gateway."""
    cmd = [
        "sglang", "serve", "--model-path", MODEL,
        "--host", "127.0.0.1", "--port", str(SG_PORT),
        "--model-variant", "fl2va",
        "--performance-mode", "speed",
    ]
    print(f"Pika H3 Flex: GPU={GPU}, performance=speed, T2VA+FL2VA", flush=True)
    engine = subprocess.Popen(cmd)
    gateway = subprocess.Popen(["python", "-u", "/opt/pika/proxy.py"])

    def monitor():
        name, code = ("engine", engine.wait())
        print(f"{name} exited: {code}", flush=True)
        try:
            gateway.terminate()
            volume.commit()
        except Exception as exc:
            print(f"Cleanup failed: {exc}", flush=True)

    threading.Thread(target=monitor, daemon=True).start()
