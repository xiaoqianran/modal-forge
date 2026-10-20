"""GPU test using bundled *real* Hunyuan3D Paint case_1 files and model pipeline.
Production app.py is imported for its cached image config only; never edited.
Run: uv run --no-sync modal run tests/modal_real_paint.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import modal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app as production

app=modal.App("hunyuan3d-real-paint-export-validation")

@app.function(image=production.image,gpu="L40S",cpu=8,memory=32768,timeout=1800,
              volumes={"/modal-forge":production.storage})
def real_paint():
    import os, time
    from pathlib import Path
    from hy3dpaint.textureGenPipeline import Hunyuan3DPaintPipeline,Hunyuan3DPaintConfig
    from hy3dpaint.convert_utils import create_glb_with_pbr_materials
    from hy3dpaint.DifferentiableRenderer.mesh_utils import _convert_obj_to_glb_trimesh

    os.chdir(production.CODE)
    out=Path(production.BASE)/"tests"/"real-paint-case1"
    out.mkdir(parents=True,exist_ok=True)
    conf=Hunyuan3DPaintConfig(6,512)
    conf.realesrgan_ckpt_path=f"{production.CODE}/hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
    conf.multiview_cfg_path=f"{production.CODE}/hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
    conf.custom_pipeline=f"{production.CODE}/hy3dpaint/hunyuanpaintpbr"
    pipeline=Hunyuan3DPaintPipeline(conf)
    start=time.perf_counter()
    obj=Path(pipeline(
        mesh_path=f"{production.CODE}/hy3dpaint/assets/case_1/mesh.glb",
        image_path=f"{production.CODE}/hy3dpaint/assets/case_1/image.png",
        output_mesh_path=str(out/"textured.obj"),save_glb=False,
    ))
    paint_seconds=time.perf_counter()-start
    textures={"albedo":str(obj.with_suffix(".jpg")),
      "metallic":str(obj.with_name(obj.stem+"_metallic.jpg")),
      "roughness":str(obj.with_name(obj.stem+"_roughness.jpg"))}
    files={k:Path(v).stat().st_size for k,v in textures.items()}
    conversions={}
    for name in ("pr215","pr163"):
        dest=out/f"{name}.glb"
        try:
            if name=="pr215":
                success=_convert_obj_to_glb_trimesh(str(obj),str(dest))
                if not success: raise RuntimeError("converter returned False")
            else:
                create_glb_with_pbr_materials(str(obj),textures,str(dest))
            conversions[name]=dict(production.check_glb(dest,True),bytes=dest.stat().st_size)
        except Exception as exc:
            conversions[name]={"error":f"{type(exc).__name__}: {exc}"}
    report={"paint_seconds":round(paint_seconds,2),"obj_bytes":obj.stat().st_size,
      "textures":files,"conversions":conversions,"volume_path":"001-Hunyuan3D-2.1/tests/real-paint-case1"}
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    production.storage.commit()
    return report

@app.local_entrypoint()
def main():
    print(json.dumps(real_paint.remote(),ensure_ascii=False,indent=2))
