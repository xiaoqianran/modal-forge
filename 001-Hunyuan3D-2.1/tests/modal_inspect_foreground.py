"""Recreate the deployed preprocessing without running Shape or Paint."""
import io
import json
import sys
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as production

app = modal.App("hunyuan3d-foreground-quality-inspection")


@app.function(image=production.image.add_local_file(ROOT / "app.py", "/root/app.py"), cpu=4, memory=8192, timeout=600,
              volumes={"/modal-forge": production.storage})
def inspect_foregrounds(items):
    from PIL import Image
    import numpy as np
    from hy3dshape.rembg import BackgroundRemover, prepare_foreground
    remover = BackgroundRemover()
    results = []
    for name, content in items:
        image = Image.open(io.BytesIO(content))
        foreground = prepare_foreground(image, remover)
        alpha = np.asarray(foreground.getchannel("A"))
        buf = io.BytesIO()
        foreground.save(buf, format="PNG")
        results.append({"name": name, "png": buf.getvalue(),
                        "foreground_fraction": float((alpha > 127).mean()),
                        "alpha_bbox": foreground.getchannel("A").getbbox()})
    return results


@app.local_entrypoint()
def main():
    items = [(f"t{idx:03d}", (Path("D:/Users/yuminghui/Downloads/pic") / f"t{idx:03d}.jpg").read_bytes())
             for idx in range(8, 17)]
    output = ROOT / "outputs/t008-t016/inspection"
    output.mkdir(exist_ok=True)
    rows = inspect_foregrounds.remote(items)
    for row in rows:
        (output / (row["name"] + "-foreground.png")).write_bytes(row.pop("png"))
    (output / "foreground.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))
