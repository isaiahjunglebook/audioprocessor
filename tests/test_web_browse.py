"""Tests for the native folder chooser the page opens through the server."""

import importlib.util
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("web_ui", REPO / "scripts" / "web_ui.py")
web_ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(web_ui)


def _result(returncode=0, stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


class TestChooseFolderDialog(unittest.TestCase):
    def test_returns_none_without_osascript(self):
        # Linux, or a stripped-down Mac: the button stays hidden rather than
        # the page offering something that can't work.
        with mock.patch.object(web_ui.shutil, "which", return_value=None):
            self.assertIsNone(web_ui.choose_folder_dialog())

    def test_returns_the_chosen_path(self):
        with mock.patch.object(web_ui.shutil, "which", return_value="/usr/bin/osascript"), \
                mock.patch.object(web_ui.subprocess, "run",
                                  return_value=_result(0, "/Users/me/Transcripts\n")):
            self.assertEqual(web_ui.choose_folder_dialog(), "/Users/me/Transcripts")

    def test_cancel_returns_none(self):
        # osascript exits non-zero when the user hits Cancel; the page keeps
        # whatever was already typed rather than blanking the field.
        with mock.patch.object(web_ui.shutil, "which", return_value="/usr/bin/osascript"), \
                mock.patch.object(web_ui.subprocess, "run", return_value=_result(1, "")):
            self.assertIsNone(web_ui.choose_folder_dialog())

    def test_osascript_failure_is_survivable(self):
        with mock.patch.object(web_ui.shutil, "which", return_value="/usr/bin/osascript"), \
                mock.patch.object(web_ui.subprocess, "run",
                                  side_effect=OSError("boom")):
            self.assertIsNone(web_ui.choose_folder_dialog())

    def test_existing_folder_becomes_the_dialog_start_point(self):
        with mock.patch.object(web_ui.shutil, "which", return_value="/usr/bin/osascript"), \
                mock.patch.object(web_ui.subprocess, "run",
                                  return_value=_result(0, "/x")) as run:
            web_ui.choose_folder_dialog(str(REPO))
        script = run.call_args[0][0][-1]
        self.assertIn("default location POSIX file", script)
        self.assertIn(str(REPO), script)

    def test_missing_folder_is_not_used_as_a_start_point(self):
        with mock.patch.object(web_ui.shutil, "which", return_value="/usr/bin/osascript"), \
                mock.patch.object(web_ui.subprocess, "run",
                                  return_value=_result(0, "/x")) as run:
            web_ui.choose_folder_dialog("/nope/not/here")
        self.assertNotIn("default location", run.call_args[0][0][-1])

    def test_quotes_in_a_path_cannot_break_out_of_the_applescript(self):
        evil = '/tmp/a" & (do shell script "echo pwned") & "'
        with mock.patch.object(web_ui.shutil, "which", return_value="/usr/bin/osascript"), \
                mock.patch.object(web_ui.Path, "is_dir", return_value=True), \
                mock.patch.object(web_ui.subprocess, "run",
                                  return_value=_result(0, "/x")) as run:
            web_ui.choose_folder_dialog(evil)
        script = run.call_args[0][0][-1]
        # The payload's quote must arrive escaped, so it can't close the
        # AppleScript string literal and start executing what follows.
        self.assertIn('/tmp/a\\" &', script)
        # Every quote inside the path is escaped; the only bare quotes left
        # are the two the template itself opens and closes the path with.
        path_part = script.split("default location POSIX file ", 1)[1]
        bare_quotes = len(re.findall(r'(?<!\\)"', path_part))
        self.assertEqual(bare_quotes, 2)


if __name__ == "__main__":
    unittest.main()
