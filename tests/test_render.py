"""Unit tests for transcript rendering, including label-free timestamp output."""

import unittest

from call_processor.render import format_timestamp, render_transcript


def turn(start, end, speaker, text):
    return {"start": start, "end": end, "speaker": speaker, "text": text}


TURNS = [
    turn(0.0, 4.0, "Isaiah", "Hey, thanks for hopping on."),
    turn(65.0, 70.0, "Jane", "Happy to be here."),
]

COMMON = dict(call_name="Test call", date="2026-08-07",
              participants=["Isaiah", "Jane"], source_files=["a.m4a", "b.m4a"])


class TestFormatTimestamp(unittest.TestCase):
    def test_hms(self):
        self.assertEqual(format_timestamp(0), "00:00:00")
        self.assertEqual(format_timestamp(65), "00:01:05")
        self.assertEqual(format_timestamp(3725), "01:02:05")
        self.assertEqual(format_timestamp(-5), "00:00:00")


class TestRenderTranscript(unittest.TestCase):
    def test_default_has_timestamps_and_speakers(self):
        md = render_transcript(TURNS, **COMMON)
        self.assertIn("**[00:00:00] Isaiah:** Hey, thanks for hopping on.", md)
        self.assertIn("**[00:01:05] Jane:** Happy to be here.", md)
        self.assertIn("- **Participants:** Isaiah, Jane", md)

    def test_no_speaker_labels_keeps_timestamps(self):
        md = render_transcript(TURNS, speaker_labels=False, **COMMON)
        self.assertIn("**[00:00:00]** Hey, thanks for hopping on.", md)
        self.assertIn("**[00:01:05]** Happy to be here.", md)
        self.assertNotIn("Isaiah", md)
        self.assertNotIn("Jane", md)
        # The header must not claim participants it can't stand behind.
        self.assertNotIn("Participants", md)
        self.assertIn("- **Duration:** 00:01:10", md)

    def test_no_timestamps_no_labels_is_plain_text(self):
        md = render_transcript(TURNS, timestamps=False, speaker_labels=False, **COMMON)
        self.assertIn("\nHey, thanks for hopping on.\n", md)
        self.assertNotIn("**[", md)


if __name__ == "__main__":
    unittest.main()
