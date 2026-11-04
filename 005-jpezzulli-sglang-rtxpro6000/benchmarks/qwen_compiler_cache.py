"""A small, strict compiler-cache contract for the Qwen PRO6000 experiment.

A dedicated Volume v2 stores only compiler artifacts; model Volumes never change.
Worker uses /tmp/penny-cache to avoid writes from compilers to a network mount.
The single writer publishes a complete tar + checksum + manifest and commits.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone

import modal

COMPILER_VOLUME_NAME = "modal-forge-qwen38-compile-v2"
COMPILER_VOLUME = modal.Volume.from_name(
    COMPILER_VOLUME_NAME, create_if_missing=True, version=2
)
CACHE_ROOT = Path("/tmp/penny-cache")
VOLUME_ROOT = Path("/compiler-vol")
IMAGE_TAG = "ghcr.io/jpezzulli/sglang-rtxpro6000:v3.1.5"
MODEL_REVISION = "7b719225242aacd3dbd3f9407468c2ee9a9d2594"
COMPILER_DIRS = ("tilelang", "triton", "torchinductor", "cuda",
                 "flashinfer", "sglang/jit")
MAX_ARCHIVE_BYTES = 3 * 1024**3
MAX_FILES = 50000


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def runtime_identity(*, capacity: str, hicache_gb: int, revision: str) -> dict:
    """Gather actual runtime versions from Penny Royal's own Python environment."""
    if capacity not in ("c2", "c4") or revision != MODEL_REVISION:
        raise ValueError("Unsupported capacity or model revision")
    command = [
        "/opt/pennyroyal/.venv/bin/python", "-c",
        "import json,importlib.metadata as m;"
        "names=('torch','tilelang','triton','flashinfer-python','sglang');"
        "print(json.dumps({k:m.version(k) for k in names}))",
    ]
    p = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if p.returncode:
        raise RuntimeError("Cannot pin compiler versions: " + p.stderr[-700:])
    versions = json.loads(p.stdout.strip())
    scripts = {}
    for path in (
        "/opt/pennyroyal/configs/pennyroyal/serve-flash-next-frspec.sh",
        "/opt/pennyroyal/configs/pennyroyal/request-capacity.sh",
    ):
        scripts[Path(path).name] = _sha256(Path(path))
    # Explicit shape and configuration guards prevent silently reusing graph-state
    # artifacts with incompatible model or concurrency settings.
    return {
        "schema": 1,
        "model_revision": revision, "image_tag": IMAGE_TAG,
        "architecture": "sm120", "capacity": capacity,
        "max_running_requests": 2 if capacity == "c2" else 4,
        "max_mamba_cache_size": 12 if capacity == "c2" else 24,
        "hicache_gb": hicache_gb, "mtp_policy": "tiered",
        "nixl": "off", "ple_backend": "ram",
        "cache_root": str(CACHE_ROOT),
        "torch_and_compilers": versions, "script_sha256": scripts,
    }


def fingerprint(identity: dict) -> str:
    stable = json.dumps(identity, sort_keys=True, ensure_ascii=True,
                        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(stable).hexdigest()


def _entry_paths(identity: dict, *, volume_root: Path = VOLUME_ROOT):
    fp = fingerprint(identity)
    folder = volume_root / "entries" / fp
    return folder, folder / "cache.tar", folder / "manifest.json"


def available(identity: dict, *, volume_root: Path = VOLUME_ROOT) -> bool:
    _, archive, manifest = _entry_paths(identity, volume_root=volume_root)
    return archive.is_file() and manifest.is_file()


def _read_manifest(identity: dict, volume_root: Path):
    folder, archive, manifest_path = _entry_paths(identity, volume_root=volume_root)
    if not archive.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"No complete compiler artifact for {fingerprint(identity)}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("identity") != identity:
        raise RuntimeError("Compiler cache runtime identity mismatch; refusing restore")
    if manifest.get("archive_sha256") != _sha256(archive):
        raise RuntimeError("Compiler cache SHA-256 mismatch")
    if manifest.get("archive_size_bytes") != archive.stat().st_size:
        raise RuntimeError("Compiler cache byte size mismatch")
    return archive, manifest


def restore(identity: dict, *, cache_root: Path = CACHE_ROOT,
            volume_root: Path = VOLUME_ROOT) -> dict:
    """Safe extraction of only regular files under known compiler paths."""
    started = time.monotonic()
    archive, manifest = _read_manifest(identity, volume_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    allowed = tuple(Path(x).parts for x in COMPILER_DIRS)
    restored = 0
    total = 0
    with tarfile.open(archive, "r:") as tar:
        for member in tar:
            raw = Path(member.name)
            parts = raw.parts
            # Some cache directories are nested (sglang/jit).
            if not any(parts[:len(prefix)] == prefix for prefix in allowed):
                raise RuntimeError(f"Unexpected compiler cache entry: {member.name!r}")
            if not member.isfile() or raw.is_absolute() or ".." in parts or "\\" in member.name:
                raise RuntimeError(f"Unsafe cache tar member: {member.name!r}")
            total += member.size
            restored += 1
            if total > MAX_ARCHIVE_BYTES or restored > MAX_FILES:
                raise RuntimeError("Cached compiler artifacts exceed restore quota")
            dest = cache_root.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_symlink():
                raise RuntimeError(f"Symlink destination refused: {dest}")
            src = tar.extractfile(member)
            if src is None:
                raise RuntimeError(f"Cannot extract {member.name}")
            with src, dest.open("wb") as writer:
                shutil.copyfileobj(src, writer, 4 * 1024 * 1024)
            os.chmod(dest, member.mode & 0o777)
    if total != manifest["payload_bytes"] or restored != manifest["file_count"]:
        raise RuntimeError("Compiler cache extracted size/file-count mismatch")
    return {
        "restored": True, "fingerprint": fingerprint(identity),
        "file_count": restored, "payload_bytes": total,
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": manifest["archive_sha256"],
        "restore_s": round(time.monotonic()-started,3),
    }


def _source_files(cache_root: Path):
    """Select only the dedicated compiler subtrees; ignore model/hf and NIXL."""
    for relative in COMPILER_DIRS:
        folder = cache_root / relative
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file() and not path.is_symlink():
                yield path, path.relative_to(cache_root)


def publish(identity: dict, *, volume, cache_root: Path = CACHE_ROOT,
            volume_root: Path = VOLUME_ROOT) -> dict:
    """Single-writer publication; only after child inference process has exited."""
    started = time.monotonic()
    folder, archive, manifest_path = _entry_paths(identity, volume_root=volume_root)
    if archive.exists() or manifest_path.exists():
        raise FileExistsError(f"Compiler cache already published for {fingerprint(identity)}")
    folder.mkdir(parents=True, exist_ok=True)
    size = 0
    count = 0
    with tempfile.TemporaryDirectory(prefix="qwen-compilers-") as temp:
        temp_archive = Path(temp) / "cache.tar"
        with tarfile.open(temp_archive, "w:") as tar:
            for source, relative in _source_files(cache_root):
                stat = source.stat()
                size += stat.st_size
                count += 1
                if count > MAX_FILES or size > MAX_ARCHIVE_BYTES:
                    raise RuntimeError("Compiler cache too large; no partial publication")
                # Paths are relative to known compiler subtrees.
                tar.add(source, arcname=relative.as_posix(), recursive=False)
        if not count:
            raise RuntimeError("No compiler artifacts created; refusing to publish empty cache")
        digest = _sha256(temp_archive)
        # Atomic file publication within the Volume, then explicit commit.
        temp_dst = folder / "cache.tar.partial"
        shutil.copyfile(temp_archive, temp_dst)
        os.replace(temp_dst, archive)
    manifest = {
        "schema":1, "identity":identity,
        "fingerprint":fingerprint(identity),
        "file_count":count,"payload_bytes":size,
        "archive_size_bytes":archive.stat().st_size,
        "archive_sha256":digest,
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "publisher":"single-writer-r1",
    }
    temp_manifest = folder / "manifest.json.partial"
    temp_manifest.write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding="utf-8")
    os.replace(temp_manifest, manifest_path)
    volume.commit()
    return {
        "published":True,
        "fingerprint":fingerprint(identity),
        "file_count":count, "payload_bytes":size,
        "archive_bytes":manifest["archive_size_bytes"],
        "archive_sha256":digest,
        "publish_s":round(time.monotonic()-started,3),
    }
