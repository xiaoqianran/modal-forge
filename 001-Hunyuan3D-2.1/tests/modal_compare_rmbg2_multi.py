"""Three-image RMBG comparison, no production changes."""
from pathlib import Path
import json,time,modal
ROOT=Path(__file__).resolve().parents[1]
NAMES=("004","052","073")
app=modal.App("hunyuan3d-rmbg2-multi")
storage=modal.Volume.from_name("modal-forge",create_if_missing=True)
image=(modal.Image.debian_slim(python_version="3.10")
 .apt_install("libgl1","libglib2.0-0")
 .pip_install("torch==2.5.1","torchvision==0.20.1","transformers==4.44.2",
 "timm==1.0.11","huggingface_hub==0.26.2","pillow==10.4.0",
 "rembg==2.0.65","onnxruntime==1.19.2","numpy==1.26.4","kornia==0.7.4"))
for name in NAMES:
 image=image.add_local_file(str(ROOT/"modal-forge-Hunyuan3D-2.1"/"assets"/"example_images"/(name+".png")),
                            "/opt/input/"+name+".png",copy=True)
@app.function(image=image,gpu="L40S",timeout=1200,
 secrets=[modal.Secret.from_name("huggingface-secret")],volumes={"/modal-forge":storage})
def run():
 import os,torch,numpy as np
 from PIL import Image
 from rembg import new_session,remove
 from transformers import AutoModelForImageSegmentation
 from torchvision import transforms
 token=next((os.getenv(k) for k in ("HF_TOKEN","HUGGINGFACE_HUB_TOKEN","HUGGING_FACE_HUB_TOKEN") if os.getenv(k)),None)
 if not token:raise RuntimeError("HF token unavailable")
 model=AutoModelForImageSegmentation.from_pretrained("briaai/RMBG-2.0",trust_remote_code=True,token=token).eval().to("cuda")
 tf=transforms.Compose([transforms.Resize((1024,1024)),transforms.ToTensor(),transforms.Normalize([0.5]*3,[1.0]*3)])
 session=new_session()
 base=Path("/modal-forge/001-Hunyuan3D-2.1/tests/rmbg2-multi")
 report={}
 for name in NAMES:
  out=base/name;out.mkdir(parents=True,exist_ok=True)
  source=Image.open("/opt/input/"+name+".png").convert("RGBA")
  white=Image.new("RGBA",source.size,(255,255,255,255))
  white.alpha_composite(source)
  rgb=white.convert("RGB")
  rgb.save(out/"source_white.png")
  t=time.perf_counter()
  original=remove(rgb,session=session).convert("RGBA")
  t_original=time.perf_counter()-t
  original.save(out/"original.png")
  t=time.perf_counter()
  with torch.inference_mode():
   mask=model(tf(rgb).unsqueeze(0).to("cuda"))[-1].sigmoid().cpu()[0].squeeze()
  torch.cuda.synchronize()
  alpha=transforms.ToPILImage()(mask).resize(rgb.size)
  new=rgb.convert("RGBA");new.putalpha(alpha);new.save(out/"rmbg2.png")
  a=np.array(original.getchannel("A"))>127
  b=np.array(alpha)>127
  report[name]={"size":rgb.size,"original_seconds":round(t_original,2),
                "rmbg2_seconds":round(time.perf_counter()-t,2),
                "original_foreground_pct":round(float(a.mean()*100),2),
                "rmbg2_foreground_pct":round(float(b.mean()*100),2),
                "mask_iou":round(float(np.logical_and(a,b).sum()/max(np.logical_or(a,b).sum(),1)),4)}
  storage.commit()
 (base/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 storage.commit()
 return report
@app.local_entrypoint()
def main():
 print(json.dumps(run.remote(),indent=2))

