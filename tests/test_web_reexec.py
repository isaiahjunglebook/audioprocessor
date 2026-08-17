"""Tests for the web page restarting itself under the repo virtualenv.

Launching with the system `python3` is the natural thing to type, but PyYAML
lives in the repo virtualenv — without the restart the page comes up with no
projects and no defaults, looking like a config mistake.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("web_ui", REPO / "scripts" / "web_ui.py")
web_ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(web_ui)


class TestReexecInVenv(unittest.TestCase):
    def setUp(self):
        self.venv_python = REPO / ".venv" / "bin" / "python"
        # Never touch a real virtualenv, and never write through a symlink.
        if self.venv_python.exists() or self.venv_python.is_symlink():
            self.skipTest("a .venv already exists here; leaving it alone")

    def _make_fake_venv(self):
        self.venv_python.parent.mkdir(parents=True, exist_ok=True)
        self.venv_python.write_text("#!/bin/sh\nexit 0\n")
        self.venv_python.chmod(0o755)
        self.addCleanup(self._remove_fake_venv)

    def _remove_fake_venv(self):
        self.venv_python.unlink(missing_ok=True)
        for folder in (self.venv_python.parent, self.venv_python.parent.parent):
            try:
                folder.rmdir()
            except OSError:
                pass

    def test_no_restart_when_yaml_is_importable(self):
        self._make_fake_venv()
        with mock.patch.object(web_ui.os, "execv") as execv:
            web_ui._reexec_in_venv()
        execv.assert_not_called()

    def test_restarts_when_yaml_is_missing(self):
        self._make_fake_venv()
        # A None entry in sys.modules makes `import yaml` raise ImportError.
        with mock.patch.dict(sys.modules, {"yaml": None}), \
                mock.patch.object(web_ui.os, "execv") as execv:
            web_ui._reexec_in_venv()
        execv.assert_called_once()
        self.assertEqual(execv.call_args[0][0], str(self.venv_python))
        self.assertIn("web_ui.py", execv.call_args[0][1][1])

    def test_no_restart_when_there_is_no_venv(self):
        # Nothing better to switch to — carry on with built-in defaults
        # rather than dying on a missing interpreter.
        with mock.patch.dict(sys.modules, {"yaml": None}), \
                mock.patch.object(web_ui.os, "execv") as execv:
            web_ui._reexec_in_venv()
        execv.assert_not_called()

    def test_never_loops_when_already_running_that_interpreter(self):
        self._make_fake_venv()
        with mock.patch.dict(sys.modules, {"yaml": None}), \
                mock.patch.object(web_ui.sys, "executable", str(self.venv_python)), \
                mock.patch.object(web_ui.os, "execv") as execv:
            web_ui._reexec_in_venv()
        execv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
