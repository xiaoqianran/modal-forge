"""Pixal3D Modal 测试入口：仅在外层目录维护，不修改模型仓库。

运行 GPU 连通性检查：
    uv run modal run app.py::gpu_smoke

正式推理依赖 CUDA 扩展；必须先单独完成镜像兼容性验证。
"""
import modal

app = modal.App("pixal3d-test")

# GPU 烟雾测试只验证云端容器和显卡，不声称模型推理成功。
smoke_image = modal.Image.debian_slim(python_version="3.10").pip_install(
    "torch==2.6.0", index_url="https://download.pytorch.org/whl/cu124"
)


@app.function(image=smoke_image, gpu="L40S", timeout=600)
def check_gpu():
    import torch

    assert torch.cuda.is_available(), "Modal 未分配可用 CUDA GPU"
    x = torch.randn((512, 512), device="cuda")
    y = x @ x
    torch.cuda.synchronize()
    info = {
        "gpu": torch.cuda.get_device_name(0),
        "cuda": torch.version.cuda,
        "torch": str(torch.__version__),
        "matmul_mean": float(y.mean()),
        "memory_allocated_mb": round(torch.cuda.memory_allocated() / 1024**2, 1),
    }
    print(info, flush=True)
    return info


@app.local_entrypoint()
def gpu_smoke():
    print(check_gpu.remote())


# Official Pixal3D source is pinned; no model code is modified here.
SOURCE_REV = "ba514547f0ed6e071c83a99cabbffca42127dd3b"
WHEEL_BASE = "https://github.com/JeffreyXiang/Storages/releases/download/Space_Wheels_251210/"
EXTENSIONS = [
    "cumesh-0.0.1-cp310-cp310-linux_x86_64.whl",
    "flex_gemm-0.0.1-cp310-cp310-linux_x86_64.whl",
    "o_voxel-0.0.1-cp310-cp310-linux_x86_64.whl",
    "nvdiffrast-0.4.0-cp310-cp310-linux_x86_64.whl",
    "nvdiffrec_render-0.0.0-cp310-cp310-linux_x86_64.whl",
]
model_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.10")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .pip_install("torch==2.6.0", "torchvision==0.21.0",
                 index_url="https://download.pytorch.org/whl/cu124")
    .pip_install(
        "pillow==12.0.0", "imageio==2.37.2", "imageio-ffmpeg==0.6.0",
        "tqdm==4.67.1", "easydict==1.13", "opencv-python-headless==4.12.0.88",
        "trimesh==4.10.1", "transformers==4.57.3", "zstandard==0.25.0",
        "kornia==0.8.2", "timm==1.0.22", "diffusers==0.37.1",
        "accelerate==1.13.0", "plyfile==1.1.3", "einops==0.8.1",
        "huggingface_hub==0.36.2",
    )
    .pip_install(
        "https://github.com/LDYang694/Storages/releases/download/20260430/"
        "utils3d-0.0.2-py3-none-any.whl",
        *[WHEEL_BASE + name for name in EXTENSIONS],
    )
    .pip_install("ninja==1.13.0", "cmake==3.31.6",
                 "wheel==0.45.1", "setuptools==80.9.0")
    .env({"CUDA_HOME": "/usr/local/cuda", "NATTEN_CUDA_ARCH": "8.9",
          "NATTEN_N_WORKERS": "4"})
    .run_commands(
        "pip install --no-binary=natten --no-build-isolation natten==0.21.0",
        "git clone https://github.com/xiaoqianran/modal-forge-Pixal3D.git /opt/pixal3d",
        f"cd /opt/pixal3d && git checkout --detach {SOURCE_REV}",
        "pip install --no-deps git+https://github.com/microsoft/MoGe.git@07444410f1e33f402353b99d6ccd26bd31e469e8",
    )
    .env({"ATTN_BACKEND": "sdpa", "HF_HOME": "/cache/huggingface",
          "PYTHONPATH": "/opt/pixal3d"})
)
cache = modal.Volume.from_name("pixal3d-hf-cache", create_if_missing=True)


@app.function(image=model_image, gpu="L40S", timeout=1800,
              volumes={"/cache": cache})
def check_model():
    import torch
    import natten
    import flex_gemm
    import o_voxel
    import cumesh
    from pixal3d.pipelines import Pixal3DImageTo3DPipeline
    return {"gpu": torch.cuda.get_device_name(0), "imports": "OK"}


@app.function(image=model_image, gpu="L40S", timeout=3600,
              volumes={"/cache": cache}, memory=16384)
def infer_glb(payload: bytes) -> bytes:
    import os
    import tempfile
    from pathlib import Path
    from PIL import Image
    from io import BytesIO
    from inference import run_inference
    with tempfile.TemporaryDirectory() as d:
        inp, out = Path(d) / "input.png", Path(d) / "output.glb"
        with Image.open(BytesIO(payload)) as im:
            im.save(inp)
        run_inference(image_path=str(inp), output_path=str(out),
                      low_vram=False, resolution=1536, rembg_model_name=None)
        if not out.is_file() or out.stat().st_size == 0:
            raise RuntimeError("Pixal3D did not produce a nonempty GLB")
        cache.commit()
        return out.read_bytes()


@app.local_entrypoint()
def verify_environment():
    print(check_model.remote())


@app.local_entrypoint()
def main(image: str, output: str = "output.glb"):
    from pathlib import Path
    data = infer_glb.remote(Path(image).read_bytes())
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"Saved {dest} ({len(data)} bytes)")
