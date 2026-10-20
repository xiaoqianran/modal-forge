"""Sequential t008..t016 local image -> Modal Shape+Paint -> GLB."""
import json
import traceback
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as production

SOURCE = Path(r"D:\Users\yuminghui\Downloads\pic")
DEST = ROOT / "outputs" / "t008-t016"
NAMES = [f"t{i:03d}" for i in range(8, 17)]

def main():
    DEST.mkdir(parents=True, exist_ok=True)
    results = []
    with production.app.run():
        worker = production.Hunyuan3D()
        for idx, name in enumerate(NAMES, 1):
            source = SOURCE / f"{name}.jpg"
            print(f"=== [{idx}/9] {name}: START ===", flush=True)
            row = {"name": name, "source": str(source), "status": "failed"}
            try:
                result = worker.generate.remote(
                    image_bytes=source.read_bytes(), name=name,
                    paint=True, seed=42, steps=50, views=6, resolution=512,
                )
                for suffix in (".glb", ".json"):
                    remote_file = str(Path(result["path"]).with_suffix(suffix)).replace("\\", "/")
                    target = DEST / f"{name}{suffix}"
                    with target.open("wb") as stream:
                        for chunk in production.storage.read_file(remote_file):
                            stream.write(chunk)
                    if target.stat().st_size == 0:
                        raise RuntimeError(f"Empty output: {target}")
                row.update(status="ok", result=result, local_glb=str(DEST / f"{name}.glb"))
                print(f"=== [{idx}/9] {name}: OK ({result['total_seconds']} s) ===",flush=True)
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                print(f"=== [{idx}/9] {name}: ERROR {row['error']} ===",flush=True)
                traceback.print_exc()
            results.append(row)
            (DEST / "batch_report.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FINAL",json.dumps([{"name":r["name"],"status":r["status"],"error":r.get("error")} for r in results],ensure_ascii=False))
if __name__ == "__main__":
    main()



