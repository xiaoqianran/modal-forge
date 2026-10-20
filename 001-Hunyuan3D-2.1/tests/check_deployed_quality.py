"""Check the deployed API's new rejection contract without running Shape/Paint."""
import json
import struct
import zlib
from pathlib import Path

import modal


def chunk(kind, content):
    return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)


png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress((b"\0" + bytes(4 * 4)) * 4)) + chunk(b"IEND", b"")
service = modal.Cls.from_name("modal-forge-hunyuan3d-2-1", "Hunyuan3D")()
result = service.generate.remote(image_bytes=png, name="deployed-quality-smoke", paint=False)
assert result["status"] == "rejected" and result["path"] is None
assert result["shape_candidates"] == []
assert result["fork_commit"] == "1112a61026bc6e11a89ea95614e97cba8235b475"
Path("outputs/quality-fixes/deployed-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: result[key] for key in ("status", "fork_commit", "reason")}, ensure_ascii=False))
