"""Build review sheets from saved production source/condition/real clay renders."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / "outputs/quality-fixes/end-to-end"
primary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
remaining = json.loads((folder / "summary-remaining.json").read_text(encoding="utf-8"))
rows = sorted(primary[:2] + remaining, key=lambda r: r["artifacts"][0])


def local(remote):
    return folder / Path(remote).relative_to("001-Hunyuan3D-2.1/outputs")


for start in range(0, len(rows), 3):
    sheet = Image.new("RGB", (1280, 310 * len(rows[start:start + 3])), "white")
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows[start:start + 3]):
        directory = local(row["artifacts"][-1]).parent
        source = Image.open(directory / "source.png").convert("RGB")
        source.thumbnail((250, 270))
        y = index * 310
        sheet.paste(source, ((256 - source.width) // 2, y + 30))
        previews = list(directory.glob("candidate-1/shape-preview.png"))
        if previews:
            picture = Image.open(previews[0]).convert("RGB")
        else:
            picture = Image.open(directory / "foreground-preview.png").convert("RGB")
            picture.thumbnail((1024, 270))
        sheet.paste(picture, (256, y + 30))
        draw.text((8, y + 6), f"{directory.name.split('_')[0]} | {row['status']}", fill="black")
    path = ROOT / f"outputs/quality-fixes/regression-contact-{start // 3 + 1}.png"
    sheet.save(path)
    print(path)
