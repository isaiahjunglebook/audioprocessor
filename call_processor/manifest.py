"""Write a machine-readable manifest.json for each processed call.

This is the stable integration contract for downstream tools (e.g. a quote /
marketing database). Instead of parsing folder names or Markdown headers, a
consumer reads output/<slug>/manifest.json for structured metadata: date,
participants, tags, and absolute paths to every artifact.

Tags are derived from a keyword map in config (`tags:`), matched
case-insensitively against the Zoom topic and composed call title. This lets a
downstream tool select, for example, every call tagged "expedition" or "squad".
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def derive_tags(text_sources: list[str], tag_map: dict[str, list[str]]) -> list[str]:
    """Return sorted tags whose keywords appear in any of the text sources.

    tag_map example: {"expedition": ["expedition", "where we dropping", "intro"],
                      "squad": ["squad"]}
    """
    haystack = " ".join(s for s in text_sources if s).casefold()
    hits = []
    for tag, keywords in (tag_map or {}).items():
        for kw in keywords:
            if kw and kw.casefold() in haystack:
                hits.append(tag)
                break
    return sorted(set(hits))


def write_manifest(output_dir: Path, call_slug: str, *, data: dict) -> Path:
    """Write output/<slug>/manifest.json atomically and return its path.

    The manifest is the last artifact written for a call AND is written via
    temp-file + rename, so downstream watchers can safely treat the appearance
    of a complete manifest.json as the "this call is fully processed" signal.
    """
    folder = Path(output_dir) / call_slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    tmp = folder / ".manifest.json.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem
    return path
