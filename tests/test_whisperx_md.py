"""Unit tests for the WhisperX JSON -> Markdown conversion."""

import json
import tempfile
import unittest
from pathlib import Path

from call_processor.whisperx_md import (convert, load_segments,
                                        name_by_talk_time, parse_map, render)


def seg(start, end, text, speaker=None):
    s = {"start": start, "end": end, "text": text}
    if speaker is not None:
        s["speaker"] = speaker
    return s


SAMPLE = {
    "segments": [
        seg(0.0, 30.0, " There's a job in Whistler.", "SPEAKER_01"),
        seg(31.0, 32.0, " Yeah.", "SPEAKER_00"),
        seg(33.0, 63.0, " All the drapes are ripple fold.", "SPEAKER_01"),
        seg(64.0, 70.0, "   ", "SPEAKER_00"),        # whitespace only -> dropped
        seg(3661.0, 3665.0, " I'd rather make 500 grand.", "SPEAKER_00"),
    ],
    "language": "en",
}


class TestLoadSegments(unittest.TestCase):
    def test_drops_empty_and_strips(self):
        out = load_segments(SAMPLE)
        self.assertEqual(len(out), 4)
        self.assertEqual(out[0]["text"], "There's a job in Whistler.")

    def test_missing_speaker_inherits_previous(self):
        out = load_segments({"segments": [
            seg(0.0, 1.0, "First.", "SPEAKER_01"),
            seg(1.0, 2.0, "Interjection with no speaker."),
        ]})
        self.assertEqual(out[1]["speaker"], "SPEAKER_01")

    def test_missing_speaker_with_nothing_to_inherit(self):
        out = load_segments({"segments": [seg(0.0, 1.0, "Orphan.")]})
        self.assertEqual(out[0]["speaker"], "UNKNOWN")


class TestNaming(unittest.TestCase):
    def test_busiest_speaker_gets_first_name(self):
        segments = load_segments(SAMPLE)
        # SPEAKER_01 speaks 60s, SPEAKER_00 speaks 5s.
        self.assertEqual(name_by_talk_time(segments, ["Dad", "Isaiah"]),
                         {"SPEAKER_01": "Dad", "SPEAKER_00": "Isaiah"})

    def test_extra_labels_keep_their_id(self):
        segments = load_segments({"segments": [
            seg(0.0, 10.0, "a", "SPEAKER_00"),
            seg(10.0, 15.0, "b", "SPEAKER_01"),
            seg(15.0, 17.0, "c", "SPEAKER_02"),
        ]})
        mapping = name_by_talk_time(segments, ["Dad", "Isaiah"])
        self.assertEqual(mapping, {"SPEAKER_00": "Dad", "SPEAKER_01": "Isaiah"})
        self.assertNotIn("SPEAKER_02", mapping)

    def test_parse_map(self):
        self.assertEqual(parse_map("SPEAKER_00=Isaiah, SPEAKER_01=Dad"),
                         {"SPEAKER_00": "Isaiah", "SPEAKER_01": "Dad"})
        self.assertEqual(parse_map(None), {})
        with self.assertRaises(ValueError):
            parse_map("SPEAKER_00")


class TestRender(unittest.TestCase):
    def test_markdown_shape_matches_the_repo_format(self):
        segments = load_segments(SAMPLE)
        md = render(segments, title="Marigold Ave 9", date="2026-08-17",
                    source="Marigold Ave 9.json",
                    mapping={"SPEAKER_01": "Dad", "SPEAKER_00": "Isaiah"},
                    named_by_talk_time=True)
        self.assertIn("**[00:00:00] Dad:** There's a job in Whistler.", md)
        self.assertIn("**[00:00:31] Isaiah:** Yeah.", md)
        self.assertIn("**[01:01:01] Isaiah:** I'd rather make 500 grand.", md)
        self.assertIn("- **Speakers:** Dad, Isaiah", md)
        self.assertIn("- **Duration:** 01:01:05", md)
        # The heuristic must announce itself so a wrong guess is catchable.
        self.assertIn("total speaking time", md)

    def test_unnamed_keeps_raw_labels_and_no_heuristic_note(self):
        md = render(load_segments(SAMPLE), title="t", date="2026-08-17",
                    source="t.json", mapping={}, named_by_talk_time=False)
        self.assertIn("**[00:00:00] SPEAKER_01:**", md)
        self.assertNotIn("total speaking time", md)


class TestConvert(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "Marigold Ave 9.json"
        self.path.write_text(json.dumps(SAMPLE), encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def test_names_applied(self):
        md = convert(self.path, names=["Dad", "Isaiah"])
        self.assertIn("] Dad:** There's a job in Whistler.", md)
        self.assertIn("# Marigold Ave 9", md)

    def test_explicit_map_overrides_the_heuristic(self):
        md = convert(self.path, names=["Dad", "Isaiah"],
                     explicit={"SPEAKER_01": "Isaiah", "SPEAKER_00": "Dad"})
        self.assertIn("] Isaiah:** There's a job in Whistler.", md)
        self.assertNotIn("total speaking time", md)

    def test_empty_json_raises(self):
        empty = self.path.with_name("empty.json")
        empty.write_text('{"segments": []}', encoding="utf-8")
        with self.assertRaises(ValueError):
            convert(empty)


if __name__ == "__main__":
    unittest.main()
