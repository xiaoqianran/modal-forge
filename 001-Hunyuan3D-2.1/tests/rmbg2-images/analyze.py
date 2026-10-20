from PIL import Image
import numpy as np,json
from pathlib import Path
p=Path('tests/rmbg2-images')
a=np.asarray(Image.open(p/'original.png').convert('RGBA'))[:,:,3]
b=np.asarray(Image.open(p/'rmbg2.png').convert('RGBA'))[:,:,3]
print('size',a.shape)
for name,x in [('original',a),('rmbg2',b)]:
 print(name, 'opaque',np.mean(x==255), 'clear',np.mean(x==0),'transition',np.mean((x>0)&(x<255)), 'alpha>127',np.mean(x>127),'mean',np.mean(x))
 for region,arr in [('bottom_20pct',x[400:,:]),('bottom_35pct',x[325:,:]),('top_20pct',x[:100,:]),('side_10pct',np.concatenate([x[:,:50].ravel(),x[:,-50:].ravel()]))]:
  print(' ',region,'opaque',np.mean(arr>127),'avg_alpha',np.mean(arr))
print('mean_abs_alpha_difference',np.abs(a.astype(int)-b.astype(int)).mean())
print('binary_IoU',np.logical_and(a>127,b>127).sum()/np.logical_or(a>127,b>127).sum())
print('original_only',np.mean((a>127)&(b<=127)),'rmbg2_only',np.mean((b>127)&(a<=127)))
for name,x in [('original',a),('rmbg2',b)]:
 inds=np.where(x>127)
 print(name, 'bbox', tuple(map(int,(inds[1].min(),inds[0].min(),inds[1].max(),inds[0].max()))))

