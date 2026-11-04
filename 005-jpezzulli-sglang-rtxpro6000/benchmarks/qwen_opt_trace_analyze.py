"""Analyze one user-owned SGLang Chrome trace locally; no GPU or network calls.

Aggregated kernel durations are NOT equal to exposed critical-path latency.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import re
from pathlib import Path
import sys
import tarfile

BASE=Path(__file__).resolve().parent.parent
NAME="r2_20261104T082923_17439d"
DEFAULT=BASE/"results"/"qwen_optimization"/"traces"/f"{NAME}.tar.gz"
MAX_TRACE_RAW=650*1024**2
FOCUS=("ple","gather","ngram","host","cudaMemcpy","transfer","ram_lookup","uva")


def analyze(path:Path)->dict:
    source_sha=hashlib.sha256(path.read_bytes()).hexdigest()
    names=[]
    with tarfile.open(path,"r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            if not member.name.endswith((".json.gz",".json")):
                continue
            with tar.extractfile(member) as file:
                if member.name.endswith(".gz"):
                    with gzip.GzipFile(fileobj=file) as trace:
                        raw=trace.read(MAX_TRACE_RAW+1)
                else:
                    raw=file.read(MAX_TRACE_RAW+1)
            if len(raw)>MAX_TRACE_RAW:
                raise RuntimeError("SGLang trace too large to safely parse in RAM")
            parsed=json.loads(raw)
            events=parsed.get("traceEvents",[]) if isinstance(parsed,dict) else parsed
            print("TRACE_MEMBER="+member.name+" EVENTS="+str(len(events))+
                  " RAW_BYTES="+str(len(raw)),flush=True)
            names.append((member.name,events,len(raw)))
    categories=Counter()
    device_by_name=defaultdict(lambda:{"count":0,"duration_us":0.0})
    keywords=defaultdict(lambda:{"count":0,"duration_us":0.0})
    keyword_by_category=defaultdict(lambda:defaultdict(lambda:{"count":0,"duration_us":0.0}))
    focus_examples=[]
    trace_events_total=0
    all_names=Counter()
    for filename,events,_ in names:
        for event in events:
            if not isinstance(event,dict):
                continue
            trace_events_total+=1
            cat=str(event.get("cat",""))
            nm=str(event.get("name",""))
            categories[cat]+=1
            all_names[nm[:120]]+=1
            dur=float(event.get("dur") or 0)
            # CUDA graph step/range annotations are not actual kernel launches.
            # Keep only profiler events explicitly categorized as physical kernels.
            if cat == "kernel" and event.get("ph")=="X":
                bucket=device_by_name[nm[:250]]
                bucket["count"]+=1
                bucket["duration_us"]+=dur
            lowercase=nm.lower()
            for keyword in FOCUS:
                hit=(re.search(r"(?<![a-z0-9])ple(?![a-z0-9])",lowercase)
                     if keyword=="ple" else keyword.lower() in lowercase)
                if hit:
                    obj=keywords[keyword]
                    obj["count"]+=1
                    obj["duration_us"]+=dur
                    categorized=keyword_by_category[keyword][cat]
                    categorized["count"]+=1
                    categorized["duration_us"]+=dur
                    if len(focus_examples)<70:
                        focus_examples.append({
                            "name":nm[:350],"cat":cat,"dur_us":dur,
                            "pid":event.get("pid"),"tid":event.get("tid"),
                        })
    top_kernels=[
        {"name":k,"count":v["count"],
         "total_ms":round(v["duration_us"]/1000,3)}
        for k,v in sorted(device_by_name.items(),
                          key=lambda p:p[1]["duration_us"],reverse=True)[:30]
    ]
    ple_kernel_names=[
        {"name":k,"count":v["count"],
         "total_ms":round(v["duration_us"]/1000,3)}
        for k,v in sorted(device_by_name.items(),
                          key=lambda p:p[1]["duration_us"],reverse=True)
        if re.search(r"(?<![a-z0-9])ple(?![a-z0-9])",k.lower())
    ]
    gpu_kernel_serial_ms=sum(x["duration_us"] for x in device_by_name.values())/1000
    return {
        "gpu_kernel_total_serial_ms":round(gpu_kernel_serial_ms,3),
        "top_ple_gpu_kernel_names":ple_kernel_names[:30],
        "archive":str(path),"archive_sha256":source_sha,
        "trace_members":[{"name":n,"raw_bytes":size,"events":len(e)} for n,e,size in names],
        "events":trace_events_total,
        "categories":categories.most_common(40),
        "top_gpu_kernels_by_sum":top_kernels,
        "name_keywords":{k:{"count":v["count"],"sum_ms":round(v["duration_us"]/1000,3)}
                         for k,v in keywords.items()},
        "focus_by_category":{
            k:{cat:{"count":v["count"],"sum_ms":round(v["duration_us"]/1000,3)}
               for cat,v in cats.items()}
            for k,cats in keyword_by_category.items()
        },
        "focus_examples":focus_examples,
        "limits":[
            "GPU kernel total durations can overlap across streams and are not the GPU critical path.",
            "Chrome trace may not expose explicit PLE wait edges, especially inside CUDA graphs.",
            "Torch profiler changes runtime timings; never treat trace workload as serving throughput.",
        ],
    }


def main():
    path=Path(sys.argv[1]) if len(sys.argv)>1 else DEFAULT
    result=analyze(path)
    out=path.with_suffix(".analysis.json")
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print("ANALYSIS_FILE="+str(out))
    print("CATEGORIES="+str(result["categories"][:12]))
    print("FOCUS="+str(result["name_keywords"]))
    print("FOCUS_BY_CATEGORY="+str(result["focus_by_category"]))
    print("SERIAL_SUM_GPU_KERNEL_MS="+str(result["gpu_kernel_total_serial_ms"]))
    for item in result["top_ple_gpu_kernel_names"][:15]:
        print("PLE_KERNEL "+str(item["total_ms"])+"ms x"+str(item["count"])+" "+item["name"][:160])
    for item in result["top_gpu_kernels_by_sum"][:12]:
        print("KERNEL "+str(item["total_ms"])+"ms x"+str(item["count"])+
              " "+item["name"][:160])


if __name__=="__main__":
    main()
