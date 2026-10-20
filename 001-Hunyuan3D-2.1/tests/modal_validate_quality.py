"""Exercise real Modal preprocessing, candidate rejection, selection and PBR export."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as production

app = production.app


@app.local_entrypoint()
def validate(all_cases: bool = False, remaining_only: bool = False):
    service = production.Hunyuan3D()
    destination = ROOT / "outputs/quality-fixes/end-to-end"
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    cases = (
        ("t011-mask-check", Path("D:/Users/yuminghui/Downloads/pic/t011.jpg"), dict(paint=False)),
        ("t009-best-of-3", Path("D:/Users/yuminghui/Downloads/pic/t009.jpg"), dict(paint=False, shape_candidates=3)),
        ("penguin-pbr", ROOT / "modal-forge-Hunyuan3D-2.1/assets/demo.png", dict(paint=True)),
        ("t011-sam3-glass", Path("D:/Users/yuminghui/Downloads/pic/t011.jpg"),
         dict(paint=True, mask_bytes=(ROOT / "outputs/quality-fixes/sam3-t011/mask.png").read_bytes())),
    )
    remaining = tuple((f"t{index:03d}-regression", Path(f"D:/Users/yuminghui/Downloads/pic/t{index:03d}.jpg"),
                      dict(paint=False)) for index in (8, 10, 12, 13, 14, 15, 16))
    if remaining_only:
        cases = remaining
    elif all_cases:
        cases += remaining
    for name, source, options in cases:
        result = service.generate.remote(image_bytes=source.read_bytes(), name=name, **options)
        rows.append(result)
        print(json.dumps({key: result.get(key) for key in (
            "status", "path", "reason", "selected_seed", "total_seconds")}, ensure_ascii=False), flush=True)
        summary_name = "summary-remaining.json" if remaining_only else "summary.json"
        (destination / summary_name).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        for remote in result["artifacts"]:
            path = destination / Path(remote).relative_to("001-Hunyuan3D-2.1/outputs")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as target:
                for chunk in production.storage.read_file(remote):
                    target.write(chunk)
    if remaining_only:
        assert all(row["status"] != "failed" for row in rows), "An inference/rendering stage failed"
        return
    assert rows[0]["status"] == "rejected" and not rows[0]["shape_candidates"]
    assert rows[1]["status"] == "rejected", rows[1]
    assert rows[2]["status"] == "completed", rows[2]
    assert rows[2]["glb"]["base_color"] and rows[2]["glb"]["metallic_roughness"]
    assert rows[3]["status"] == "completed", rows[3]
    assert all(row["status"] != "failed" for row in rows), "An inference/rendering stage failed"
    print("Quality validation passed; visual review of saved previews is still required.")
