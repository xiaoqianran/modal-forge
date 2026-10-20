import numpy as np,trimesh,json
from pathlib import Path
p=Path("tests/shape-ab-local")
res={}
for name in ("original","rmbg2"):
 m=trimesh.load(p/(name+".glb"),force="mesh")
 f=np.asarray(m.faces)
 edges=np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[0,2]]]),axis=1)
 e,c=np.unique(edges,axis=0,return_counts=True)
 deg=np.count_nonzero((f[:,0]==f[:,1])|(f[:,1]==f[:,2])|(f[:,0]==f[:,2]))
 print(name, "nonmanifold edges",int((c>2).sum()),"boundary edges",int((c==1).sum()),"degenerate face indices",int(deg),"is_winding_consistent",m.is_winding_consistent,"is_volume",m.is_volume)
 res[name]={"nonmanifold_edges":int((c>2).sum()),"boundary_edges":int((c==1).sum()),"degenerate_index_faces":int(deg),"winding_consistent":bool(m.is_winding_consistent)}
(p/"topology_diagnostics.json").write_text(json.dumps(res,indent=2),encoding="utf-8")

