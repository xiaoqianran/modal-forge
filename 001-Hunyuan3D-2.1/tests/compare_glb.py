"""Compare the existing PR #215 and PR #163 GLB converters on the same OBJ.

Run from the outer project: uv run --with trimesh --with pygltflib --with pillow --with numpy --with opencv-python python tests/compare_glb.py
Does not load Hunyuan weights or touch the Modal app.py entrypoint.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORK = Path(os.environ.get("HY3D_TEST_REPO", str(ROOT / "modal-forge-Hunyuan3D-2.1")))
sys.path.insert(0, str(FORK / "hy3dpaint"))

def make_fixture(folder: Path) -> Path:
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (205, 70, 30)).save(folder / "mesh.jpg")
    Image.new("L", (16, 16), 190).save(folder / "mesh_metallic.jpg")
    Image.new("L", (16, 16), 80).save(folder / "mesh_roughness.jpg")
    (folder / "mesh.mtl").write_text(
        "newmtl TestMaterial\n"
        "Kd 1 1 1\nmap_Kd mesh.jpg\nmap_Pm mesh_metallic.jpg\nmap_Pr mesh_roughness.jpg\n",
        encoding="utf-8",
    )
    obj = folder / "mesh.obj"
    obj.write_text(
        "mtllib mesh.mtl\no TestMesh\n"
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 0 1\n"
        "usemtl TestMaterial\nf 1/1 2/2 3/3\n",
        encoding="utf-8",
    )
    return obj

def inspect(path: Path) -> dict:
    import pygltflib
    from PIL import Image
    from io import BytesIO
    import base64

    gltf = pygltflib.GLTF2().load(str(path))
    report = {
        "exists": path.is_file(), "bytes": path.stat().st_size,
        "meshes": len(gltf.meshes), "materials": len(gltf.materials),
        "images": len(gltf.images), "uv": False, "base_color": False,
        "metallic_roughness": False, "mr_channel_pixel": None,
    }
    for mesh in gltf.meshes:
        for prim in mesh.primitives:
            report["uv"] |= prim.attributes.TEXCOORD_0 is not None
    if gltf.materials:
        pbr = gltf.materials[0].pbrMetallicRoughness
        if pbr:
            report["base_color"] = pbr.baseColorTexture is not None
            report["metallic_roughness"] = pbr.metallicRoughnessTexture is not None
            if pbr.metallicRoughnessTexture:
                ti = pbr.metallicRoughnessTexture.index
                source = gltf.textures[ti].source
                im = gltf.images[source]
                raw = None
                if im.uri and im.uri.startswith("data:"):
                    raw = base64.b64decode(im.uri.partition(",")[2])
                elif im.bufferView is not None:
                    blob = gltf.binary_blob()
                    view = gltf.bufferViews[im.bufferView]
                    raw = blob[view.byteOffset:view.byteOffset + view.byteLength]
                if raw:
                    img = Image.open(BytesIO(raw)).convert("RGB")
                    report["mr_channel_pixel"] = list(img.getpixel((0, 0)))
    return report

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="Keep fixture and GLB results in this directory")
    args = parser.parse_args()
    scratch = tempfile.TemporaryDirectory() if args.output is None else None
    folder = args.output.resolve() if args.output else Path(scratch.name)
    folder.mkdir(parents=True, exist_ok=True)
    obj = make_fixture(folder)
    results = {}

    from DifferentiableRenderer.mesh_utils import _convert_obj_to_glb_trimesh
    from convert_utils import create_glb_with_pbr_materials

    for name in ("pr215", "pr163"):
        target = folder / f"{name}.glb"
        try:
            if name == "pr215":
                ok = _convert_obj_to_glb_trimesh(str(obj), str(target))
                if not ok:
                    raise RuntimeError("converter returned False")
            else:
                # The exact function PR #163 calls; deliberately use a separate cwd so
                # its fixed temporary filenames never touch the project working tree.
                import os
                old_cwd = Path.cwd()
                try:
                    os.chdir(folder)
                    create_glb_with_pbr_materials(
                        str(obj),
                        {"albedo": str(folder / "mesh.jpg"),
                         "metallic": str(folder / "mesh_metallic.jpg"),
                         "roughness": str(folder / "mesh_roughness.jpg")},
                        str(target),
                    )
                finally:
                    os.chdir(old_cwd)
            results[name] = inspect(target)
        except Exception as exc:
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}

    print(json.dumps(results, indent=2, ensure_ascii=False))
    if scratch:
        scratch.cleanup()
    return 0 if all(
        r.get("uv") and r.get("base_color") and r.get("metallic_roughness")
        for r in results.values()
    ) else 1

if __name__ == "__main__":
    raise SystemExit(main())

