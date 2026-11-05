"""Create Modal Secret safely from local .env (never print or pass keys in CLI args)."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from producer import REQUIRED_ENV


def main():
    env_file = Path(__file__).with_name(".env")
    if not env_file.exists():
        raise SystemExit("Copy .env.example to .env and configure Cloudflare first")
    values = {}
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            value = value.strip().strip('"').strip("'")
            values[key.strip()] = value
    missing = [name for name in REQUIRED_ENV if not values.get(name)]
    if missing:
        raise SystemExit("Missing fields in .env: " + ", ".join(missing))
    path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json",
            prefix="modal-cf-secret-", delete=False,
        ) as handle:
            path = Path(handle.name)
            os.chmod(path, 0o600)
            json.dump({key: values[key] for key in REQUIRED_ENV}, handle)
        subprocess.run(
            [sys.executable, "-m", "modal", "secret", "create",
             "cf-video-pipeline", "--from-json", str(path), "--force"],
            check=True,
        )
    finally:
        if path:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
