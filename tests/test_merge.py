"""Unit tests for the timestamp merge logic — pure data in, turns out.

Runnable with either ``python -m unittest discover tests`` or ``pytest tests/``.
"""

import unittest

from call_processor.merge import merge_segments


def seg(start, end, speaker, text):
    return {"start": start, "end": end, "speaker": speaker, "text": text}


class TestMergeSegments(unittest.TestCase):
    def test_interleaved_two_speakers_chronological(self):
        # Hand-made segments from two "tracks", deliberately out of order.
        isaiah = [
            seg(0.0, 2.0, "Isaiah", "Hey Jane, thanks for hopping on."),
            seg(11.0, 14.0, "Isaiah", "That's huge."),
        ]
        jane = [
            seg(4.0, 9.0, "Jane", "Really well actually."),
            seg(15.0, 17.0, "Jane", "Thanks!"),
        ]
        turns = merge_segments(jane + isaiah)

        self.assertEqual(
            [t["speaker"] for t in turns], ["Isaiah", "Jane", "Isaiah", "Jane"]
        )
        starts = [t["start"] for t in turns]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(turns[0]["text"], "Hey Jane, thanks for hopping on.")

    def test_consecutive_same_speaker_collapsed(self):
        segments = [
            seg(0.0, 2.0, "Isaiah", "So the plan is"),
            seg(2.3, 4.0, "Isaiah", "we ship on Friday"),
            seg(4.1, 5.0, "Isaiah", "assuming tests pass."),
            seg(6.0, 8.0, "Jane", "Sounds good."),
        ]
        turns = merge_segments(segments)

        self.assertEqual(len(turns), 2)
        self.assertEqual(
            turns[0]["text"], "So the plan is we ship on Friday assuming tests pass."
        )
        self.assertEqual(turns[0]["start"], 0.0)
        self.assertEqual(turns[0]["end"], 5.0)
        self.assertEqual(turns[1]["speaker"], "Jane")

    def test_same_speaker_long_gap_starts_new_turn(self):
        segments = [
            seg(0.0, 2.0, "Isaiah", "First thought."),
            seg(10.0, 12.0, "Isaiah", "Different thought much later."),
        ]
        turns = merge_segments(segments, merge_gap_seconds=1.5)
        self.assertEqual(len(turns), 2)

    def test_same_speaker_within_gap_threshold_merges(self):
        segments = [
            seg(0.0, 2.0, "Isaiah", "First half"),
            seg(3.0, 4.0, "Isaiah", "second half."),
        ]
        turns = merge_segments(segments, merge_gap_seconds=1.5)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["text"], "First half second half.")

    def test_interjection_splits_speaker_turns(self):
        # Jane interjects between two Isaiah segments that are close in time —
        # sorting by start puts her in the middle, so Isaiah gets two turns.
        segments = [
            seg(0.0, 3.0, "Isaiah", "Let me walk you through the numbers."),
            seg(3.2, 4.0, "Jane", "Quick question first."),
            seg(4.2, 6.0, "Isaiah", "Sure, go ahead."),
        ]
        turns = merge_segments(segments)
        self.assertEqual([t["speaker"] for t in turns], ["Isaiah", "Jane", "Isaiah"])

    def test_overlapping_segments_keep_max_end(self):
        segments = [
            seg(0.0, 5.0, "Isaiah", "Long segment."),
            seg(1.0, 3.0, "Isaiah", "Overlapping aside."),
        ]
        turns = merge_segments(segments)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["end"], 5.0)

    def test_empty_and_whitespace_segments_dropped(self):
        segments = [
            seg(0.0, 1.0, "Isaiah", "   "),
            seg(2.0, 3.0, "Jane", "Hello."),
            seg(4.0, 5.0, "Jane", ""),
        ]
        turns = merge_segments(segments)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["speaker"], "Jane")

    def test_empty_input(self):
        self.assertEqual(merge_segments([]), [])

    def test_input_not_mutated(self):
        segments = [seg(2.0, 3.0, "A", "b"), seg(0.0, 1.0, "A", "a")]
        snapshot = [dict(s) for s in segments]
        merge_segments(segments)
        self.assertEqual(segments, snapshot)


if __name__ == "__main__":
    unittest.main()
