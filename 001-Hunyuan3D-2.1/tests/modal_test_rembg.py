"""CPU-only Modal regression test against a fixed GitHub commit."""
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/xiaoqianran/modal-forge-Hunyuan3D-2.1.git"
COMMIT = "b4c57ab95601f9a258a54b1165feddd9f1f18c33"
app = modal.App("hunyuan3d-rembg-regression")

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git")
    .pip_install("pillow", "rembg==2.0.65", "onnxruntime==1.16.3", "numpy==1.24.4")
    .run_commands(
        f"git clone --filter=blob:none {REPO} /opt/hunyuan3d",
        f"git -C /opt/hunyuan3d checkout --detach {COMMIT}",
        f"test $(git -C /opt/hunyuan3d rev-parse HEAD) = {COMMIT}",
    )
    .add_local_file(str(ROOT / "tests" / "test_rembg.py"), "/opt/tests/test_rembg.py", copy=True)
    .add_local_file(str(ROOT / "modal-forge-Hunyuan3D-2.1" / "hy3dshape" / "hy3dshape" / "rembg.py"), "/opt/hunyuan3d/hy3dshape/hy3dshape/rembg.py", copy=True)
    .env({"HY3D_TEST_REPO": "/opt/hunyuan3d"})
)

@app.function(image=image, timeout=180)
def check():
    import subprocess
    completed = subprocess.run(
        ["python", "/opt/tests/test_rembg.py"],
        cwd="/tmp", text=True, capture_output=True,
    )
    return {
        "commit": COMMIT, "exit_code": completed.returncode,
        "stdout": completed.stdout, "stderr": completed.stderr,
    }


@app.local_entrypoint()
def main():
    result = check.remote()
    print(result["stdout"])
    if result["exit_code"]:
        raise RuntimeError(result["stderr"] or "Regression test failed")
    print("MODAL CPU PASS:", result["commit"])
