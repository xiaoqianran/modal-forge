"""L40S real Shape A/B, same seed and inference steps, no Paint.
Run: uv run --no-sync modal run tests/modal_shape_ab.py
Uses precomputed foregrounds stored in Modal Volume.
"""
from __future__ import annotations
import json
import modal
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from types import SimpleNamespace
production = SimpleNamespace(
    BASE="/modal-forge/001-Hunyuan3D-2.1",
    CODE="/opt/hunyuan3d",
    MODEL="tencent/Hunyuan3D-2.1",
    FORK_URL="https://github.com/xiaoqianran/modal-forge-Hunyuan3D-2.1.git",
    FORK_COMMIT="b4c57ab95601f9a258a54b1165feddd9f1f18c33",
    storage=modal.Volume.from_name("modal-forge",create_if_missing=True)
)

app=modal.App("hunyuan3d-shape-rembg-ab")
shape_image=(
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04",add_python="3.10")
    .apt_install("git","build-essential","cmake","ninja-build","libgl1","libglib2.0-0")
    .uv_pip_install("torch==2.5.1","torchvision==0.20.1",index_url="https://download.pytorch.org/whl/cu124")
    .env({"CUDA_HOME":"/usr/local/cuda","TORCH_CUDA_ARCH_LIST":"8.9",
          "HF_HOME":f"{production.BASE}/weights/hf",
          "HY3DGEN_MODELS":f"{production.BASE}/weights/hy3dgen",
          "PYTHONPATH":f"{production.CODE}:{production.CODE}/hy3dshape"})
    .run_commands(
        f"git clone --filter=blob:none {production.FORK_URL} {production.CODE} && git -C {production.CODE} checkout --detach {production.FORK_COMMIT}",
        "python -m pip install 'setuptools<81' transformers==4.46.0 diffusers==0.30.0 accelerate==1.1.1 huggingface-hub==0.30.2 safetensors==0.4.4 numpy==1.24.4 scipy==1.14.1 scikit-image==0.24.0 torchdiffeq==0.2.5 timm==1.0.11 einops==0.8.0 opencv-python-headless==4.10.0.84 omegaconf==2.3.0 pyyaml==6.0.2 trimesh==4.4.7 pymeshlab==2022.2.post3 pygltflib==1.16.3 xatlas==0.0.9 tqdm==4.66.5",
    )
)

@app.function(image=shape_image,gpu="L40S",cpu=8,memory=32768,timeout=1800,
              volumes={"/modal-forge":production.storage})
def shape_ab(seed:int=42,steps:int=50):
    import os, time, torch
    from PIL import Image
    from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
    os.chdir(production.CODE)
    pipeline=Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(production.MODEL)
    pipeline.to("cuda")
    src=Path(production.BASE)/"tests"/"rmbg2-ab"
    dst=Path(production.BASE)/"tests"/"shape-ab"
    dst.mkdir(parents=True,exist_ok=True)
    data={"seed":seed,"steps":steps,"gpu":"L40S","model":production.MODEL,
          "fork_commit":production.FORK_COMMIT,"items":{}}
    import trimesh
    for key in ("original","rmbg2"):
        foreground=Image.open(src/f"{key}.png").convert("RGBA")
        torch.manual_seed(seed)
        if torch.cuda.is_available():torch.cuda.manual_seed_all(seed)
        start=time.perf_counter()
        mesh=pipeline(image=foreground,num_inference_steps=steps)[0]
        torch.cuda.synchronize()
        path=dst/f"{key}.glb"
        mesh.export(str(path))
        parts=trimesh.load(str(path),force="scene")
        geometries=list(parts.geometry.values())
        bounds=parts.bounds.tolist() if parts.bounds is not None else None
        data["items"][key]={"seconds":round(time.perf_counter()-start,2),
            "bytes":path.stat().st_size,"meshes":len(geometries),
            "faces":int(sum(len(m.faces) for m in geometries)),
            "vertices":int(sum(len(m.vertices) for m in geometries)),
            "bounds":bounds,"watertight":all(m.is_watertight for m in geometries)}
        production.storage.commit()
    (dst/"report.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    production.storage.commit()
    return data

@app.local_entrypoint()
def main():
    print(json.dumps(shape_ab.remote(),ensure_ascii=False,indent=2))





