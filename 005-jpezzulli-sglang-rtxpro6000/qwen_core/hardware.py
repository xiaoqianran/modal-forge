"""Low-cost Modal host hardware identification (no model or CUDA workload).

Keeps literal outputs of the four requested commands for each GPU run.
Host firmware and DDR generation may be masked in the container.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

COMMANDS = (
    ("lscpu", ["lscpu"]),
    ("numactl --hardware", ["numactl", "--hardware"]),
    ("nvidia-smi -q", ["nvidia-smi", "-q"]),
    ("cat /proc/cpuinfo", ["cat", "/proc/cpuinfo"]),
    ("lstopo --of console", ["lstopo-no-graphics", "--of", "console"]),
)
MAX_CAPTURE_CHARS = 300_000


def _read(path: str, max_chars: int = 20_000) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return None


def capture_hardware() -> dict:
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "container_hostname": os.uname().nodename,
        "commands": {},
        "numa_sysfs": {},
        "ddr_generation": "unknown (host SMBIOS not exposed / not queried)",
    }
    for name, command in COMMANDS:
        try:
            p = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=12,
                env={**os.environ, "LC_ALL": "C"},
            )
            result["commands"][name] = {
                "exit_code": p.returncode,
                "stdout": p.stdout[:MAX_CAPTURE_CHARS],
                "stderr": p.stderr[:4_000],
                "truncated": len(p.stdout) > MAX_CAPTURE_CHARS,
            }
        except (OSError, subprocess.SubprocessError) as exc:
            result["commands"][name] = {
                "exit_code": None, "stdout": "", "stderr": repr(exc),
                "truncated": False,
            }
    for path in ("/sys/devices/system/node/online",
                 "/sys/devices/system/cpu/online"):
        result["numa_sysfs"][path] = _read(path, 1_000)
    cpuinfo = result["commands"]["cat /proc/cpuinfo"]["stdout"]
    model = next(
        (line.split(":", 1)[1].strip() for line in cpuinfo.splitlines()
         if line.lower().startswith("model name") and ":" in line),
        None,
    )
    result["cpu_model"] = model
    return result
