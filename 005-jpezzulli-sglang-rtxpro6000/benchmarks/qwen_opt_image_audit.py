"""CPU-only inspection of Penny Royal v3.1.5; no model or GPU."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import modal

app = modal.App("005-qwen38-opt-image-audit")
image = modal.Image.from_registry(
    "ghcr.io/jpezzulli/sglang-rtxpro6000:v3.1.5", add_python="3.12"
).entrypoint([])


@app.function(image=image, cpu=1, memory=2048, timeout=130,
              scaledown_window=2, max_containers=1)
def inspect() -> dict:
    targets = [
        "/opt/pennyroyal/configs/pennyroyal/serve-flash-next-frspec.sh",
        "/opt/pennyroyal/configs/pennyroyal/request-capacity.sh",
    ]
    result = {"targets": {}, "env": {}, "python_versions": {}, "system": {}}
    for path in targets:
        p = Path(path)
        if p.is_file():
            lines = p.read_text("utf-8", errors="replace").splitlines()
            result["targets"][path] = {
                "lines": len(lines),
                "relevant_lines": [
                    f"{i+1}: {line[:650]}" for i, line in enumerate(lines)
                    if any(x in line for x in (
                        "CACHE_BASE", "CACHE_DIR", "TILELANG",
                        "TRITON", "FLASHINFER", "CUDA_CACHE",
                        "TORCHINDUCTOR", "MAX_RUNNING_REQUESTS",
                        "MAX_MAMBA_CACHE_SIZE", "PYTHON", "VENV_PATH",
                    ))
                ][:100],
            }
        else:
            result["targets"][path] = "not found"
    for key in ("PATH","PYTHONPATH","HOME","CUDA_HOME","TILELANG_CACHE_DIR",
                "TRITON_CACHE_DIR","CACHE_BASE","PYTHONHOME"):
        result["env"][key] = os.environ.get(key)
    pythons = ["/opt/pennyroyal/.venv/bin/python", "/opt/pennyroyal/.venv/bin/python3",
               "/usr/bin/python3", "python"]
    for cmd in pythons:
        try:
            p = subprocess.run([cmd, "-c",
                "import json,sys,importlib.metadata as m; x={}; "
                "names=('torch','tilelang','triton','flashinfer-python','sglang'); "
                "[(x.update({k:m.version(k) if k in [p.metadata['Name'] for p in m.distributions()] else None})) for k in names]; "
                "print(json.dumps({'executable':sys.executable,'versions':x}))"],
                capture_output=True, text=True, timeout=12)
            result["python_versions"][cmd] = {
                "code":p.returncode, "stdout":p.stdout[:1000], "stderr":p.stderr[:1500]
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["python_versions"][cmd] = repr(exc)
    result["system"] = {
        "uid":os.getuid(), "cwd":os.getcwd(), "python":".".join(map(str,__import__("sys").version_info[:3])),
    }
    return result


@app.local_entrypoint()
def main():
    result = inspect.remote()
    here = Path(__file__).resolve().parent.parent / "results" / "qwen_optimization"
    here.mkdir(parents=True, exist_ok=True)
    output = here / "cpu_image_audit_20261104.json"
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print("AUDIT_SAVED="+str(output),flush=True)
    for path, block in result["targets"].items():
        print("SCRIPT="+path,flush=True)
        if isinstance(block,dict):
            for line in block["relevant_lines"]: print(line,flush=True)
        else: print(block,flush=True)
    print("VERSIONS="+json.dumps(result["python_versions"],ensure_ascii=False),flush=True)
