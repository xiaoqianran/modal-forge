"""Test optional .env parsing without reading or printing a real API key."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import setup_nvidia_secret
from scripts import setup_secret


class EnvKeyTests(unittest.TestCase):
    def test_secret_paths_stay_in_project_root(self):
        project = Path(__file__).resolve().parent.parent
        self.assertEqual(setup_nvidia_secret.ENV_FILE, project / ".env")
        self.assertEqual(setup_secret.COOKIE_FILE, project / "cookies.txt")

    def test_unquoted_and_quoted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            with patch.object(setup_nvidia_secret, "ENV_FILE", path):
                path.write_text("# comment\nNVIDIA_API_KEY=demo-test-only\n", encoding="utf-8")
                self.assertEqual(setup_nvidia_secret.load_key(), "demo-test-only")
                path.write_text('NVIDIA_API_KEY="demo quoted"\n', encoding="utf-8")
                self.assertEqual(setup_nvidia_secret.load_key(), "demo quoted")

    def test_empty_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("NVIDIA_API_KEY=\n", encoding="utf-8")
            with patch.object(setup_nvidia_secret, "ENV_FILE", path):
                with self.assertRaises(SystemExit):
                    setup_nvidia_secret.load_key()


if __name__ == "__main__":
    unittest.main()
