"""Producer tests requiring no real Cloudflare or NVIDIA access."""

import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from extractor import locate_video, extract_window
from producer import make_batch, produce, produce_all, _pending_frames


JOB = "8748ecf7da644a1884d7cd8fae692b41"


class PipelineTests(unittest.TestCase):
    def test_pending_frames_counts_paginated_objects(self):
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {"KeyCount": 100}, {"KeyCount": 14},
        ]
        self.assertEqual(_pending_frames(client, "bucket", JOB), 114)

    def test_full_video_progress_and_resume(self):
        client = MagicMock()
        with (
            patch("producer.locate_video", return_value=Path("video.mp4")),
            patch("producer.duration_seconds", return_value=235.4),
            patch("producer.r2_client", return_value=client),
            patch("producer._read_progress", return_value={"next_second": 100, "windows": 1}),
            patch("producer._pending_frames", return_value=0),
            patch("producer.produce", side_effect=[
                {"next_second": 200}, {"next_second": 236},
            ]) as create,
            patch.dict("os.environ", {"CF_R2_BUCKET": "bucket"}),
        ):
            state = produce_all(JOB)
        self.assertEqual(state["status"], "submitted")
        self.assertEqual(state["next_second"], 236)
        self.assertEqual(state["windows"], 3)
        self.assertEqual([call.kwargs["start_second"] for call in create.call_args_list], [100, 200])
        self.assertEqual(client.put_object.call_count, 2)

    def test_full_video_already_submitted_is_idempotent(self):
        with (
            patch("producer.locate_video", return_value=Path("video.mp4")),
            patch("producer.duration_seconds", return_value=4),
            patch("producer.r2_client"),
            patch("producer._read_progress", return_value={"status": "submitted", "next_second": 4}),
            patch("producer.produce") as create,
            patch.dict("os.environ", {"CF_R2_BUCKET": "bucket"}),
        ):
            state = produce_all(JOB)
        self.assertEqual(state["status"], "submitted")
        create.assert_not_called()

    def test_muxing_padding_does_not_create_extra_frame(self):
        client = MagicMock()
        with (
            patch("producer.locate_video", return_value=Path("video.mp4")),
            patch("producer.duration_seconds", return_value=4.004),
            patch("producer.r2_client", return_value=client),
            patch("producer._read_progress", return_value={"next_second": 4, "windows": 1}),
            patch("producer.produce") as create,
            patch.dict("os.environ", {"CF_R2_BUCKET": "bucket"}),
        ):
            state = produce_all(JOB)
        self.assertEqual(state["status"], "submitted")
        self.assertEqual(state["next_second"], 4)
        client.put_object.assert_called_once()
        create.assert_not_called()

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
