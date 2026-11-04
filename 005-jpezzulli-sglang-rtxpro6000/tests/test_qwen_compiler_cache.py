"""CPU-only regression of the independent compiler cache. No Modal GPU calls."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.qwen_compiler_cache import (
    available, fingerprint, publish, restore, MODEL_REVISION,
)


class FakeVolume:
    def __init__(self):
        self.commits=0
    def commit(self):
        self.commits+=1


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/"work"
        self.remote=self.root/"vol"
        self.dest=self.root/"restored"
        self.source.mkdir()
        self.remote.mkdir()
        self.identity={
            "model_revision":MODEL_REVISION,
            "image_tag":"synthetic-only",
            "architecture":"sm120",
            "capacity":"c2",
            "torch_and_compilers":{"tilelang":"0.1.12"},
        }

    def _sample(self):
        for path, data in [
            ("tilelang/mod/kernel.so",b"F" * 256),
            ("triton/test.bin",b"T" * 128),
            ("flashinfer/rank.json",b'{"autotune":1}'),
        ]:
            dest=self.source/path
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(data)

    def test_publish_and_restore_and_sha_verification(self):
        self._sample()
        vol=FakeVolume()
        saved=publish(self.identity,volume=vol,cache_root=self.source,
                      volume_root=self.remote)
        self.assertTrue(saved["published"])
        self.assertEqual(vol.commits,1)
        self.assertEqual(saved["file_count"],3)
        self.assertTrue(available(self.identity,volume_root=self.remote))
        restored=restore(self.identity,cache_root=self.dest,volume_root=self.remote)
        self.assertEqual(restored["file_count"],3)
        self.assertEqual((self.dest/"triton/test.bin").read_bytes(),b"T"*128)
        with self.assertRaises(FileExistsError):
            publish(self.identity,volume=vol,cache_root=self.source,
                    volume_root=self.remote)
        manifest_path=self.remote/"entries"/fingerprint(self.identity)/"manifest.json"
        manifest=json.loads(manifest_path.read_text("utf-8"))
        manifest["archive_sha256"]="0"*64
        manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
        with self.assertRaises(RuntimeError):
            restore(self.identity,cache_root=self.dest,volume_root=self.remote)

    def test_cache_isolation_of_fingerprints(self):
        self._sample()
        publish(self.identity,volume=FakeVolume(),cache_root=self.source,
                volume_root=self.remote)
        changed=dict(self.identity,capacity="c4")
        self.assertNotEqual(fingerprint(self.identity),fingerprint(changed))
        self.assertFalse(available(changed,volume_root=self.remote))
        with self.assertRaises(FileNotFoundError):
            restore(changed,cache_root=self.dest,volume_root=self.remote)

    def test_empty_source_never_commits(self):
        vol=FakeVolume()
        with self.assertRaises(RuntimeError):
            publish(self.identity,volume=vol,cache_root=self.source,
                    volume_root=self.remote)
        self.assertEqual(vol.commits,0)


if __name__=="__main__":
    unittest.main()
