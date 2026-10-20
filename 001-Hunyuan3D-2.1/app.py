"""Hunyuan3D-2.1 Fork 的 Modal 单文件推理入口。

镜像构建、主体预处理、Shape 候选验收、Paint、PBR 导出与可复查的中间产物。
运行 GPU 需要显式传入 --run-gpu。
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import modal

FORK_URL = "https://github.com/xiaoqianran/modal-forge-Hunyuan3D-2.1.git"
FORK_COMMIT = "1112a61026bc6e11a89ea95614e97cba8235b475"
# Native dependencies are built once at this revision; later Python-only fixes
# are checked out after compilation. The diff guard below rejects stale builds.
BUILD_COMMIT = "020ffd34226022bbceb5a37e1c899a1a4f6805a6"
CODE = "/opt/hunyuan3d"
BASE = "/modal-forge/001-Hunyuan3D-2.1"
MODEL = "tencent/Hunyuan3D-2.1"
GPU = "L40S"

storage = modal.Volume.from_name("modal-forge", create_if_missing=True)
app = modal.App("modal-forge-hunyuan3d-2-1")

image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.10")
    .apt_install(
        "git", "build-essential", "cmake", "ninja-build", "wget",
        "libgl1", "libegl1", "libglib2.0-0", "libsm6", "libxext6",
        "libxrender1", "libxi6", "libxkbcommon-x11-0",
    )
    .uv_pip_install(
        "torch==2.5.1", "torchvision==0.20.1",
        index_url="https://download.pytorch.org/whl/cu124",
    )
    .env({
        "CUDA_HOME": "/usr/local/cuda",
        "TORCH_CUDA_ARCH_LIST": "8.9",
        "MAX_JOBS": "4",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": f"{CODE}:{CODE}/hy3dshape:{CODE}/hy3dpaint",
    })
    # 从 GitHub 获取并验证指定 SHA，完全不上传本地 Fork 文件。
    .run_commands(
        f"git clone --filter=blob:none {FORK_URL} {CODE} "
        f"&& git -C {CODE} checkout --detach {BUILD_COMMIT} "
        f"&& test $(git -C {CODE} rev-parse HEAD) = {BUILD_COMMIT}",
    )
    # 在固定 Git commit 检出完成后直接读取 Fork 的依赖文件。
    .run_commands(
        "python -m pip install wheel 'setuptools<81'",
        f"python -m pip install --no-build-isolation -r {CODE}/requirements.txt "
        "'torch==2.5.1' 'torchvision==0.20.1' 'timm==1.0.11' 'torchdiffeq==0.2.5'",
    )
    # Modal's standalone Python was built with clang; link extensions with the
    # GCC toolchain installed in this CUDA image rather than a missing clang++.
    .env({"CC": "gcc", "CXX": "g++", "LDSHARED": "g++ -shared"})
    .run_commands(
        f"cd {CODE}/hy3dpaint/custom_rasterizer && pip install --no-build-isolation .",
        f"cd {CODE}/hy3dpaint/DifferentiableRenderer && bash compile_mesh_painter.sh",
        f"mkdir -p {CODE}/hy3dpaint/ckpt && wget -q -O "
        f"{CODE}/hy3dpaint/ckpt/RealESRGAN_x4plus.pth "
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    )
    .run_commands(
        f"git -C {CODE} fetch --depth=1 origin {FORK_COMMIT} "
        f"&& git -C {CODE} diff --exit-code {BUILD_COMMIT} FETCH_HEAD -- "
        "requirements.txt hy3dpaint/custom_rasterizer hy3dpaint/DifferentiableRenderer "
        f"&& git -C {CODE} checkout --detach {FORK_COMMIT} "
        f"&& test $(git -C {CODE} rev-parse HEAD) = {FORK_COMMIT}",
    )
    .run_commands(
        f"cd {CODE} && python -m unittest discover -s tests -v",
        "python -c 'from torchvision_fix import apply_fix; apply_fix(); "
        "from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline; "
        "from textureGenPipeline import Hunyuan3DPaintPipeline; "
        "from DifferentiableRenderer.MeshRender import meshVerticeInpaint; "
        "assert meshVerticeInpaint is not None; print(\"Inference imports and inpaint extension OK\")'",
    )
    .uv_pip_install("pyrender==0.1.45", "kornia==0.7.3")
    # Set persistent cache paths only after build-time imports. Otherwise
    # Transformers creates /modal-forge in the image and Modal cannot mount it.
    .env({
        "HF_HOME": f"{BASE}/weights/hf",
        "HY3DGEN_MODELS": f"{BASE}/weights/hy3dgen",
        "U2NET_HOME": f"{BASE}/weights/rembg",
        "PYOPENGL_PLATFORM": "egl",
    })
)


def check_glb(path: Path, require_pbr: bool) -> dict:
    """读取 glTF JSON 块，检查输出材质引用；不改动 GLB 本身。"""
    import struct

    with path.open("rb") as handle:
        header = handle.read(20)
        if len(header) != 20 or header[:4] != b"glTF":
            raise RuntimeError(f"非法 GLB：{path}")
        json_length = struct.unpack_from("<I", header, 12)[0]
        info = json.loads(handle.read(json_length).decode("utf-8"))
    materials = info.get("materials", [])
    base_color = any("baseColorTexture" in m.get("pbrMetallicRoughness", {}) for m in materials)
    metal_rough = any("metallicRoughnessTexture" in m.get("pbrMetallicRoughness", {}) for m in materials)
    if require_pbr and not (base_color and metal_rough):
        raise RuntimeError("PBR GLB 缺少 baseColor 或 metallicRoughness 纹理")
    return {"materials": len(materials), "base_color": base_color, "metallic_roughness": metal_rough}


@app.cls(
    image=image, gpu=GPU, cpu=8, memory=65536, timeout=3600,
    scaledown_window=60, volumes={"/modal-forge": storage},
)
class Hunyuan3D:
    @modal.enter()
    def load(self):
        """每个容器仅初始化一次 Shape 模型；Paint 按需懒加载。"""
        import os
        import sys
        from torchvision_fix import apply_fix

        os.chdir(CODE)
        for directory in (CODE, f"{CODE}/hy3dshape", f"{CODE}/hy3dpaint"):
            if directory not in sys.path:
                sys.path.insert(0, directory)
        apply_fix()
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline

        self.shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(MODEL)
        self.shape.to("cuda")
        self.shape_backend = "2.1"
        self.paint = None
        self.paint_config = None
        self.removers = {}
        storage.commit()

    def get_shape(self, backend):
        if backend != self.shape_backend:
            import gc
            import torch
            from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
            self.shape = None
            self.paint = None
            self.paint_config = None
            gc.collect()
            torch.cuda.empty_cache()
            model, subfolder = (MODEL, "hunyuan3d-dit-v2-1") if backend == "2.1" else (
                "tencent/Hunyuan3D-2mv", "hunyuan3d-dit-v2-mv")
            self.shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model, subfolder=subfolder)
            self.shape_backend = backend
            storage.commit()
        return self.shape

    def get_paint(self, views: int, resolution: int):
        """复用相同参数的 Paint Pipeline。"""
        if self.paint is None or self.paint_config != (views, resolution):
            import gc
            import torch
            from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

            self.paint = None
            self.paint_config = None
            gc.collect()
            torch.cuda.empty_cache()
            config = Hunyuan3DPaintConfig(views, resolution)
            config.realesrgan_ckpt_path = f"{CODE}/hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
            config.multiview_cfg_path = f"{CODE}/hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
            config.custom_pipeline = f"{CODE}/hy3dpaint/hunyuanpaintpbr"
            self.paint = Hunyuan3DPaintPipeline(config)
            self.paint_config = (views, resolution)
            storage.commit()
        return self.paint

    @modal.method()
    def generate(
        self, image_url: str = "", name: str = "sample", paint: bool = True,
        steps: int = 50, seed: int = 42, views: int = 6, resolution: int = 512,
        image_bytes: bytes | None = None,
        mask_bytes: bytes | None = None, background: str = "rembg",
        shape_candidates: int = 1, precision: str = "fp16",
        allow_box_like: bool = False, allow_flat: bool = False,
        min_foreground: float = .01,
        attention_precision: str = "native",
        shape_backend: str = "2.1", view_bytes: dict[str, bytes] | None = None,
        min_silhouette_iou: float = .75,
    ) -> dict:
        """图片 → Shape → 可选 Paint → PBR GLB，保存文件与计时数据。"""
        import torch
        import io
        import numpy as np
        from PIL import Image, ImageOps
        from hy3dshape.rembg import BackgroundRemover, RMBG2Remover, prepare_foreground
        from hy3dshape.quality import (
            inspect_foreground, foreground_preview, inspect_mesh, render_shape, select_candidate,
        )

        if bool(image_url) == (image_bytes is not None):
            raise ValueError("必须且只能提供图片地址或图片内容其中之一")
        if image_url and not image_url.startswith("https://"):
            raise ValueError("只接受 HTTPS 图片地址")
        if not (1 <= steps <= 100 and 6 <= views <= 9 and resolution in (512, 768)):
            raise ValueError("推理参数超出允许范围")
        if not (1 <= shape_candidates <= 4 and .0 <= min_foreground <= .5):
            raise ValueError("shape_candidates 必须为 1–4，min_foreground 必须为 0–0.5")
        if not 0 <= min_silhouette_iou <= 1:
            raise ValueError("min_silhouette_iou 必须为 0–1")
        if background not in ("rembg", "rmbg2", "none") or precision not in ("fp16", "bf16"):
            raise ValueError("background 支持 rembg/rmbg2/none；precision 支持 fp16/bf16")
        if attention_precision not in ("native", "fp32"):
            raise ValueError("attention_precision 支持 native/fp32")
        if shape_backend not in ("2.1", "2mv"):
            raise ValueError("shape_backend 支持 2.1/2mv")
        if view_bytes and shape_backend != "2mv":
            raise ValueError("额外视图需要 --shape-backend 2mv，默认 2.1 不支持多图条件")
        if shape_backend == "2mv" and attention_precision != "native":
            raise ValueError("FP32 attention 诊断选项目前仅适用于 2.1 DiT")
        if view_bytes and (set(view_bytes) - {"left", "back", "right"}
                           or any(len(data) > 40 * 1024 * 1024 for data in view_bytes.values())):
            raise ValueError("视图名称仅支持 left/back/right，每张不能超过 40 MiB")
        if mask_bytes is not None and len(mask_bytes) > 40 * 1024 * 1024:
            raise ValueError("mask 不能超过 40 MiB")
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_") or "sample"

        total_start = time.perf_counter()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        stem = f"{name}_{stamp}_{seed}_{uuid.uuid4().hex[:8]}"
        destination = Path(f"{BASE}/outputs/{stem}")
        destination.mkdir(parents=True, exist_ok=True)
        metadata = {
            "status": "running", "model": MODEL, "gpu": GPU, "fork_commit": FORK_COMMIT,
            "paint": paint, "steps": steps, "seed": seed, "precision": precision,
            "attention_precision": attention_precision,
            "shape_backend": shape_backend,
            "allow_box_like": allow_box_like, "allow_flat": allow_flat,
            "min_foreground": min_foreground, "shape_candidate_count": shape_candidates,
            "min_silhouette_iou": min_silhouette_iou,
            "background": "manual-mask" if mask_bytes is not None else background,
            "views": views if paint else None, "resolution": resolution if paint else None,
            "volume": "modal-forge", "path": None, "shape_candidates": [],
        }

        def finish(status, reason=None):
            metadata["status"] = status
            metadata["reason"] = reason
            metadata["total_seconds"] = round(time.perf_counter() - total_start, 2)
            metadata["artifacts"] = [str(path.relative_to("/modal-forge"))
                                     for path in sorted(destination.rglob("*")) if path.is_file()]
            report = destination / "report.json"
            metadata["artifacts"].append(str(report.relative_to("/modal-forge")))
            report.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            storage.commit()
            return metadata

        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            source = work / "source"
            # 限制输入体积，避免下载无界文件。
            if image_bytes is not None:
                if len(image_bytes) > 40 * 1024 * 1024:
                    raise ValueError("图片不能超过 40 MiB")
                source.write_bytes(image_bytes)
            else:
                with urllib.request.urlopen(image_url, timeout=45) as response, source.open("wb") as target:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > 40 * 1024 * 1024:
                            raise ValueError("图片不能超过 40 MiB")
                        target.write(chunk)
            with Image.open(source) as original:
                original = ImageOps.exif_transpose(original).convert("RGBA")
            original.save(destination / "source.png")
            manual_mask = Image.open(io.BytesIO(mask_bytes)).convert("L") if mask_bytes is not None else None
            rgba = original
            if manual_mask is not None:
                rgba = prepare_foreground(original, mask=manual_mask)
            elif background != "none" and original.getchannel("A").getextrema()[0] == 255:
                if background not in self.removers:
                    self.removers[background] = BackgroundRemover() if background == "rembg" else RMBG2Remover()
                rgba = prepare_foreground(original, self.removers[background])
            foreground = destination / "foreground.png"
            rgba.save(foreground)
            rgba.getchannel("A").save(destination / "mask.png")
            foreground_preview(rgba).save(destination / "foreground-preview.png")
            metadata["foreground"] = inspect_foreground(rgba, min_fraction=min_foreground)
            if not metadata["foreground"]["accepted"]:
                return finish("rejected", "前景几乎消失：请检查 mask 或明确选择主体，未运行 Shape/Paint")
            shape_input = rgba
            if shape_backend == "2mv":
                shape_input = {"front": rgba}
                for view, data in (view_bytes or {}).items():
                    picture = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
                    if background != "none":
                        if background not in self.removers:
                            self.removers[background] = BackgroundRemover() if background == "rembg" else RMBG2Remover()
                        picture = prepare_foreground(picture, self.removers[background])
                    picture.save(destination / f"{view}-foreground.png")
                    info = inspect_foreground(picture, min_fraction=min_foreground)
                    metadata.setdefault("view_foregrounds", {})[view] = info
                    if not info["accepted"]:
                        return finish("rejected", f"{view} 视图前景几乎消失，未运行 Shape/Paint")
                    shape_input[view] = picture
            self.get_shape(shape_backend)
            metadata["model"] = MODEL if shape_backend == "2.1" else "tencent/Hunyuan3D-2mv"
            from hy3dshape.preprocessors import ImageProcessorV2
            preview_processor = ImageProcessorV2(size=self.shape.image_processor.size,
                border_ratio=self.shape.image_processor.border_ratio)
            condition = preview_processor(rgba, to_tensor=False)
            Image.fromarray(condition["image"]).save(destination / "condition.png")
            Image.fromarray(condition["mask"].squeeze()).save(destination / "condition-mask.png")

            shape_start = time.perf_counter()
            self.shape.to(dtype=torch.float16 if precision == "fp16" else torch.bfloat16)
            for module in self.shape.model.modules():
                if hasattr(module, "upcast_attention"):
                    module.upcast_attention = attention_precision == "fp32"
            for index in range(shape_candidates):
                candidate_seed = (seed + index * 1009) % (2 ** 63 - 1)
                torch.manual_seed(candidate_seed)
                candidate_dir = destination / f"candidate-{index + 1}"
                candidate_dir.mkdir()
                stats = []
                def callback(step, timestep, output):
                    values = output.prev_sample.float()
                    stats.append({"step": step, "min": float(values.min()), "max": float(values.max()),
                                  "finite": bool(torch.isfinite(values).all())})
                try:
                    candidate = self.shape(image=shape_input, num_inference_steps=steps,
                                           callback=callback, callback_steps=1)[0]
                    row = inspect_mesh(candidate, allow_box_like=allow_box_like, allow_flat=allow_flat)
                    row.update({"index": index + 1, "seed": candidate_seed, "latents": stats})
                    if candidate is not None and np.isfinite(candidate.vertices).all() and len(candidate.faces):
                        candidate.export(candidate_dir / "shape.glb")
                        row.update(render_shape(candidate, condition["mask"], candidate_dir))
                    # A silhouette score ranks candidates; it never overrules a collapse flag.
                    row["score"] = row.get("silhouette_iou", 0.0)
                    if row["score"] < min_silhouette_iou:
                        row["accepted"] = False
                        row["issues"].append("silhouette_mismatch")
                    metadata["shape_candidates"].append(row)
                except FloatingPointError as error:
                    metadata["shape_candidates"].append({"index": index + 1, "seed": candidate_seed,
                        "accepted": False, "issues": ["non_finite_inference"], "error": str(error), "latents": stats})
                except Exception as error:
                    metadata["error"] = repr(error)
                    return finish("failed", "Shape 或预览执行出错；请查看 report.json，未运行 Paint")
            torch.cuda.synchronize()
            shape_seconds = time.perf_counter() - shape_start
            metadata["shape_seconds"] = round(shape_seconds, 2)
            selected = select_candidate(metadata["shape_candidates"])
            if selected is None:
                return finish("rejected", "所有 Shape 候选均未通过几何检查，未运行 Paint；请查看保留的原始网格和预览")
            import trimesh
            shape_glb = destination / f"candidate-{selected['index']}" / "shape.glb"
            mesh = trimesh.load(shape_glb, force="mesh", process=False)
            metadata.update({"selected_candidate": selected["index"], "selected_seed": selected["seed"],
                             "vertices": len(mesh.vertices), "faces": len(mesh.faces)})
            result = shape_glb
            paint_seconds = 0.0

            if paint:
                from convert_utils import create_glb_with_pbr_materials

                pipeline = self.get_paint(views, resolution)
                paint_start = time.perf_counter()
                obj = Path(pipeline(
                    mesh_path=str(shape_glb), image_path=str(foreground),
                    output_mesh_path=str(work / "textured.obj"), save_glb=False,
                ))
                textures = {
                    "albedo": str(obj.with_suffix(".jpg")),
                    "metallic": str(obj.with_name(obj.stem + "_metallic.jpg")),
                    "roughness": str(obj.with_name(obj.stem + "_roughness.jpg")),
                }
                for texture in textures.values():
                    if not Path(texture).is_file():
                        raise RuntimeError(f"缺少 Paint 纹理：{texture}")
                result = work / "textured.glb"
                create_glb_with_pbr_materials(str(obj), textures, str(result))
                torch.cuda.synchronize()
                paint_seconds = time.perf_counter() - paint_start

            material = check_glb(result, require_pbr=paint)
            shutil.copy2(result, destination / "output.glb")
            metadata.update({"glb": material, "paint_seconds": round(paint_seconds, 2),
                             "path": str((destination / "output.glb").relative_to("/modal-forge"))})
            if paint:
                from DifferentiableRenderer.mesh_io import load_mesh_file
                final_mesh = load_mesh_file(destination / "output.glb", force="mesh", process=False)
                render_shape(final_mesh, condition["mask"], destination / "textured-preview", textured=True)
            return finish("completed")


@app.local_entrypoint()
def main(
    image_url: str = "", image_path: str = "", paint: bool = True, run_gpu: bool = False,
    name: str = "sample", steps: int = 50, seed: int = 42, views: int = 6,
    resolution: int = 512, output_dir: str = "outputs",
    mask_path: str = "", background: str = "rembg", shape_candidates: int = 1,
    precision: str = "fp16", allow_box_like: bool = False, allow_flat: bool = False,
    min_foreground: float = .01,
    attention_precision: str = "native",
    shape_backend: str = "2.1", left_path: str = "", back_path: str = "", right_path: str = "",
    hf_secret: str = "",
    min_silhouette_iou: float = .75,
):
    """默认仅预览；明确传 --run-gpu 才触发付费推理。"""
    if not run_gpu:
        print("预览模式：指定 --run-gpu --image-url URL 后执行推理")
        return
    if bool(image_url) == bool(image_path):
        raise ValueError("必须且只能指定 --image-url 或 --image-path 其中之一")
    image_bytes = None
    if image_path:
        path = Path(image_path)
        if path.stat().st_size > 40 * 1024 * 1024:
            raise ValueError("图片不能超过 40 MiB")
        image_bytes = path.read_bytes()
    import os
    secrets = []
    if hf_secret:
        secrets = [modal.Secret.from_name(hf_secret)]
    elif background == "rmbg2" and os.environ.get("HF_TOKEN"):
        secrets = [modal.Secret.from_dict({"HF_TOKEN": os.environ["HF_TOKEN"]})]
    service = Hunyuan3D.with_options(secrets=secrets)() if secrets else Hunyuan3D()
    result = service.generate.remote(
        image_url, name=name, paint=paint, steps=steps, seed=seed, views=views,
        resolution=resolution, image_bytes=image_bytes,
        mask_bytes=Path(mask_path).read_bytes() if mask_path else None,
        background=background, shape_candidates=shape_candidates, precision=precision,
        allow_box_like=allow_box_like, allow_flat=allow_flat, min_foreground=min_foreground,
        attention_precision=attention_precision,
        min_silhouette_iou=min_silhouette_iou,
        shape_backend=shape_backend,
        view_bytes={key: Path(path).read_bytes() for key, path in (
            ("left", left_path), ("back", back_path), ("right", right_path)) if path} or None,
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for remote_file in result["artifacts"]:
        local_file = destination / Path(remote_file).relative_to("001-Hunyuan3D-2.1/outputs")
        local_file.parent.mkdir(parents=True, exist_ok=True)
        with local_file.open("wb") as target:
            for chunk in storage.read_file(remote_file):
                target.write(chunk)
        print(f"已下载：{local_file.resolve()}")
    print(json.dumps({key: result.get(key) for key in (
        "status", "path", "reason", "selected_seed", "total_seconds")}, ensure_ascii=False, indent=2))
