"""Independent Modal smoke test for PR #215 / #163 PBR GLB conversion.

Usage: uv run modal run tests/modal_compare_glb.py
No GPU, model weights, production app.py or Modal Volume required.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
FORK_COMMIT = "b4c57ab95601f9a258a54b1165feddd9f1f18c33"
REPO = "/opt/hunyuan3d"
app = modal.App("hunyuan3d-glb-converter-comparison")

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .pip_install(
        "numpy==1.24.4",
        "trimesh==4.4.7",
        "pygltflib==1.16.3",
        "pillow",
        "opencv-python-headless==4.10.0.84",
    )
    .run_commands(
        f"git clone --filter=blob:none https://github.com/xiaoqianran/modal-forge-Hunyuan3D-2.1.git {REPO}",
        f"git -C {REPO} checkout --detach {FORK_COMMIT}",
        f"test $(git -C {REPO} rev-parse HEAD) = {FORK_COMMIT}",
    )
    .env({"HY3D_TEST_REPO": REPO})
    .add_local_file(str(ROOT / "tests" / "compare_glb.py"), "/opt/tests/compare_glb.py")
    .add_local_file(str(ROOT / "tests" / "edge_glb.py"), "/opt/tests/edge_glb.py")
)

@app.function(image=image, timeout=180)
def compare() -> dict:
    result = subprocess.run(
        ["python", "/opt/tests/compare_glb.py", "--output", "/tmp/glb-compare"],
        capture_output=True, text=True, cwd="/tmp",
    )
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}

@app.function(image=image, timeout=180)
def edges() -> dict:
    result = subprocess.run(["python", "/opt/tests/edge_glb.py"], capture_output=True, text=True, cwd="/tmp")
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
@app.local_entrypoint()
def main():
    result = compare.remote()
    edge_result = edges.remote()
    print("EDGE TEST:", json.dumps(edge_result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["exit_code"]:
        raise RuntimeError("GLB comparison failed; inspect the report above")



