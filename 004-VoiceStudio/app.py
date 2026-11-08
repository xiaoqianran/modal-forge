"""VoiceStudio official CUDA container hosted as an independent Modal app."""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

import modal


# 许可证配置
MODEL_LICENSES = [
    "k2-fsa/OmniVoice",
]

app = modal.App("modal-forge-004-voicestudio")
volume = modal.Volume.from_name("modal-forge", create_if_missing=True)
image = (
    modal.Image.from_registry("ghcr.io/debpalash/voicestudio:stable")
    .entrypoint([])
    .env({
        "HF_HOME": "/app/omnivoice_data/huggingface",
        "OMNIVOICE_DATA_DIR": "/app/omnivoice_data",
        "OMNIVOICE_BIND_HOST": "0.0.0.0",
        "OMNIVOICE_SERVER_MODE": "1",
        "OMNIVOICE_ALLOWED_ORIGINS": (
            "https://chenjunnaner--modal-forge-004-voicestudio-serve.us-east.modal.run,"
            "http://localhost:3901,http://127.0.0.1:3901,app://voicestudio"
        ),
        "PYTHONPATH": "/app/backend",
    })
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("modal-forge-004-voicestudio")],
    gpu=os.getenv("MODAL_GPU", "L40S"),
    volumes={"/app/omnivoice_data": volume.with_mount_options(sub_path="/004-VoiceStudio")},
    min_containers=1,
    max_containers=1,
    timeout=86400,
)
@modal.concurrent(max_inputs=100)
@modal.web_server(port=3900, startup_timeout=600, requires_proxy_auth=False)
def serve():
    """Run the upstream Docker entrypoint; persist live server writes periodically."""
    def persist():
        while True:
            threading.Event().wait(60)
            try:
                volume.commit()
            except Exception as exc:
                print(f"Periodic Volume commit failed: {exc}", flush=True)


    def initialize_model_licenses():
        base_url = "http://127.0.0.1:3900"

        # 等待 VoiceStudio API 启动
        for _ in range(120):
            try:
                with urllib.request.urlopen(
                    f"{base_url}/health", timeout=3
                ):
                    break
            except Exception:
                time.sleep(2)
        else:
            print("VoiceStudio API 未就绪")
            return

        for repo_id in MODEL_LICENSES:
            url = f"{base_url}/models/licenses/acceptance/{repo_id}"
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    status = json.load(response)
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                print(f"{repo_id}: 许可证查询失败: {exc}", flush=True)
                continue

            state = status.get("state", "unknown")
            print(f"{repo_id}: 许可证状态 {state}", flush=True)
            if not status.get("accepted"):
                print(f"{repo_id}: 请在 Model Catalogue 确认当前许可证", flush=True)


    threading.Thread(target=persist, daemon=True).start()
    threading.Thread(
        target=initialize_model_licenses,
        daemon=True,
    ).start()
    process = subprocess.Popen(["python3", "backend/docker_entrypoint.py"], cwd="/app")

    def monitor():
        code = process.wait()
        print(f"VoiceStudio process stopped (exit code {code})", flush=True)
        volume.commit()

    threading.Thread(target=monitor, daemon=True).start()
    # Modal's web_server decorator waits for port 3900 to become available.
    # The function itself must return instead of waiting on the child process.
