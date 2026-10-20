"""Render the actual batch GLBs, including geometry-only views and source images."""
import json
import ctypes
from pathlib import Path

import numpy as np
import pyrender
import trimesh
from PIL import Image, ImageDraw
from OpenGL.raw.GL.VERSION.GL_1_1 import glGenTextures as raw_gl_gen_textures

# PyOpenGL 3.1.0's convenience wrapper has a ctypes/Python 3.12 incompatibility.
def gen_textures(count):
    names = (ctypes.c_uint * count)()
    raw_gl_gen_textures(count, names)
    return int(names[0]) if count == 1 else np.array(names)

pyrender.texture.glGenTextures = gen_textures

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "outputs/t008-t016/inspection"
DEST.mkdir(exist_ok=True)
SIZE = 360


def pose(direction, center, distance):
    z = np.array(direction, dtype=float)
    z /= np.linalg.norm(z)
    x = np.cross([0, 1, 0], z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    result = np.eye(4)
    result[:3, :3] = np.column_stack((x, y, z))
    result[:3, 3] = center + z * distance
    return result


def render(renderer, mesh, direction, gray):
    scene = pyrender.Scene(bg_color=[0.94, 0.95, 0.97, 1], ambient_light=[0.45] * 3)
    material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=[0.6, 0.67, 0.78, 1], metallicFactor=0, roughnessFactor=0.8,
    ) if gray else None
    scene.add(pyrender.Mesh.from_trimesh(mesh, material=material, smooth=False))
    camera_pose = pose(direction, mesh.bounds.mean(0), max(mesh.extents) * 2.1)
    scene.add(pyrender.PerspectiveCamera(yfov=np.pi / 4), pose=camera_pose)
    scene.add(pyrender.DirectionalLight(color=np.ones(3), intensity=2.5), pose=camera_pose)
    pixels, depth = renderer.render(scene, flags=pyrender.RenderFlags.SKIP_CULL_FACES)
    return Image.fromarray(pixels)


def main():
    renderer = pyrender.OffscreenRenderer(SIZE, SIZE)
    metrics = []
    try:
        for start in (8, 11, 14):
            sheet = Image.new("RGB", (SIZE * 4, (SIZE + 38) * 3), "white")
            draw = ImageDraw.Draw(sheet)
            for row, idx in enumerate(range(start, start + 3)):
                name = f"t{idx:03d}"
                mesh = trimesh.load(str(ROOT / f"outputs/t008-t016/{name}.glb"), force="mesh", process=False)
                components = sorted(mesh.split(only_watertight=False), key=lambda part: part.area, reverse=True)
                aligned = np.max(np.abs(mesh.face_normals), axis=1) > 0.999
                item = {"name": name, "vertices": len(mesh.vertices), "faces": len(mesh.faces),
                        "extents": mesh.extents.tolist(), "watertight": bool(mesh.is_watertight),
                        "components": len(components),
                        "largest_component_area_ratio": float(components[0].area / mesh.area),
                        "axis_aligned_area_ratio": float(mesh.area_faces[aligned].sum() / mesh.area)}
                metrics.append(item)
                print(json.dumps(item), flush=True)
                source = Image.open(Path("D:/Users/yuminghui/Downloads/pic") / f"{name}.jpg").convert("RGB")
                source.thumbnail((SIZE, SIZE))
                images = [source, render(renderer, mesh, (0, .1, 1), True),
                          render(renderer, mesh, (1, .15, .1), True),
                          render(renderer, mesh, (1, .3, 1), False)]
                for col, (label, picture) in enumerate(zip(("INPUT", "GEOMETRY FRONT", "GEOMETRY SIDE", "TEXTURED 3/4"), images)):
                    left, top = col * SIZE, row * (SIZE + 38)
                    draw.text((left + 8, top + 8), f"{name} {label}", fill="black")
                    sheet.paste(picture, (left + (SIZE - picture.width) // 2, top + 30))
                images[3].save(DEST / f"{name}-textured.png")
            sheet.save(DEST / f"contact-{start:03d}-{start+2:03d}.png")
    finally:
        renderer.delete()
    (DEST / "geometry.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
