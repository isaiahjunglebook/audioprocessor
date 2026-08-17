"""Unit tests for named projects and their fallback behaviour."""

import unittest

from call_processor.projects import (default_project, get, list_projects,
                                     resolve)

CFG = {
    "default_project": "castle",
    "paths": {"recordings_dir": "~/Fallback/raw", "transcripts_dir": "~/Fallback/out"},
    "whisperx": {"speaker_names": ["Someone"], "num_speakers": 2,
                 "model": "large-v3", "venv": "~/wx/.venv"},
    "projects": {
        "castle": {
            "recordings_dir": "~/CASTLE/raw",
            "transcripts_dir": "~/CASTLE/out",
            "speaker_names": ["Dad", "Isaiah"],
        },
        "interviews": {
            "recordings_dir": "~/Interviews/raw",
            "transcripts_dir": "~/Interviews/out",
            "num_speakers": 3,
        },
    },
}


class TestListingAndDefault(unittest.TestCase):
    def test_list_is_sorted(self):
        self.assertEqual(list_projects(CFG), ["castle", "interviews"])

    def test_no_projects_block(self):
        self.assertEqual(list_projects({}), [])
        self.assertIsNone(default_project({}))

    def test_explicit_default_wins(self):
        self.assertEqual(default_project(CFG), "castle")

    def test_single_project_is_the_default(self):
        cfg = {"projects": {"only": {"transcripts_dir": "/x"}}}
        self.assertEqual(default_project(cfg), "only")

    def test_several_projects_with_no_default_picks_none(self):
        # Guessing between them would silently write to the wrong folder.
        cfg = {"projects": {"a": {}, "b": {}}}
        self.assertIsNone(default_project(cfg))

    def test_unknown_default_is_ignored(self):
        cfg = {"default_project": "ghost", "projects": {"a": {}, "b": {}}}
        self.assertIsNone(default_project(cfg))


class TestGet(unittest.TestCase):
    def test_project_value_wins(self):
        self.assertEqual(get(CFG, "transcripts_dir", "interviews"), "~/Interviews/out")

    def test_falls_back_to_top_level_section(self):
        # 'interviews' sets no speaker_names, so whisperx.speaker_names applies.
        self.assertEqual(get(CFG, "speaker_names", "interviews"), ["Someone"])
        self.assertEqual(get(CFG, "model", "castle"), "large-v3")

    def test_uses_default_project_when_none_named(self):
        self.assertEqual(get(CFG, "transcripts_dir"), "~/CASTLE/out")

    def test_empty_project_value_falls_through(self):
        cfg = {"projects": {"p": {"transcripts_dir": ""}},
               "paths": {"transcripts_dir": "/real"}}
        self.assertEqual(get(cfg, "transcripts_dir", "p"), "/real")

    def test_no_projects_at_all_uses_top_level(self):
        cfg = {"paths": {"transcripts_dir": "/plain"}}
        self.assertEqual(get(cfg, "transcripts_dir"), "/plain")

    def test_missing_everywhere_is_none(self):
        self.assertIsNone(get({}, "transcripts_dir"))


class TestResolve(unittest.TestCase):
    def test_full_settings_with_mixed_sources(self):
        settings = resolve(CFG, "interviews")
        self.assertEqual(settings["project"], "interviews")
        self.assertEqual(settings["recordings_dir"], "~/Interviews/raw")
        self.assertEqual(settings["num_speakers"], 3)          # from the project
        self.assertEqual(settings["speaker_names"], ["Someone"])  # from whisperx
        self.assertEqual(settings["venv"], "~/wx/.venv")


if __name__ == "__main__":
    unittest.main()
