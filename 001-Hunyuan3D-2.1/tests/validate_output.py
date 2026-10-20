"""Validate a downloaded production PBR GLB independently of app.py.

uv run --with trimesh==4.4.7 --with numpy --with pillow --with pygltflib python tests/validate_output.py outputs/model.glb
"""
import base64
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from pygltflib import GLTF2


def validate(path):
    gltf = GLTF2().load(str(path))
    scene = trimesh.load(str(path), force="scene", process=False)
    if not scene.geometry:
        raise ValueError("GLB has no geometry")
    vertices = faces = 0
    for mesh in scene.geometry.values():
        if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
            raise ValueError("GLB contains an empty mesh")
        if not np.isfinite(mesh.vertices).all():
            raise ValueError("GLB contains nonfinite vertices")
        if mesh.visual.uv is None or not np.isfinite(mesh.visual.uv).all():
            raise ValueError("GLB has no valid UV coordinates")
        vertices += len(mesh.vertices)
        faces += len(mesh.faces)

    for mesh in gltf.meshes:
        for primitive in mesh.primitives:
            if primitive.material is None:
                raise ValueError("Primitive has no material")
            pbr = gltf.materials[primitive.material].pbrMetallicRoughness
            if pbr is None or pbr.baseColorTexture is None or pbr.metallicRoughnessTexture is None:
                raise ValueError("Material is missing PBR textures")
            for reference in (pbr.baseColorTexture, pbr.metallicRoughnessTexture):
                source = gltf.textures[reference.index].source
                if source is None or not 0 <= source < len(gltf.images):
                    raise ValueError("Broken texture image reference")

    images = []
    for item in gltf.images:
        if item.uri is not None:
            if not item.uri.startswith("data:image/"):
                raise ValueError("GLB references an external texture")
            raw = base64.b64decode(item.uri.split(",", 1)[1])
        else:
            view = gltf.bufferViews[item.bufferView]
            offset = view.byteOffset or 0
            raw = gltf.binary_blob()[offset:offset + view.byteLength]
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            images.append({"format": image.format, "size": list(image.size),
                           "mode": image.mode, "extrema": image.getextrema()})

    return {"valid": True, "file": path.name, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "vertices": vertices, "faces": faces, "meshes": len(gltf.meshes),
            "materials": len(gltf.materials), "images": images}


if __name__ == "__main__":
    path = Path(sys.argv[1])
    report = validate(path)
    output = path.with_suffix(".validation.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
