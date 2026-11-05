"""Offline tests; no NVIDIA key or cloud resources required."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import video_vision


class FrameTests(unittest.TestCase):
    def test_sample_times(self):
        self.assertEqual(video_vision.sample_times(12, 5, 24), [0, 5, 10])
        self.assertEqual(video_vision.sample_times(2, 5, 24), [0])
        self.assertEqual(video_vision.sample_times(20, 2, 3), [0, 2, 4])

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            video_vision.sample_times(20, 0, 4)
        with self.assertRaises(ValueError):
            video_vision.sample_times(20, 2, 101)

    def test_payload(self):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, *args):
                return b'{"choices":[{"message":{"content":"ok"}}]}'
        with patch("urllib.request.urlopen", return_value=FakeResponse()) as mocked:
            self.assertEqual(video_vision.analyze_frames([(1.5, b"jpeg")], "dummy"), "ok")
            request = mocked.call_args.args[0]
            body = json.loads(request.data)
            self.assertEqual(body["model"], video_vision.MODEL)
            self.assertIn("1.500", body["messages"][0]["content"][1]["text"])

    @unittest.skipUnless(__import__("shutil").which("ffmpeg") and __import__("shutil").which("ffprobe"), "FFmpeg unavailable")
    def test_ffmpeg_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                            "color=c=red:s=320x240:r=1", "-t", "3", "-y", str(path)], check=True)
            self.assertGreater(video_vision.probe_duration(path), 0)
            self.assertTrue(video_vision.extract_frame(path, 1).startswith(b"\xff\xd8"))


if __name__ == "__main__":
    unittest.main()
