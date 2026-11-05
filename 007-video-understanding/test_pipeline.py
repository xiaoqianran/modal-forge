"""Producer tests requiring no real Cloudflare or NVIDIA access."""

import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from extractor import locate_video, extract_window
from producer import make_batch, produce


JOB = "8748ecf7da644a1884d7cd8fae692b41"


class PipelineTests(unittest.TestCase):
    def test_video_path_and_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / JOB
            folder.mkdir()
            path = folder / "film.mkv"
            path.write_bytes(b"fake")
            self.assertEqual(locate_video(JOB, root), path)
            with self.assertRaises(ValueError):
                locate_video("../abc", root)

    def test_batch_mapping(self):
        message = make_batch(JOB, 120, [Path("a.jpg"), Path("b.jpg")])
        self.assertEqual(message["batch_id"], "00000120")
        self.assertEqual(message["timestamps_s"], [120, 121])
        self.assertEqual(message["keys"][0], f"temp/{JOB}/00000120.jpg")

    def test_bounded_extractor(self):
        with self.assertRaises(ValueError):
            extract_window(Path("irrelevant.mp4"), Path("unused"), 0, 201)

    def test_missing_secret(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Missing Modal Secret"):
                produce(JOB)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_ffmpeg_1fps_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "synthetic.mp4"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=25",
                 "-t", "4", "-y", str(video)],
                capture_output=True, check=True,
            )
            files = extract_window(video, Path(tmp) / "frames", 0, 4, 640)
            self.assertEqual(len(files), 4)
            self.assertTrue(all(f.read_bytes().startswith(b"\xff\xd8") for f in files))


if __name__ == "__main__":
    unittest.main()
