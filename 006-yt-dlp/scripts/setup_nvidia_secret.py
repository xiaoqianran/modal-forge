"""Read NVIDIA_API_KEY from .env or hidden prompt and create a Modal Secret."""

import getpass
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_key() -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, sep, value = line.partition("=")
            if sep and name.strip() == "NVIDIA_API_KEY":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                if not value:
                    raise SystemExit("NVIDIA_API_KEY is empty in .env")
                return value
    return getpass.getpass("NVIDIA_API_KEY (input hidden): ").strip()


def main():
    key = load_key()
    if not key:
        raise SystemExit("Empty API key; no secret created")
    path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="modal-nvidia-secret-", suffix=".json", mode="w",
            encoding="utf-8", delete=False
        ) as handle:
            path = Path(handle.name)
            os.chmod(path, 0o600)
            json.dump({"NVIDIA_API_KEY": key}, handle)
        subprocess.run(
            [sys.executable, "-m", "modal", "secret", "create", "nvidia-api",
             "--from-json", str(path), "--force"],
            check=True,
        )
    finally:
        key = None
        if path is not None:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
