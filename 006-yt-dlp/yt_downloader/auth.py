"""Cookie material is available only during execution, not in images/Volumes."""
import base64
import contextlib
import os
import tempfile
from pathlib import Path


@contextlib.contextmanager
def cookie_file():
    """Decode a Modal Secret's Base64 Netscape cookie file into ephemeral storage."""
    encoded = os.environ.get("YOUTUBE_COOKIES_B64", "")
    if not encoded:
        raise RuntimeError("Modal Secret youtube-cookies is missing YOUTUBE_COOKIES_B64")
    raw = base64.b64decode(encoded, validate=True)
    if not raw.startswith(b"# Netscape HTTP Cookie File"):
        raise ValueError("Invalid Netscape Cookie header")
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="yt-cookies-", suffix=".txt", delete=False) as f:
            path = Path(f.name)
            os.chmod(path, 0o600)
            f.write(raw)
        yield str(path)
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
