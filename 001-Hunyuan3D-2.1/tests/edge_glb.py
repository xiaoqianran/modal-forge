"""Adversarial GLB exporter regression cases against the actual fork function."""
import base64
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image
import pygltflib
import trimesh
from compare_glb import make_fixture, inspect
from convert_utils import create_glb_with_pbr_materials

def texture_map(root):
    return {k: str(root / fn) for k, fn in {
        "albedo":"mesh.jpg", "metallic":"mesh_metallic.jpg", "roughness":"mesh_roughness.jpg"}.items()}

def single(root):
    obj=make_fixture(root)
    target=root/"simple.glb"
    os.chdir(root)
    create_glb_with_pbr_materials(str(obj), texture_map(root), str(target))
    gltf=pygltflib.GLTF2().load(str(target))
    uri=gltf.images[0].uri
    return {"glb":inspect(target), "declared_uri":uri.split(",")[0] if uri else None,
        "actual_header":base64.b64decode(uri.split(",")[1])[:3].hex() if uri else None}

def absent(root):
    obj=make_fixture(root)
    args=texture_map(root)
    args["roughness"]=None
    try:
        create_glb_with_pbr_materials(str(obj), args, str(root/"missing.glb"))
        return {"unexpected_success":True}
    except Exception as e:
        return {"error":f"{type(e).__name__}: {e}"}

def extra_mesh(root):
    obj=make_fixture(root)
    # Multiple independent OBJ objects often get collapsed by trimesh's default loading.
    # Export a two-mesh GLB first to demonstrate what the helper's first-mesh-only
    # assignment would mean, and report whether the actual OBJ path yields >1 meshes.
    p=root/"multi.obj"
    text=obj.read_text()
    text += "\no Second\nv 0 0 1\nv 1 0 1\nv 0 1 1\nusemtl TestMaterial\nf 4/1 5/2 6/3\n"
    p.write_text(text)
    for suffix in (".jpg","_metallic.jpg","_roughness.jpg"):
        (root/("multi"+suffix)).write_bytes((root/("mesh"+suffix)).read_bytes())
    (root/"multi.mtl").write_text((root/"mesh.mtl").read_text().replace("mesh.","multi."))
    p.write_text(p.read_text().replace("mtllib mesh.mtl","mtllib multi.mtl"))
    target=root/"multi.glb"
    create_glb_with_pbr_materials(str(p),{k:v.replace("mesh.","multi.").replace("mesh_","multi_") for k,v in texture_map(root).items()},str(target))
    g=pygltflib.GLTF2().load(str(target))
    return {"mesh_count":len(g.meshes),"materials":[[pr.material for pr in m.primitives] for m in g.meshes]}

def fixed_paths(root):
    root.mkdir(parents=True,exist_ok=True)
    obj=make_fixture(root)
    os.chdir(root)
    create_glb_with_pbr_materials(str(obj),texture_map(root),str(root/"one.glb"))
    return {"temp_glb_exists":(root/"temp.glb").exists(),
        "mr_combined_exists":(root/"mr_combined.png").exists(),
        "paths_are_shared":True}

def run():
    results={}
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        for key,fn in (("simple",single),("missing",absent),("multiple",extra_mesh),("fixed_temp",fixed_paths)):
            folder=root/key;folder.mkdir()
            try: results[key]=fn(folder)
            except Exception as e: results[key]={"error":f"{type(e).__name__}: {e}"}
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return results

if __name__=="__main__":
    run()
