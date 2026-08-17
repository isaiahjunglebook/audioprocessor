"""Unit tests for the web page's progress parsing.

web_ui.py is a script, not a package module, so it's loaded by path.
"""

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "web_ui", Path(__file__).resolve().parent.parent / "scripts" / "web_ui.py")
web_ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(web_ui)


class TestHumanize(unittest.TestCase):
    def test_units(self):
        self.assertEqual(web_ui._humanize(42), "42s")
        self.assertEqual(web_ui._humanize(90), "1m 30s")
        self.assertEqual(web_ui._humanize(3725), "1h 02m")
        self.assertEqual(web_ui._humanize(-5), "0s")


class TestProgressParsing(unittest.TestCase):
    def setUp(self):
        web_ui.JOBS[1] = {"id": 1, "percent": 0, "phase": "", "eta": "",
                          "elapsed": "", "detail": "", "status": "running"}
        self.addCleanup(web_ui.JOBS.clear)

    def read(self, line, total=1500.0, started=None):
        import time
        web_ui._read_progress(1, line, total, started if started is not None
                              else time.monotonic() - 60)
        return web_ui.JOBS[1]

    def test_whisperx_segment_line(self):
        job = self.read("Transcript: [689.341 --> 750.000]  some words")
        self.assertEqual(job["percent"], 50)   # 750 of 1500
        self.assertEqual(job["phase"], "transcribing")

    def test_call_processor_progress_line(self):
        job = self.read("[progress] 300.0/1200.0")
        self.assertEqual(job["percent"], 25)   # its own total wins over ours

    def test_percent_capped_below_complete(self):
        # The job is not done until the file exists, so parsing must never
        # show 100% while transcription output is still arriving.
        job = self.read("[1490.0 --> 1500.0]")
        self.assertEqual(job["percent"], 99)

    def test_diarization_line_switches_phase(self):
        job = self.read(">>Performing diarization...")
        self.assertEqual(job["phase"], "finding speakers")
        self.assertIn("separating the voices", job["detail"])

    def test_unrelated_line_changes_nothing(self):
        job = self.read("Some warning about torchcodec")
        self.assertEqual(job["percent"], 0)
        self.assertEqual(job["phase"], "")

    def test_no_duration_means_no_percentage(self):
        job = self.read("[10.0 --> 20.0]", total=0.0)
        self.assertEqual(job["percent"], 0)

    def test_eta_is_reported_once_underway(self):
        import time
        job = self.read("[0.0 --> 750.0]", started=time.monotonic() - 600)
        # Half done in 10 minutes -> roughly 10 minutes left.
        self.assertIn("left", job["eta"])


if __name__ == "__main__":
    unittest.main()
