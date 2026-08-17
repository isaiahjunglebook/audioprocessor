"""Named projects: a set of folders and speakers you switch between.

One tool, several bodies of work — memos with your dad, client interviews,
research calls — each with its own input folder, output folder and cast of
speakers. A project is just those settings under a name:

    default_project: castle
    projects:
      castle:
        recordings_dir:  ~/Documents/CASTLE BLINDS/Raw Voice Memos
        transcripts_dir: ~/Documents/CASTLE BLINDS/Timestamped Transcribed Memos
        speaker_names:   ["Dad", "Isaiah"]
      interviews:
        recordings_dir:  ~/Documents/Interviews/raw
        transcripts_dir: ~/Documents/Interviews/transcripts
        speaker_names:   ["Isaiah", "Guest"]

Anything a project doesn't set falls back to the top-level `paths:` and
`whisperx:` sections, so a single-project setup needs no `projects:` block at
all and nothing here changes for it.
"""

from __future__ import annotations

import argparse
import sys

from . import config as config_mod
from .paths import format_value

# key -> where to look for it outside a project block
_FALLBACKS = {
    "recordings_dir": "paths",
    "transcripts_dir": "paths",
    "speaker_names": "whisperx",
    "num_speakers": "whisperx",
    "model": "whisperx",
    "venv": "whisperx",
}
_PATH_KEYS = {"recordings_dir", "transcripts_dir", "venv"}


def list_projects(cfg: dict) -> list[str]:
    projects = cfg.get("projects")
    return sorted(projects) if isinstance(projects, dict) else []


def default_project(cfg: dict) -> str | None:
    """The project to use when none is named.

    An explicit ``default_project`` wins. Otherwise a lone project is
    unambiguous enough to pick on its own; with several, guessing would be
    worse than falling back to the top-level settings.
    """
    named = cfg.get("default_project")
    available = list_projects(cfg)
    if named and named in available:
        return named
    if len(available) == 1:
        return available[0]
    return None


def get(cfg: dict, key: str, project: str | None = None):
    """Look a setting up in a project, then in its top-level section."""
    if project is None:
        project = default_project(cfg)
    if project:
        block = (cfg.get("projects") or {}).get(project)
        if isinstance(block, dict) and block.get(key) not in (None, "", []):
            return block[key]
    section = cfg.get(_FALLBACKS.get(key, ""), {})
    if isinstance(section, dict):
        return section.get(key)
    return None


def resolve(cfg: dict, project: str | None = None) -> dict:
    """Every setting a run needs, with fallbacks already applied."""
    if project is None:
        project = default_project(cfg)
    return {"project": project or "",
            **{key: get(cfg, key, project) for key in _FALLBACKS}}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m call_processor.projects",
        description="Read project settings, for shell scripts that can't parse YAML.")
    p.add_argument("--list", action="store_true", help="Print project names, one per line")
    p.add_argument("--get", metavar="KEY", help="Print one setting (e.g. transcripts_dir)")
    p.add_argument("--project", default=None, help="Which project (default: default_project)")
    args = p.parse_args(argv)

    cfg = config_mod.load_config(None)
    if args.list:
        for name in list_projects(cfg):
            print(name)
        return 0
    if args.get:
        if args.project and args.project not in list_projects(cfg):
            print(f"No project named '{args.project}' in config.yaml. "
                  f"Available: {', '.join(list_projects(cfg)) or '(none)'}", file=sys.stderr)
            return 1
        print(format_value(get(cfg, args.get, args.project),
                           is_path=args.get in _PATH_KEYS))
        return 0
    p.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
