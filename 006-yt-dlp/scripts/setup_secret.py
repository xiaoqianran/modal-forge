"""Create/update Modal Secret from local, Git-ignored cookies.txt.

Cookie values never appear in CLI arguments or application source files.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SECRET = "youtube-cookies"
COOKIE_FILE = Path(__file__).resolve().parent.parent / "cookies.txt"


def main() -> None:
    if not COOKIE_FILE.is_file():
        raise SystemExit("Place a Netscape-format cookies.txt in the project root first.")
    content = COOKIE_FILE.read_bytes()
    if not content.startswith(b"# Netscape HTTP Cookie File"):
        raise SystemExit("Invalid Netscape cookie export; expected Netscape HTTP Cookie File.")
    data = {"YOUTUBE_COOKIES_B64": base64.b64encode(content).decode("ascii")}
    path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="modal-cookie-secret-", suffix=".json", mode="w",
            encoding="utf-8", delete=False
        ) as f:
            path = Path(f.name)
            os.chmod(path, 0o600)
            json.dump(data, f)
        subprocess.run(
            [sys.executable, "-m", "modal", "secret", "create",
             SECRET, "--from-json", str(path), "--force"],
            check=True,
        )
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
