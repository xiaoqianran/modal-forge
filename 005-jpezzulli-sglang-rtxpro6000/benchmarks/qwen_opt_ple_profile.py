"""Optional short SGLang profiler, executed AFTER performance measurements.

Never changes Penny Royal model parameters. Trace artifacts are preserved in a
separate profile_traces/ prefix of our dedicated experiment Volume v2.
Trace timing must not be compared with production non-profiled throughput.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

from qwen_core.profile import stream_request

PROFILE_URL="http://127.0.0.1:8001"
TRACE_ROOT=Path("/tmp/qwen-opt-ple-profile")
MAX_TRACE_BYTES=256*1024**2
MAX_TRACE_FILES=100


def _post(path: str, payload=None, timeout=15) -> dict:
    data=json.dumps(payload or {}).encode("utf-8")
    request=urllib.request.Request(
        PROFILE_URL+path, data=data,
        headers={"Content-Type":"application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request,timeout=timeout) as resp:
            return {"status":resp.status,
                    "text":resp.read(1500).decode("utf-8",errors="replace")}
    except urllib.error.HTTPError as exc:
        return {"status":exc.code, "error":exc.read(1000).decode("utf-8",errors="replace")}
    except (OSError, ValueError) as exc:
        return {"status":None, "error":f"{type(exc).__name__}: {exc}"}


def profile_once(model: str, *, volume, volume_root: Path,
                 run_identifier: str = "r2") -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",run_identifier):
        raise ValueError("Unsafe trace run ID")
    started=time.monotonic()
    folder=TRACE_ROOT/run_identifier
    folder.mkdir(parents=True,exist_ok=True)
    result={"status":"not_started","run_identifier":run_identifier,
            "source":"SGLang native /start_profile",
            "steps_requested":12,"profiled_workload":None,
            "trace_files":[],"profiling_only":True}
    start=_post("/start_profile",{
        "output_dir":str(folder),
        "num_steps":12,
        "activities":["CPU","GPU"],
        "detailed_annotations":False
    },timeout=18)
    result["start_endpoint"]=start
    if start.get("status") != 200:
        result["status"]="endpoint_unavailable"
        return result
    try:
        result["profiled_workload"]=stream_request(
            model,
            "Profile test: Explain briefly how 17 multiplied by 23 equals 391. "
            "Then describe why a CPU-hosted lookup table can create GPU stalls.",
            256, timeout=50,
        )
        # When num_steps is set, SGLang ends the profile automatically after
        # the requested batches. Give the worker time to flush its traces.
        files=[]
        for _ in range(4):
            time.sleep(2)
            files=[x for x in folder.rglob("*") if x.is_file() and not x.is_symlink()]
            if files and all(x.stat().st_size > 0 for x in files):
                break
        if not files:
            result["stop_endpoint"]=_post("/stop_profile",{},timeout=20)
            time.sleep(3)
            files=[x for x in folder.rglob("*") if x.is_file() and not x.is_symlink()]
        files=sorted(files)
        total=sum(x.stat().st_size for x in files)
        result["trace_files"]=[
            {"name":str(x.relative_to(folder)),"bytes":x.stat().st_size}
            for x in files[:MAX_TRACE_FILES]
        ]
        result["trace_payload_bytes"]=total
        if not files:
            result["status"]="no_trace_emitted"
        elif total>MAX_TRACE_BYTES or len(files)>MAX_TRACE_FILES:
            result["status"]="trace_too_large"
        else:
            # Archive under experiment namespace, never compiler-cache /entries.
            destdir=volume_root/"profile_traces"
            destdir.mkdir(parents=True,exist_ok=True)
            target=destdir/(run_identifier+".tar.gz")
            if target.exists():
                raise FileExistsError("Trace already published")
            staging=target.with_suffix(".tar.gz.partial")
            with tarfile.open(staging,"w:gz",compresslevel=1) as t:
                for file in files:
                    t.add(file,arcname=file.relative_to(folder).as_posix(),recursive=False)
            os.replace(staging,target)
            digest=hashlib.sha256(target.read_bytes()).hexdigest()
            info={
                "created_utc":datetime.now(timezone.utc).isoformat(),
                "run":run_identifier,"sha256":digest,"size_bytes":target.stat().st_size,
                "source_files":result["trace_files"],
                "note":"profile overhead is not production latency",
            }
            metadata=destdir/(run_identifier+".json")
            metadata.write_text(json.dumps(info,indent=2),encoding="utf-8")
            volume.commit()
            result.update(status="published", trace_volume_path=str(target),
                          trace_sha256=digest,trace_archive_bytes=target.stat().st_size)
    except Exception as exc:
        result["status"]="profile_error"
        result["error"]=f"{type(exc).__name__}: {exc}"
    result["elapsed_s"]=round(time.monotonic()-started,3)
    return result
