"""Qwen3.8 Flash-Next model cache contract.

This file is for Modal Volume v1 only. Use the corresponding v1 entrypoints. A downloader
publishes a pinned, verified snapshot; inference only reads and links it.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

import modal

MODEL_ID = "RadixArk/Qwen3.8-Flash-Next-NVFP4"
MODEL_SLUG = "models--" + MODEL_ID.replace("/", "--")
MODEL_VOLUME_NAME = "modal-forge-qwen38-flashnext-model-v1-ab"
CACHE_DIR = Path("/cache")
PIN_FILE = CACHE_DIR / ".qwen-model-pin.json"
READY_FILE = CACHE_DIR / ".qwen-model-ready.json"
STAGING_DIR = CACHE_DIR / ".download-staging"
LOCAL_MODEL_LINK = Path("/tmp/pennyroyal-model")
MODEL_VOLUME = modal.Volume.from_name(
    MODEL_VOLUME_NAME, create_if_missing=True, version=1
)


def safe_filename(filename: str) -> Path:
    path = PurePosixPath(filename)
    if (
        not filename or path.is_absolute() or "\\" in filename
        or filename.startswith("./") or "//" in filename
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"Unsafe model filename: {filename!r}")
    return Path(*path.parts)


def snapshot_dir(revision: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"Invalid model revision: {revision!r}")
    return CACHE_DIR / MODEL_SLUG / "snapshots" / revision


def snapshot_file(revision: str, filename: str) -> Path:
    return snapshot_dir(revision) / safe_filename(filename)


def blob_file(digest: str) -> Path:
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", digest):
        raise ValueError(f"Invalid model file digest: {digest!r}")
    return CACHE_DIR / MODEL_SLUG / "blobs" / digest


def size_matches(path: Path, expected: int | None) -> bool:
    try:
        info = path.stat()
    except FileNotFoundError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_size > 0
        and (expected is None or info.st_size == expected)
    )


def validate_weights(root: Path) -> None:
    for name in ("config.json", "tokenizer.json", "model.safetensors.index.json"):
        if not size_matches(root / name, None):
            raise RuntimeError(f"Required model file missing: {name}")
    index = json.loads((root / "model.safetensors.index.json").read_text("utf-8"))
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        raise RuntimeError("Invalid model.safetensors.index.json weight_map")
    for filename in set(weight_map.values()):
        if not isinstance(filename, str):
            raise RuntimeError("Invalid model weight filename")
        if not size_matches(root / safe_filename(filename), None):
            raise RuntimeError(f"Missing indexed weight: {filename}")


def ready_snapshot() -> tuple[Path, dict]:
    """Inspect the last successful publication without network or downloads."""
    if not READY_FILE.is_file():
        raise RuntimeError(
            f"Model is not published in {MODEL_VOLUME_NAME}. "
            "Use qwen_download.py --stage download (CPU only)."
        )
    manifest = json.loads(READY_FILE.read_text("utf-8"))
    if manifest.get("model") != MODEL_ID or manifest.get("volume_version") != 1:
        raise RuntimeError("Model manifest belongs to another model or volume version")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Published manifest is empty")
    root = snapshot_dir(manifest["revision"])
    for item in files:
        if not size_matches(root / safe_filename(item["filename"]), item["size"]):
            raise RuntimeError(f"Published model file missing or corrupt: {item['filename']}")
    validate_weights(root)
    return root, manifest


def link_ready_model() -> tuple[str, dict]:
    """ComfyUI-style local symlink to the pinned, immutable v1 snapshot."""
    root, manifest = ready_snapshot()
    LOCAL_MODEL_LINK.parent.mkdir(parents=True, exist_ok=True)
    if LOCAL_MODEL_LINK.is_symlink():
        if LOCAL_MODEL_LINK.resolve() != root.resolve():
            LOCAL_MODEL_LINK.unlink()
    elif LOCAL_MODEL_LINK.exists():
        raise RuntimeError(f"Unexpected existing local model path: {LOCAL_MODEL_LINK}")
    if not LOCAL_MODEL_LINK.is_symlink():
        LOCAL_MODEL_LINK.symlink_to(root, target_is_directory=True)
    return str(LOCAL_MODEL_LINK), manifest


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    os.replace(temporary, path)
