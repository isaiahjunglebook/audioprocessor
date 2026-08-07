"""Unit tests for sentence-granularity splitting — pure data in, sentences out.

Runnable with either ``python -m unittest discover tests`` or ``pytest tests/``.
"""

import unittest

from call_processor.sentences import (ends_sentence, split_into_sentences,
                                      split_segment)


def words(*pairs):
    """words(("Hi.", 0.0, 0.5), ...) -> word dicts as the backend emits them."""
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


def seg(start, end, speaker, text, word_list=None):
    s = {"start": start, "end": end, "speaker": speaker, "text": text}
    if word_list is not None:
        s["words"] = word_list
    return s


class TestEndsSentence(unittest.TestCase):
    def test_terminal_punctuation(self):
        for w in ("done.", "really?", "wow!", "hmm…", 'said."', "(yes.)"):
            self.assertTrue(ends_sentence(w), w)

    def test_mid_sentence_words(self):
        for w in ("the", "well,", "so", "half-"):
            self.assertFalse(ends_sentence(w), w)

    def test_abbreviations_are_not_sentence_ends(self):
        for w in ("Dr.", "etc.", "p.m.", "Mrs."):
            self.assertFalse(ends_sentence(w), w)

    def test_single_initial_is_not_a_sentence_end(self):
        self.assertFalse(ends_sentence("J."))
        self.assertTrue(ends_sentence("Jo."))


class TestSplitSegment(unittest.TestCase):
    def test_one_segment_splits_into_multiple_sentences(self):
        segment = seg(0.0, 6.0, "Isaiah",
                      "So we shipped it. It went fine.",
                      words(("So", 0.0, 0.3), (" we", 0.3, 0.6),
                            (" shipped", 0.6, 1.1), (" it.", 1.1, 1.6),
                            (" It", 3.0, 3.3), (" went", 3.3, 3.7),
                            (" fine.", 3.7, 4.2)))
        out = split_segment(segment)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["text"], "So we shipped it.")
        self.assertEqual(out[1]["text"], "It went fine.")
        # Each sentence carries the timing of its own first and last word —
        # the whole point: no inherited or interpolated timestamps.
        self.assertEqual((out[0]["start"], out[0]["end"]), (0.0, 1.6))
        self.assertEqual((out[1]["start"], out[1]["end"]), (3.0, 4.2))
        self.assertEqual(out[1]["speaker"], "Isaiah")

    def test_trailing_words_without_punctuation_still_emit(self):
        segment = seg(0.0, 2.0, "Jane", "Yeah exactly",
                      words(("Yeah", 0.0, 0.4), (" exactly", 0.4, 1.0)))
        out = split_segment(segment)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["text"], "Yeah exactly")
        self.assertEqual(out[0]["end"], 1.0)

    def test_abbreviation_does_not_split_mid_sentence(self):
        segment = seg(0.0, 4.0, "Jane", "Dr. Cooper called at 4 p.m. today.",
                      words(("Dr.", 0.0, 0.4), (" Cooper", 0.4, 0.9),
                            (" called", 0.9, 1.3), (" at", 1.3, 1.5),
                            (" 4", 1.5, 1.7), (" p.m.", 1.7, 2.1),
                            (" today.", 2.1, 2.6)))
        out = split_segment(segment)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["text"], "Dr. Cooper called at 4 p.m. today.")

    def test_segment_without_word_timings_passes_through(self):
        segment = seg(1.0, 3.0, "Isaiah", "No words available. Two sentences.")
        out = split_segment(segment)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["text"], "No words available. Two sentences.")
        self.assertNotIn("words", out[0])

    def test_empty_segment_is_dropped(self):
        self.assertEqual(split_segment(seg(0.0, 1.0, "Isaiah", "   ")), [])


class TestSplitIntoSentences(unittest.TestCase):
    def test_sorted_across_tracks_and_never_collapsed(self):
        # Same speaker, back-to-back — merge_segments would collapse these into
        # one turn; sentence mode must keep a timestamp on each.
        isaiah = [
            seg(0.0, 2.0, "Isaiah", "First point.",
                words(("First", 0.0, 0.5), (" point.", 0.5, 1.0))),
            seg(2.1, 4.0, "Isaiah", "Second point.",
                words(("Second", 2.1, 2.6), (" point.", 2.6, 3.0))),
        ]
        jane = [
            seg(1.2, 1.8, "Jane", "Right.", words((" Right.", 1.2, 1.8))),
        ]
        out = split_into_sentences(isaiah + jane)

        self.assertEqual([s["text"] for s in out],
                         ["First point.", "Right.", "Second point."])
        starts = [s["start"] for s in out]
        self.assertEqual(starts, sorted(starts))

    def test_no_word_key_leaks_into_output(self):
        out = split_into_sentences([
            seg(0.0, 1.0, "Isaiah", "Hi.", words(("Hi.", 0.0, 1.0)))
        ])
        self.assertEqual(set(out[0]), {"start", "end", "speaker", "text"})


if __name__ == "__main__":
    unittest.main()
