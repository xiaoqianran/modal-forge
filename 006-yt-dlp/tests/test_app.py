"""Offline tests: no Modal cloud resources and no real Cookie required."""
import base64
import os
import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

from yt_downloader.auth import cookie_file
from yt_downloader.downloader import _options, validate_tuning, inspect, _requires_authentication
from yt_downloader.models import validate_url, public_metadata
from yt_downloader.storage import ROOT


class TestAutomaticAnalysis(unittest.TestCase):
    def test_download_starts_analysis_after_success(self):
        import app

        result = {"status": "success", "job_id": "1234567890abcdef1234567890abcdef"}
        with (
            patch("yt_downloader.downloader.download", return_value=result),
            patch("modal.Function.from_name") as locate,
        ):
            locate.return_value.spawn.return_value.object_id = "fc-test"
            output = app.download_video.local("https://youtube.com/watch?v=abc")
        self.assertEqual(output["analysis"]["status"], "scheduled")
        self.assertEqual(output["analysis"]["function_call_id"], "fc-test")
        locate.assert_called_once_with(
            "modal-forge-007-video-understanding", "process_video"
        )
        locate.return_value.spawn.assert_called_once_with(result["job_id"])

    def test_download_opt_out_does_not_trigger_analysis(self):
        import app

        with (
            patch("yt_downloader.downloader.download", return_value={"job_id": "test"}),
            patch("modal.Function.from_name") as locate,
        ):
            output = app.download_video.local("https://youtube.com/watch?v=abc", analyze=False)
        self.assertEqual(output["analysis"]["status"], "disabled")
        locate.assert_not_called()

    def test_analysis_failure_does_not_discard_completed_download(self):
        import app

        with (
            patch("yt_downloader.downloader.download", return_value={"job_id": "test"}),
            patch("modal.Function.from_name", side_effect=RuntimeError("unavailable")),
        ):
            output = app.download_video.local("https://youtube.com/watch?v=abc")
        self.assertEqual(output["analysis"]["status"], "trigger_failed")


class TestConfig(unittest.TestCase):
    def test_valid_url(self):
        self.assertEqual(validate_url("https://www.youtube.com/watch?v=abc"), "https://www.youtube.com/watch?v=abc")

    def test_invalid_url(self):
        for value in ("", "file:///etc/passwd", "ftp://example.org", "https://user:pass@example.org"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_url(value)

    def test_inspect_is_safe(self):
        cfg = _options()
        self.assertTrue(cfg["skip_download"])
        self.assertTrue(cfg["noplaylist"])
        self.assertNotIn("cookiefile", cfg)

    def test_download_uses_staging(self):
        cfg = _options(Path("/data/stage"), subtitles=True, cookie_path="/tmp/cookie")
        self.assertFalse(cfg["skip_download"])
        self.assertTrue(cfg["writesubtitles"])
        self.assertEqual(cfg["cookiefile"], "/tmp/cookie")

    def test_aria2_is_only_for_http_media(self):
        cfg = _options(Path("/data/stage"), strategy="aria2", connections=4, fragments=3)
        self.assertEqual(cfg["external_downloader"], {
            "default": "aria2c", "dash": "native", "m3u8": "native",
        })
        self.assertIn("--split=4", cfg["external_downloader_args"]["aria2c"])
        self.assertEqual(cfg["concurrent_fragment_downloads"], 3)

    def test_native_baseline_has_no_external_downloader_or_chunking(self):
        cfg = _options(Path("/data/stage"), strategy="native", fragments=1)
        self.assertNotIn("external_downloader", cfg)
        self.assertNotIn("http_chunk_size", cfg)

    def test_download_default_keeps_fastest_measured_native_policy(self):
        cfg = _options(Path("/data/stage"))
        self.assertEqual(cfg["concurrent_fragment_downloads"], 1)
        self.assertNotIn("external_downloader", cfg)
        self.assertNotIn("http_chunk_size", cfg)

    def test_chunked_http_caps_request_range_to_eight_mib(self):
        cfg = _options(Path("/data/stage"), strategy="chunked")
        self.assertEqual(cfg["http_chunk_size"], 8 * 1024 * 1024)
        self.assertNotIn("external_downloader", cfg)

    def test_inspect_never_invokes_external_downloader(self):
        cfg = _options(strategy="aria2")
        self.assertNotIn("external_downloader", cfg)

    def test_authentication_error_detection(self):
        self.assertTrue(_requires_authentication(Exception("Sign in to confirm you’re not a bot")))
        self.assertFalse(_requires_authentication(Exception("HTTP Error 429: Too Many Requests")))

    def test_inspect_anonymous_success_skips_cookie(self):
        fake = types.ModuleType("yt_dlp")
        fake.utils = types.SimpleNamespace(DownloadError=RuntimeError)
        ydl = MagicMock()
        ydl.extract_info.return_value = {"id": "abc", "formats": []}
        ydl.sanitize_info.side_effect = lambda info: info
        fake.YoutubeDL = MagicMock()
        fake.YoutubeDL.return_value.__enter__.return_value = ydl
        with patch.dict(sys.modules, {"yt_dlp": fake}), patch("yt_downloader.downloader.cookie_file") as cookies:
            result = inspect("https://www.youtube.com/watch?v=abc")
        self.assertEqual(result["authentication"], "anonymous")
        cookies.assert_not_called()
        self.assertNotIn("cookiefile", fake.YoutubeDL.call_args.args[0])

    def test_inspect_authentication_fallback(self):
        fake = types.ModuleType("yt_dlp")
        class DownloadError(Exception):
            pass
        fake.utils = types.SimpleNamespace(DownloadError=DownloadError)
        records = []
        def build(options):
            records.append(options)
            ydl = MagicMock()
            if len(records) == 1:
                ydl.extract_info.side_effect = DownloadError("Sign in to confirm you’re not a bot")
            else:
                ydl.extract_info.return_value = {"id": "abc", "formats": []}
            ydl.sanitize_info.side_effect = lambda info: info
            return _FakeContext(ydl)
        class _FakeContext:
            def __init__(self, ydl):
                self.ydl = ydl
            def __enter__(self):
                return self.ydl
            def __exit__(self, *args):
                return False
        fake.YoutubeDL = build
        from contextlib import contextmanager
        @contextmanager
        def fake_cookie():
            yield "/tmp/secret-cookie.txt"
        with patch.dict(sys.modules, {"yt_dlp": fake}), patch("yt_downloader.downloader.cookie_file", fake_cookie):
            result = inspect("https://www.youtube.com/watch?v=abc")
        self.assertEqual(result["authentication"], "cookie")
        self.assertNotIn("cookiefile", records[0])
        self.assertEqual(records[1]["cookiefile"], "/tmp/secret-cookie.txt")

    def test_tuning_limits(self):
        for kwargs in [
            {"strategy": "unknown", "connections": 4, "fragments": 4},
            {"strategy": "aria2", "connections": 0, "fragments": 4},
            {"strategy": "aria2", "connections": 9, "fragments": 4},
            {"strategy": "aria2", "connections": 4, "fragments": 9},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                validate_tuning(**kwargs)

    def test_output_path(self):
        self.assertEqual(ROOT.as_posix().replace("\\", "/"), "/data/006-yt-dlp-downloads")

    def test_public_metadata_excludes_secrets(self):
        info = {"id": "foo", "title": "demo", "http_headers": {"Cookie": "private"}}
        self.assertNotIn("http_headers", public_metadata(info))

    def test_cookie_lifecycle(self):
        fake = b"# Netscape HTTP Cookie File\n.example.org\tTRUE\t/\tTRUE\t0\tX\ttest\n"
        with patch.dict(os.environ, {"YOUTUBE_COOKIES_B64": base64.b64encode(fake).decode("ascii")}):
            with cookie_file() as path:
                self.assertTrue(Path(path).is_file())
                self.assertEqual(Path(path).read_bytes(), fake)
            self.assertFalse(Path(path).exists())

    def test_cookie_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                with cookie_file():
                    pass


if __name__ == "__main__":
    unittest.main()
