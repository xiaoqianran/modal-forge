"""Verify downloader selection without making network requests or using cookies."""
import unittest
from pathlib import Path

from yt_downloader.downloader import _options

try:
    from yt_dlp.downloader import get_suitable_downloader
except ImportError:
    get_suitable_downloader = None


SAMPLE = {
    "https": {"url": "https://example.com/file.mp4", "protocol": "https"},
    "dash": {
        "url": "https://example.com/media",
        "protocol": "http_dash_segments",
        "fragments": [{"url": "https://example.com/segment1"}],
    },
    "hls": {"url": "https://example.com/index.m3u8", "protocol": "m3u8_native"},
}

EXPECTED = {
    "native": ("HttpFD", "DashSegmentsFD", "HlsFD"),
    "chunked": ("HttpFD", "DashSegmentsFD", "HlsFD"),
    "aria2": ("Aria2cFD", "DashSegmentsFD", "HlsFD"),
}


def main():
    for strategy, expected in EXPECTED.items():
        options = _options(Path("/tmp/probe"), strategy=strategy, connections=4, fragments=4)
        actual = tuple(
            get_suitable_downloader(SAMPLE[k], options).__name__
            for k in ("https", "dash", "hls")
        )
        print(f"{strategy:7} HTTPS={actual[0]:12} DASH={actual[1]:16} HLS={actual[2]}")
        if actual != expected:
            raise RuntimeError(f"Unexpected downloader for {strategy}: {actual!r} != {expected!r}")
    print("PASS: protocol routing verified; no external requests issued")


class DownloaderProbeTests(unittest.TestCase):
    @unittest.skipIf(get_suitable_downloader is None, "yt-dlp only installed in Modal image")
    def test_protocol_routing(self):
        main()


if __name__ == "__main__":
    unittest.main()
