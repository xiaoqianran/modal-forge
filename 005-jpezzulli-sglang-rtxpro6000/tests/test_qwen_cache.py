"""Offline regression tests for the Qwen Volume v2 model cache."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import qwen_download_v2 as qwen_download
from qwen_core import storage as qwen_storage
from legacy import qwen_storage_v1 as qwen_storage_v1


class DownloadTests(unittest.TestCase):
    def test_pack_shards_balanced_and_lossless(self):
        files = [
            {"filename": name, "size": size}
            for name, size in (("a", 10), ("b", 9), ("c", 8), ("d", 7))
        ]
        groups = qwen_download.pack_shards(files, target_bytes=17, max_shards=2)
        self.assertEqual(len(groups), 2)
        self.assertEqual(
            {file["filename"] for group in groups for file in group},
            {"a", "b", "c", "d"},
        )
        self.assertEqual(sorted(sum(x["size"] for x in group) for group in groups), [17, 17])

    def test_staging_folder_stable_for_a_nested_filename(self):
        info = {"filename": "weights/model-0001.safetensors"}
        actual = qwen_download.stage_file("f" * 40, info)
        self.assertEqual(actual.name, "model-0001.safetensors")
        self.assertEqual(actual.parent.name, "weights")
        self.assertEqual(
            actual.parents[1].name,
            hashlib.sha256(info["filename"].encode()).hexdigest()[:24],
        )

    def test_verify_hash_sha256_and_git_blob_sha1(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tiny.bin"
            data = b"hello qwen"
            path.write_bytes(data)
            qwen_download.verify_hash(
                path, {"filename": path.name, "size": len(data),
                       "algorithm": "sha256", "digest": hashlib.sha256(data).hexdigest()},
            )
            git = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            qwen_download.verify_hash(
                path, {"filename": path.name, "size": len(data),
                       "algorithm": "sha1", "digest": git},
            )
            with self.assertRaises(RuntimeError):
                qwen_download.verify_hash(
                    path, {"filename": path.name, "size": len(data),
                           "algorithm": "sha256", "digest": "0" * 64},
                )


class StorageTests(unittest.TestCase):
    def test_v1_v2_volumes_are_isolated(self):
        self.assertNotEqual(
            qwen_storage_v1.MODEL_VOLUME_NAME,
            qwen_storage.MODEL_VOLUME_NAME,
        )
        self.assertEqual(qwen_storage_v1.MODEL_ID, qwen_storage.MODEL_ID)
        self.assertEqual(qwen_storage_v1.MODEL_SLUG, qwen_storage.MODEL_SLUG)

    def test_reject_unsafe_paths(self):
        for value in ("", "../secret", "/etc/passwd", "dir\\evil", "./abc", "a//b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                qwen_storage.safe_filename(value)
        self.assertEqual(
            qwen_storage.safe_filename("nested/file.safetensors"),
            Path("nested/file.safetensors"),
        )

    def _sample_cache(self, tmp: Path) -> dict:
        revision = "a" * 40
        root = tmp / qwen_storage.MODEL_SLUG / "snapshots" / revision
        root.mkdir(parents=True)
        (root / "config.json").write_text("{}", encoding="utf-8")
        (root / "tokenizer.json").write_text("{}", encoding="utf-8")
        (root / "weight.bin").write_bytes(b"weight")
        (root / "model.safetensors.index.json").write_text(
            json.dumps({"weight_map": {"w": "weight.bin"}}), encoding="utf-8",
        )
        files = [
            {"filename": p.name, "size": p.stat().st_size}
            for p in root.iterdir() if p.is_file()
        ]
        return {"model": qwen_storage.MODEL_ID, "volume_version": 2,
                "revision": revision, "files": files}

    def test_unpublished_snapshot_is_not_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._sample_cache(root)
            with patch.object(qwen_storage, "READY_FILE", root / "ready.json"), \
                 patch.object(qwen_storage, "CACHE_DIR", root):
                with self.assertRaisesRegex(RuntimeError, "not published"):
                    qwen_storage.ready_snapshot()

    def test_published_snapshot_validates_all_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = self._sample_cache(root)
            ready = root / "ready.json"
            with patch.object(qwen_storage, "READY_FILE", ready), \
                 patch.object(qwen_storage, "CACHE_DIR", root):
                qwen_storage.atomic_json(ready, record)
                location, manifest = qwen_storage.ready_snapshot()
                self.assertEqual(location.name, record["revision"])
                self.assertEqual(manifest["volume_version"], 2)
                (location / "weight.bin").unlink()
                with self.assertRaisesRegex(RuntimeError, "missing or corrupt"):
                    qwen_storage.ready_snapshot()


if __name__ == "__main__":
    unittest.main()
