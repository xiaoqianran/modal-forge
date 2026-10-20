"""Run local fork's current PBR exporter regressions in an isolated Modal CPU image.

Usage:
  uv run --no-sync modal run tests/modal_export_regression.py

Includes only the exporter and test files; no Hunyuan3D weights, CUDA, Volume or production app.
"""
from pathlib import Path
import json
import subprocess
import modal

ROOT=Path(__file__).resolve().parents[1]
FORK=ROOT/"modal-forge-Hunyuan3D-2.1"
app=modal.App("hunyuan3d-pbr-v3-regressions")
image=(modal.Image.debian_slim(python_version="3.10")
    .pip_install("numpy==1.24.4","trimesh==4.4.7","pygltflib==1.16.3","pillow")
    .add_local_file(str(FORK/"hy3dpaint"/"convert_utils.py"),"/opt/convert_utils.py")
    .add_local_file(str(FORK/"tests"/"test_convert_pbr.py"),"/opt/tests/test_convert_pbr.py"))

@app.function(image=image,timeout=120)
def run_tests():
    result=subprocess.run(
        ["python","-m","unittest","discover","-s","/opt/tests","-p","test_convert_pbr.py","-v"],
        capture_output=True,text=True,cwd="/opt")
    return {"returncode":result.returncode,"stdout":result.stdout,"stderr":result.stderr}

@app.local_entrypoint()
def main():
    result=run_tests.remote()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result["returncode"]:
        raise RuntimeError("Modal exporter regression tests failed")

