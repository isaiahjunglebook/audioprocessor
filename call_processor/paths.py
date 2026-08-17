"""Read one config value, for shell scripts that can't parse YAML.

The batch scripts and the web page all need the same few settings — where
recordings live, where transcripts go, which virtualenv holds WhisperX. Rather
than each script growing its own YAML reader (or the user retyping long paths
on every run), they ask this module:

    python -m call_processor.paths paths.recordings_dir

Prints the value and nothing else, so a shell can capture it directly. An unset
or missing key prints an empty line and exits 0 — "not configured" is a normal
state, not an error, and callers fall back to their own defaults.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import config as config_mod

# Keys whose values are filesystem paths and should have ~ expanded.
_PATH_SUFFIXES = ("_dir", "venv")


def lookup(cfg: dict, dotted_key: str):
    """Fetch cfg["a"]["b"] for "a.b", or None if any part is missing."""
    node = cfg
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def format_value(value, *, is_path: bool = False) -> str:
    """Render a config value as a single line of shell-friendly text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v).strip() for v in value if str(v).strip())
    text = str(value).strip()
    if text and is_path:
        text = str(Path(text).expanduser())
    return text


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: python -m call_processor.paths <dotted.key>", file=sys.stderr)
        return 2
    key = args[0]
    cfg = config_mod.load_config(None)
    is_path = key.endswith(_PATH_SUFFIXES)
    print(format_value(lookup(cfg, key), is_path=is_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
