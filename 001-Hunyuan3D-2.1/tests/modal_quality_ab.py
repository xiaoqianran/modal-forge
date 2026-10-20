"""Preserve raw Shape meshes; compare current and original sigma schedules."""
import json
import sys
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as production

app = modal.App("hunyuan3d-geometry-quality-ab")


@app.function(image=production.image.add_local_file(ROOT / "app.py", "/root/app.py"),
              gpu="L40S", cpu=8, memory=65536, timeout=900,
              volumes={"/modal-forge": production.storage})
def compare(content, regular_init=False):
    import io
    import os
    import numpy as np
    import torch
    from PIL import Image
    from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
    from hy3dshape.rembg import BackgroundRemover, prepare_foreground
    os.chdir(production.CODE)
    if regular_init:
        import hy3dshape.pipelines as module
        def original_build(config, state_dict, strict=True):
            component = module.instantiate_from_config(config)
            result = component.load_state_dict(state_dict, strict=strict)
            print("Ordinary checkpoint load:", result, flush=True)
            return component
        module.build_from_checkpoint = original_build
    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(production.MODEL)
    original = Image.open(io.BytesIO(content)).convert("RGBA")
    foreground = prepare_foreground(original, BackgroundRemover())
    folder_name = "quality-baseline-t009" if regular_init else "quality-ab-t009"
    folder = Path(production.BASE) / "tests" / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    foreground.save(folder / "foreground.png")
    rows = []
    cases = (
        ("current", foreground, False), ("original-sigmas", foreground, True),
        ("opaque-input", original, False),
    ) if not regular_init else (("original-init-and-sigmas", foreground, True),)
    for label, picture, legacy in cases:
        torch.manual_seed(42)
        kwargs = {"sigmas": np.linspace(0, 1, 50)} if legacy else {}
        mesh = pipeline(image=picture, num_inference_steps=50, enable_pbar=False, **kwargs)[0]
        mesh.export(folder / f"{label}.glb")
        normals = np.max(np.abs(mesh.face_normals), axis=1) > .999
        row = {"variant": label, "vertices": len(mesh.vertices), "faces": len(mesh.faces),
               "extents": mesh.extents.tolist(),
               "axis_aligned_area_ratio": float(mesh.area_faces[normals].sum() / mesh.area)}
        rows.append(row)
        print(json.dumps(row), flush=True)
    (folder / "report.json").write_text(json.dumps(rows, indent=2))
    production.storage.commit()
    return rows


@app.local_entrypoint()
def main(regular_init: bool = False):
    rows = compare.remote(Path("D:/Users/yuminghui/Downloads/pic/t009.jpg").read_bytes(), regular_init)
    folder_name = "quality-baseline-t009" if regular_init else "quality-ab-t009"
    dest = ROOT / "outputs/t008-t016/inspection" / ("original-baseline" if regular_init else "raw-shape-ab")
    dest.mkdir(exist_ok=True)
    names = [row["variant"] + ".glb" for row in rows] + ["foreground.png", "report.json"]
    for name in names:
        with (dest / name).open("wb") as handle:
            for chunk in production.storage.read_file("001-Hunyuan3D-2.1/tests/" + folder_name + "/" + name):
                handle.write(chunk)
    print(json.dumps(rows, indent=2))
