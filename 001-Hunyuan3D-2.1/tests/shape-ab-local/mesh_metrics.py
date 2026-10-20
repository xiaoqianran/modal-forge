import trimesh, numpy as np
from pathlib import Path
for n in ("original","rmbg2"):
 m=trimesh.load(Path("tests/shape-ab-local")/(n+".glb"), force="mesh")
 print("\n",n,"watertight",m.is_watertight,"euler",m.euler_number,"components")
 parts=m.split(only_watertight=False)
 lens=sorted((len(x.faces) for x in parts),reverse=True)
 print("count",len(parts),"largest",lens[:10],"small components",sum(x<100 for x in lens))
 for axis in range(3):
  x=m.vertices[:,axis]
  lo,hi=x.min(),x.max()
  upper=np.mean(x>lo+0.9*(hi-lo));lower=np.mean(x<lo+0.1*(hi-lo))
  print("axis",axis,"low/high vertex shares",round(lower,4),round(upper,4))
