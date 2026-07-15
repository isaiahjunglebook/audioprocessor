"""Render merged turns into the Markdown transcript."""

from __future__ import annotations

import re
from pathlib import Path


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w]+", "-", name.lower(), flags=re.UNICODE).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "call"


def render_transcript(turns: list[dict], *, call_name: str, date: str,
                      participants: list[str], source_files: list[str],
                      timestamps: bool = True, time: str | None = None) -> str:
    duration = max((t["end"] for t in turns), default=0)
    lines = [
        f"# {call_name}",
        "",
        f"- **Date:** {date}" + (f" · {time}" if time else ""),
        f"- **Participants:** {', '.join(participants)}",
        f"- **Duration:** {format_timestamp(duration)}",
        f"- **Source files:** {', '.join(source_files)}",
        "",
        "---",
        "",
    ]
    for turn in turns:
        prefix = f"[{format_timestamp(turn['start'])}] " if timestamps else ""
        lines.append(f"**{prefix}{turn['speaker']}:** {turn['text']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_transcript(content: str, output_dir: str | Path, call_slug: str) -> Path:
    out_dir = Path(output_dir) / call_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "transcript.md"
    path.write_text(content, encoding="utf-8")
    return path
