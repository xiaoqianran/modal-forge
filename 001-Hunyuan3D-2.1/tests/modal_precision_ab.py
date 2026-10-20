"""Compare norm precision on the same cached weights and initial noise, before Paint."""
import json
import sys
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as production

app = modal.App("hunyuan3d-precision-validation")
test_image = production.image.add_local_file(
    ROOT / "modal-forge-Hunyuan3D-2.1/hy3dshape/hy3dshape/models/denoisers/hunyuandit.py",
    production.CODE + "/hy3dshape/hy3dshape/models/denoisers/hunyuandit.py",
).add_local_file(ROOT / "app.py", "/root/app.py")


@app.function(image=test_image, gpu="L40S", cpu=8, memory=65536, timeout=1800,
              volumes={"/modal-forge": production.storage})
def compare(content, variant="all"):
    import io
    import os
    import numpy as np
    import torch
    from PIL import Image
    from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
    from hy3dshape.rembg import BackgroundRemover, prepare_foreground
    from hy3dshape.models.denoisers.hunyuandit import StableLayerNorm, StableRMSNorm

    os.chdir(production.CODE)
    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(production.MODEL)
    foreground = prepare_foreground(Image.open(io.BytesIO(content)), BackgroundRemover())
    folder = Path(production.BASE) / ("tests/precision-fp32-attention" if variant != "all" else "tests/precision-validation")
    folder.mkdir(parents=True, exist_ok=True)
    foreground.save(folder / "foreground.png")
    original_prepare = pipeline.prepare_latents
    torch.manual_seed(42)
    noise = original_prepare(1, torch.float16, torch.device("cuda"), None)
    pipeline.prepare_latents = lambda batch, dtype, device, generator: noise.to(dtype=dtype, device=device).clone()
    rows = []
    cases = (("legacy-fp16", torch.float16, False),
                              ("stable-fp16", torch.float16, True),
                              ("bf16", torch.bfloat16, True)) if variant == "all" else (("fp32-attention", torch.float16, True),)
    for label, dtype, safe in cases:
        pipeline.to(dtype=dtype)
        for module in pipeline.model.modules():
            if isinstance(module, (StableLayerNorm, StableRMSNorm)):
                module.fp16_safe = safe
            if hasattr(module, "upcast_attention"):
                module.upcast_attention = variant != "all"
        stats = []
        def callback(index, timestep, output):
            x = output.prev_sample.float()
            finite = bool(torch.isfinite(x).all())
            stats.append({"step": index, "finite": finite, "min": float(x.min()), "max": float(x.max())})
            if not finite:
                raise FloatingPointError(f"Non-finite latents at step {index}")
        try:
            mesh = pipeline(image=foreground, num_inference_steps=50, enable_pbar=False,
                            callback=callback, callback_steps=1)[0]
            mesh.export(folder / f"{label}.glb")
            aligned = np.max(np.abs(mesh.face_normals), axis=1) > .999
            row = {"variant": label, "vertices": len(mesh.vertices), "faces": len(mesh.faces),
                   "extents": mesh.extents.tolist(),
                   "axis_aligned_area_ratio": float(mesh.area_faces[aligned].sum() / mesh.area),
                   "steps": stats}
        except Exception as error:
            row = {"variant": label, "error": repr(error), "steps": stats}
        rows.append(row)
        (folder / "report.json").write_text(json.dumps(rows, indent=2))
        production.storage.commit()
        print(json.dumps({k: v for k, v in row.items() if k != "steps"}), flush=True)
    return rows


@app.local_entrypoint()
def main(image_path: str = "D:/Users/yuminghui/Downloads/pic/t009.jpg", variant: str = "all"):
    rows = compare.remote(Path(image_path).read_bytes(), variant)
    destination = ROOT / "outputs/quality-fixes" / ("precision-fp32-attention" if variant != "all" else "precision")
    destination.mkdir(parents=True, exist_ok=True)
    files = [row["variant"] + ".glb" for row in rows if "error" not in row] + ["foreground.png", "report.json"]
    for name in files:
        with (destination / name).open("wb") as handle:
            folder = "precision-fp32-attention" if variant != "all" else "precision-validation"
            for chunk in production.storage.read_file("001-Hunyuan3D-2.1/tests/" + folder + "/" + name):
                handle.write(chunk)
    print(json.dumps([{k: v for k, v in row.items() if k != "steps"} for row in rows], indent=2))
