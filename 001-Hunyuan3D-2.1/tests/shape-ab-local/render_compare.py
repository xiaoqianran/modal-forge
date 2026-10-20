import numpy as np,trimesh,matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
p=Path("tests/shape-ab-local")
fig=plt.figure(figsize=(13,9))
for col,name in enumerate(("original","rmbg2")):
 m=trimesh.load(p/(name+".glb"),force="mesh")
 parts=sorted(m.split(only_watertight=False),key=lambda k:len(k.faces),reverse=True)
 rng=np.random.default_rng(42)
 for row,(elev,azim) in enumerate(((17,40),(5,135))):
  ax=fig.add_subplot(2,2,row*2+col+1,projection="3d")
  for j,part in enumerate(parts):
   f=np.asarray(part.faces);v=np.asarray(part.vertices)
   take=rng.choice(len(f),size=min(len(f),15000),replace=False)
   pts=v[f[take]].mean(axis=1)
   ax.scatter(pts[:,0],pts[:,1],pts[:,2],s=0.12 if j==0 else 2,
       c="#8d9bb3" if j==0 else "#fa4828",alpha=.3 if j==0 else .95,rasterized=True)
  ax.set(xlim=(-.75,.75),ylim=(-1,1),zlim=(-.65,.65),
         xlabel="X",ylabel="Y",zlabel="Z")
  ax.view_init(elev=elev,azim=azim)
  ax.set_box_aspect((1.5,2,1.3))
  ax.set_title(name+" view "+str(row+1))
fig.tight_layout()
fig.savefig(p/"shape_ab_views.png",dpi=170)
print("Saved",p/"shape_ab_views.png")

