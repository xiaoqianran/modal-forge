"""Very cheap CPU-only sanity check of the compiler Volume v2 commit/reload contract."""
from __future__ import annotations
import json
import uuid
from pathlib import Path
import modal

from benchmarks.qwen_compiler_cache import COMPILER_VOLUME, COMPILER_VOLUME_NAME

app=modal.App("005-qwen-compile-volume-preflight")
image=modal.Image.debian_slim(python_version="3.12").add_local_python_source(
    "benchmarks"
)

@app.function(image=image, cpu=1, memory=512, timeout=45,
              volumes={"/compiler-vol":COMPILER_VOLUME}, max_containers=1)
def write_preflight(key:str):
    path=Path("/compiler-vol")/"preflight"/f"{key}.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"key":key,"kind":"preflight-no-model-cache"}),
                    encoding="utf-8")
    COMPILER_VOLUME.commit()
    return path.as_posix()

@app.function(image=image, cpu=1, memory=512, timeout=45,
              volumes={"/compiler-vol":COMPILER_VOLUME}, max_containers=1)
def check_preflight(key:str):
    COMPILER_VOLUME.reload()
    path=Path("/compiler-vol")/"preflight"/f"{key}.json"
    x=json.loads(path.read_text("utf-8"))
    return {"verified":x["key"]==key,"path":path.as_posix(),
            "volume":COMPILER_VOLUME_NAME}

@app.local_entrypoint()
def main():
    key=uuid.uuid4().hex
    path=write_preflight.remote(key)
    result=check_preflight.remote(key)
    if not result["verified"]:
        raise RuntimeError("Volume v2 commit/reload preflight failed")
    here=Path(__file__).resolve().parent.parent/"results"/"qwen_optimization"
    here.mkdir(parents=True,exist_ok=True)
    out=here/"compiler_volume_cpu_preflight.json"
    out.write_text(json.dumps({"writer_path":path,"reader":result},
                              indent=2),encoding="utf-8")
    print("VOLUME_V2_PREFLIGHT_OK "+str(out),flush=True)
