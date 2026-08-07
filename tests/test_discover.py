"""Unit tests for file discovery — no audio decoding, just paths and names."""

import tempfile
import unittest
from pathlib import Path

from call_processor.discover import discover_files


class TestDiscoverSingleFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def touch(self, name, size=1):
        p = self.dir / name
        p.write_bytes(b"0" * size)
        return p

    def test_single_file_path_is_accepted(self):
        path = self.touch("conversation.m4a")
        self.assertEqual(discover_files(path), {path: "Conversation"})

    def test_single_file_skips_the_combined_recording_heuristic(self):
        # In a folder this name would be treated as the mixed track and skipped.
        # Naming the file explicitly is unambiguous intent, so it's kept.
        path = self.touch("audio_only.m4a")
        self.assertEqual(list(discover_files(path)), [path])

    def test_single_file_honours_overrides(self):
        path = self.touch("memo123.wav")
        self.assertEqual(discover_files(path, {"memo123": "Both voices"}),
                         {path: "Both voices"})

    def test_non_audio_file_is_rejected(self):
        path = self.touch("notes.txt")
        with self.assertRaises(ValueError):
            discover_files(path)

    def test_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            discover_files(self.dir / "nope")

    def test_folder_still_works(self):
        a = self.touch("audio1234_Jane_Cooper.m4a")
        b = self.touch("audio5678_Isaiah.m4a")
        self.assertEqual(discover_files(self.dir),
                         {a: "Jane Cooper", b: "Isaiah"})


if __name__ == "__main__":
    unittest.main()
