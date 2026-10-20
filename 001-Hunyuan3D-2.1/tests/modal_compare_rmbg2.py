"""Modal L40S: original rembg vs BRIA RMBG-2.0, segmentation-only A/B.
Run: uv run --no-sync modal run tests/modal_compare_rmbg2.py
Requires access to briaai/RMBG-2.0 via existing huggingface-secret.
No Shape/Paint pipeline or production file is modified.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App("hunyuan3d-rmbg2-ab")
volume = modal.Volume.from_name("modal-forge", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.5.1", "torchvision==0.20.1",
        "transformers==4.44.2", "timm==1.0.11", "huggingface_hub==0.26.2",
        "pillow==10.4.0", "rembg==2.0.65", "onnxruntime==1.19.2",
        "numpy==1.26.4", "kornia==0.7.4",
    )
    .add_local_file(str(ROOT / "modal-forge-Hunyuan3D-2.1" / "assets" / "demo.png"),
                    "/opt/input/demo.png", copy=True)
)

@app.function(image=image, gpu="L40S", timeout=900, secrets=[modal.Secret.from_name("huggingface-secret")], volumes={"/modal-forge": volume})
def compare(use_hf_secret: bool = False):
    import os
    import torch
    from PIL import Image
    from rembg import new_session, remove

    source = Image.open("/opt/input/demo.png").convert("RGB")
    folder = Path("/modal-forge/001-Hunyuan3D-2.1/tests/rmbg2-ab")
    folder.mkdir(parents=True, exist_ok=True)
    source.save(folder / "source.png")
    result = {"image_size": source.size, "device": torch.cuda.get_device_name(),
              "outputs": {}, "model": "briaai/RMBG-2.0"}
    t = time.perf_counter()
    session = new_session()
    old = remove(source, session=session).convert("RGBA")
    old.save(folder / "original.png")
    result["outputs"]["original"] = {"seconds": round(time.perf_counter()-t, 3),
                                       "alpha_extrema": old.getchannel("A").getextrema()}

    from transformers import AutoModelForImageSegmentation
    from torchvision import transforms
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise RuntimeError("RMBG-2.0 requires Hugging Face access. Ensure huggingface-secret provides HF_TOKEN.")
    t = time.perf_counter()
    model = AutoModelForImageSegmentation.from_pretrained(
        "briaai/RMBG-2.0", trust_remote_code=True, token=token
    ).eval().to("cuda")
    result["model_load_seconds"] = round(time.perf_counter()-t, 3)
    transform = transforms.Compose([
        transforms.Resize((1024, 1024)),
        transforms.ToTensor(),
        transforms.Normalize([0.5]*3, [1.0]*3)
    ])
    t = time.perf_counter()
    with torch.inference_mode():
        prediction = model(transform(source).unsqueeze(0).to("cuda"))[-1].sigmoid().cpu()[0].squeeze()
    torch.cuda.synchronize()
    mask = transforms.ToPILImage()(prediction).resize(source.size)
    output = source.convert("RGBA")
    output.putalpha(mask)
    output.save(folder / "rmbg2.png")
    result["outputs"]["rmbg2"] = {"seconds": round(time.perf_counter()-t, 3),
                                    "alpha_extrema": mask.getextrema()}
    result["peak_gpu_memory_mb"] = round(torch.cuda.max_memory_allocated()/1024**2)
    (folder / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    volume.commit()
    return result


@app.local_entrypoint()
def main():
    import json
    print(json.dumps(compare.remote(), indent=2))


