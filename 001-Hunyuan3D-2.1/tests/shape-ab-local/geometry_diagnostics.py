import numpy as np, trimesh, json
from pathlib import Path
root=Path("tests/shape-ab-local")
out={}
for name in ("original","rmbg2"):
 m=trimesh.load(root/(name+".glb"),force="mesh")
 parts=sorted(m.split(only_watertight=False),key=lambda z:len(z.faces),reverse=True)
 item=[]
 for i,c in enumerate(parts):
  v=np.asarray(c.vertices)
  item.append({"index":i,"faces":len(c.faces),"center":np.round(c.centroid,5).tolist(),"bounds":np.round(c.bounds,5).tolist(),"extent":np.round(c.extents,5).tolist(),"watertight":bool(c.is_watertight)})
 faces=np.sort(np.asarray(m.faces),axis=1)
 edges=np.sort(np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[0,2]]]),axis=1)
 uniq,counts=np.unique(edges,axis=0,return_counts=True)
 boundary=uniq[counts==1]
 bv=np.unique(boundary)
 out[name]={"parts":item,"boundary_edge_count":len(boundary),"boundary_vertex_count":len(bv),"boundary_bounds":np.round(m.vertices[bv].min(axis=0),5).tolist()+np.round(m.vertices[bv].max(axis=0),5).tolist() if len(bv) else None}
 print(name,json.dumps(out[name]))
(root/"geometry_diagnostics.json").write_text(json.dumps(out,indent=2),encoding="utf-8")

