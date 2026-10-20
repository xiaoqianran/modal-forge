"""Optional SAM3 subject masks on Modal, isolated from Shape's PyTorch 2.5 stack.

Based on photo-to-mesh's text-prompt segmentation, with explicit no-match errors.
Official SAM3 weights require Hugging Face access; no third-party mirror fallback.
"""
import io
import json
import hashlib
import os
from pathlib import Path

import modal

SAM3_COMMIT = "7f473cfd983d5eb43040ff608f66bff0d7bdcb53"
SAM3_WEIGHTS = "3c879f39826c281e95690f02c7821c4de09afae7"
BASE = "/modal-forge/001-Hunyuan3D-2.1"
storage = modal.Volume.from_name("modal-forge", create_if_missing=True)
app = modal.App("modal-forge-hunyuan-subject-mask")
image = (
    modal.Image.from_registry("nvidia/cuda:12.6.3-runtime-ubuntu22.04", add_python="3.12")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .uv_pip_install("torch==2.7.1", "torchvision==0.22.1",
                    index_url="https://download.pytorch.org/whl/cu126")
    .uv_pip_install(f"git+https://github.com/facebookresearch/sam3.git@{SAM3_COMMIT}",
                    "einops", "pillow", "pycocotools", "decord", "psutil", "scipy",
                    "opencv-python-headless<4.12")
    .env({"HF_HOME": BASE + "/weights/hf-sam3"})
)


@app.cls(image=image, gpu="L40S", cpu=4, memory=32768, timeout=1200,
         scaledown_window=60, volumes={"/modal-forge": storage})
class SubjectMask:
    @modal.enter()
    def load(self):
        from sam3.model_builder import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor
        from huggingface_hub import hf_hub_download
        try:
            checkpoint = hf_hub_download("facebook/sam3", "sam3.pt", revision=SAM3_WEIGHTS)
            self.processor = Sam3Processor(build_sam3_image_model(checkpoint_path=checkpoint, load_from_HF=False))
        except OSError as error:
            raise RuntimeError("SAM3 权重不可用：需先获得 facebook/sam3 访问权限并提供 HF_TOKEN；未回退整图 mask") from error
        storage.commit()

    @modal.method()
    def segment(self, content: bytes, subject: str, min_score: float = .3):
        import numpy as np
        import torch
        from PIL import Image, ImageOps
        if not subject.strip() or not 0 <= min_score <= 1:
            raise ValueError("subject 必须非空，min_score 必须为 0–1")
        if len(content) > 40 * 1024 * 1024:
            raise ValueError("图片不能超过 40 MiB")
        original = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            state = self.processor.set_image(original)
            result = self.processor.set_text_prompt(state=state, prompt=subject)
        scores = result["scores"].float().cpu().numpy().reshape(-1)
        if not len(scores) or not np.isfinite(scores).all() or float(scores.max()) < min_score:
            raise ValueError("SAM3 没有找到足够可信的主体，请换提示或提供人工 mask；未返回全白 mask")
        masks = result["masks"].float().cpu().numpy()
        selected = masks[int(scores.argmax())].squeeze()
        mask = Image.fromarray((selected > .5).astype(np.uint8) * 255).resize(
            original.size, Image.Resampling.NEAREST)
        if mask.getbbox() is None:
            raise ValueError("SAM3 主体 mask 为空，未继续生成")
        rgba = original.convert("RGBA")
        rgba.putalpha(mask)
        y, x = np.indices((rgba.height, rgba.width))
        gray = np.where((x // 24 + y // 24) % 2, 205, 245).astype(np.uint8)
        checker = Image.fromarray(np.dstack([gray, gray, gray, np.full_like(gray, 255)]), "RGBA")
        preview = Image.alpha_composite(checker, rgba).convert("RGB")
        def png(picture):
            data = io.BytesIO()
            picture.save(data, format="PNG")
            return data.getvalue()
        storage.commit()
        return {"mask": png(mask), "foreground": png(rgba), "preview": png(preview),
                "score": float(scores.max()), "visible_fraction": float((np.array(mask) > 127).mean())}


@app.local_entrypoint()
def main(image_path: str, subject: str, output_dir: str = "masks", run_gpu: bool = False,
         hf_secret: str = "", min_score: float = .3):
    if not run_gpu:
        print("预览模式：添加 --run-gpu 才运行 SAM3。需要 facebook/sam3 模型访问权限。")
        return
    secrets = []
    if hf_secret:
        secrets.append(modal.Secret.from_name(hf_secret))
    elif os.environ.get("HF_TOKEN"):
        secrets.append(modal.Secret.from_dict({"HF_TOKEN": os.environ["HF_TOKEN"]}))
    else:
        raise ValueError("请设置 HF_TOKEN 或 --hf-secret（含 HF_TOKEN 的 Modal Secret）；未启动 SAM3 推理")
    content = Path(image_path).read_bytes()
    result = SubjectMask.with_options(secrets=secrets)().segment.remote(content, subject, min_score)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for key in ("mask", "foreground", "preview"):
        path = destination / f"{key}.png"
        path.write_bytes(result[key])
        print(f"已保存：{path.resolve()}")
    print(f"主体匹配分数：{result['score']:.3f}")
    (destination / "segmentation.json").write_text(json.dumps({
        "subject": subject, "min_score": min_score, "score": result["score"],
        "visible_fraction": result["visible_fraction"], "source_sha256": hashlib.sha256(content).hexdigest(),
        "sam3_commit": SAM3_COMMIT, "weights_revision": SAM3_WEIGHTS,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
