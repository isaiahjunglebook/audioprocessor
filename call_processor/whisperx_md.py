"""Turn WhisperX diarized JSON into the transcript Markdown this repo writes.

WhisperX gives you `SPEAKER_00` / `SPEAKER_01` — it separates voices but has no
idea whose they are. This module converts its JSON into the same
`**[HH:MM:SS] Name:** text` format as the multitrack pipeline, optionally
putting real names on those anonymous labels.

Naming works by total speaking time: pass the people in order of how much they
talk and the busiest label gets the first name. That is a heuristic, not
knowledge, so the header records that it was used — if two people talk about
equally, check the first few lines before trusting it.

Pure standard library, so it runs under the WhisperX virtualenv or this repo's.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

UNKNOWN = "UNKNOWN"


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def load_segments(data: dict) -> list[dict]:
    """Normalise WhisperX JSON into {start, end, speaker, text} dicts.

    A segment can arrive without a ``speaker`` when diarization found no
    overlapping turn for it — usually a short interjection. Rather than drop
    the words, it inherits the previous segment's speaker, which is right far
    more often than it's wrong; the first such segment has nothing to inherit
    and is labelled UNKNOWN.
    """
    out: list[dict] = []
    last_speaker = UNKNOWN
    for seg in data.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = seg.get("speaker") or last_speaker
        last_speaker = speaker
        out.append({
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0)),
            "speaker": speaker,
            "text": text,
        })
    return out


def speaking_time(segments: list[dict]) -> dict[str, float]:
    """Total seconds of speech per speaker label."""
    totals: dict[str, float] = {}
    for seg in segments:
        totals[seg["speaker"]] = totals.get(seg["speaker"], 0.0) + max(
            0.0, seg["end"] - seg["start"])
    return totals


def name_by_talk_time(segments: list[dict], names: list[str]) -> dict[str, str]:
    """Map SPEAKER_xx -> real name, busiest speaker first.

    Extra labels beyond the names supplied keep their original id rather than
    being forced onto a name that isn't theirs.
    """
    totals = speaking_time(segments)
    ranked = sorted(totals, key=lambda s: (-totals[s], s))
    ranked = [s for s in ranked if s != UNKNOWN]
    return {label: names[i] for i, label in enumerate(ranked) if i < len(names)}


def parse_map(arg: str | None) -> dict[str, str]:
    """Parse "SPEAKER_00=Isaiah,SPEAKER_01=Dad" into a dict."""
    mapping: dict[str, str] = {}
    for pair in (arg or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"Bad --map entry '{pair}': expected LABEL=Name")
        label, _, name = pair.partition("=")
        mapping[label.strip()] = name.strip()
    return mapping


def render(segments: list[dict], *, title: str, date: str, source: str,
           mapping: dict[str, str], named_by_talk_time: bool) -> str:
    labelled = [{**s, "speaker": mapping.get(s["speaker"], s["speaker"])}
                for s in segments]
    speakers = sorted({s["speaker"] for s in labelled})
    duration = max((s["end"] for s in labelled), default=0)

    lines = [
        f"# {title}",
        "",
        f"- **Date:** {date}",
        f"- **Speakers:** {', '.join(speakers)}",
        f"- **Duration:** {format_timestamp(duration)}",
        f"- **Source:** {source}",
    ]
    if named_by_talk_time:
        # Say how the names got attached so a wrong guess is auditable.
        lines.append("- **Speaker names assigned by:** total speaking time "
                     "(most talkative first) — spot-check the first exchange")
    lines += ["", "---", ""]

    for seg in labelled:
        lines.append(f"**[{format_timestamp(seg['start'])}] {seg['speaker']}:** {seg['text']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def convert(json_path: Path, *, names: list[str] | None = None,
            explicit: dict[str, str] | None = None,
            title: str | None = None) -> str:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    segments = load_segments(data)
    if not segments:
        raise ValueError(f"No speech segments found in {json_path}")

    mapping: dict[str, str] = {}
    named_by_talk_time = False
    if names:
        mapping = name_by_talk_time(segments, names)
        named_by_talk_time = True
    if explicit:  # an explicit map always wins over the heuristic
        mapping.update(explicit)

    return render(
        segments,
        title=title or Path(json_path).stem,
        date=_dt.date.today().isoformat(),
        source=Path(json_path).name,
        mapping=mapping,
        named_by_talk_time=named_by_talk_time and not explicit,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m call_processor.whisperx_md",
        description="Convert WhisperX diarized JSON into speaker-labeled Markdown.")
    p.add_argument("json_file", help="WhisperX .json output")
    p.add_argument("-o", "--out", help="Where to write the .md (default: stdout)")
    p.add_argument("--names", help='Names in order of who talks most, e.g. "Dad,Isaiah"')
    p.add_argument("--map", dest="speaker_map",
                   help='Exact mapping, e.g. "SPEAKER_00=Isaiah,SPEAKER_01=Dad"')
    p.add_argument("--title", help="Title for the transcript header")
    args = p.parse_args(argv)

    names = [n.strip() for n in args.names.split(",") if n.strip()] if args.names else None
    try:
        content = convert(Path(args.json_file), names=names,
                          explicit=parse_map(args.speaker_map), title=args.title)
    except (ValueError, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print(f"Wrote {out}")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
