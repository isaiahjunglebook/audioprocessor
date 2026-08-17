"""Unit tests for the config-value reader used by the shell scripts."""

import unittest
from pathlib import Path

from call_processor.paths import format_value, lookup, main


CFG = {
    "paths": {"recordings_dir": "~/Documents/Raw", "transcripts_dir": ""},
    "whisperx": {"speaker_names": ["Dad", "Isaiah"], "num_speakers": 2},
    "summarize": {"enabled": False},
}


class TestLookup(unittest.TestCase):
    def test_nested_key(self):
        self.assertEqual(lookup(CFG, "paths.recordings_dir"), "~/Documents/Raw")
        self.assertEqual(lookup(CFG, "whisperx.num_speakers"), 2)

    def test_missing_key_is_none_not_an_error(self):
        self.assertIsNone(lookup(CFG, "paths.nope"))
        self.assertIsNone(lookup(CFG, "nope.nope"))
        self.assertIsNone(lookup(CFG, "paths.recordings_dir.deeper"))


class TestFormatValue(unittest.TestCase):
    def test_list_becomes_comma_separated(self):
        self.assertEqual(format_value(["Dad", "Isaiah"]), "Dad,Isaiah")
        self.assertEqual(format_value([" Dad ", "", "Isaiah"]), "Dad,Isaiah")

    def test_none_and_empty(self):
        self.assertEqual(format_value(None), "")
        self.assertEqual(format_value(""), "")

    def test_bool_and_number(self):
        self.assertEqual(format_value(False), "false")
        self.assertEqual(format_value(2), "2")

    def test_tilde_expanded_only_for_paths(self):
        self.assertEqual(format_value("~/Docs", is_path=True),
                         str(Path.home() / "Docs"))
        self.assertEqual(format_value("~/Docs", is_path=False), "~/Docs")


class TestCli(unittest.TestCase):
    def test_wrong_arity_is_an_error(self):
        self.assertEqual(main([]), 2)
        self.assertEqual(main(["a", "b"]), 2)

    def test_unset_key_exits_zero(self):
        # "Not configured" is a normal state — callers fall back to their own
        # defaults, so this must not look like a failure to the shell.
        self.assertEqual(main(["paths.definitely_not_set"]), 0)


if __name__ == "__main__":
    unittest.main()
