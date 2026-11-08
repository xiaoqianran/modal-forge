"""Shared Pika checkpoint location and fail-fast validation for CPU/GPU stages."""
import json
from pathlib import Path

MODEL = "Pika-Labs/Pika-H3-Flex"
VOLUME_ROOT = "/mnt/modal"
CACHE_ROOT = Path(VOLUME_ROOT) / "009-pika-h3-flex"
HF_HUB_CACHE = CACHE_ROOT / "hub"
READY_FILE = CACHE_ROOT / "model-ready.json"


def inspect_snapshot(snapshot):
    """Fail if the snapshot contains missing links or no actual weight tensors."""
    snapshot = Path(snapshot)
    if not snapshot.is_dir():
        raise RuntimeError(f"Model snapshot is missing: {snapshot}")
    files = [p for p in snapshot.rglob("*") if p.is_file()]
    weights = [p for p in files if p.suffix.lower() in (".safetensors", ".bin", ".pt", ".pth")]
    if not weights:
        raise RuntimeError(f"No model weights were found in {snapshot}")
    total = sum(p.stat().st_size for p in files)
    if total == 0:
        raise RuntimeError(f"Model files are empty: {snapshot}")
    return {"file_count": len(files), "weight_count": len(weights), "total_bytes": total}


def get_ready_model():
    """Return the local checkpoint path; never resolve a remote Hugging Face repo."""
    if not READY_FILE.is_file():
        raise RuntimeError(
            "Pika model was not downloaded on CPU. First run: "
            "uv run modal run download_model.py"
        )
    manifest = json.loads(READY_FILE.read_text(encoding="utf-8"))
    if manifest.get("repo_id") != MODEL:
        raise RuntimeError("Model cache manifest has the wrong repo_id")
    snapshot = Path(manifest.get("snapshot_path", ""))
    if not snapshot.is_absolute() or not snapshot.resolve().is_relative_to(HF_HUB_CACHE.resolve()):
        raise RuntimeError("Model cache manifest refers to an invalid snapshot directory")
    if snapshot.parent.name != "snapshots":
        raise RuntimeError("Model cache manifest must point to a Hugging Face snapshot")
    inspect_snapshot(snapshot)
    return str(snapshot)
