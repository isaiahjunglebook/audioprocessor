"""CLI entry point and pipeline orchestration.

Pipeline: discover tracks -> resolve speakers -> transcribe each track locally
-> merge segments by timestamp -> write transcript -> (optional) summarize +
update participant profiles via the Claude API.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import sys
from pathlib import Path

from . import config as config_mod
from .discover import discover_files


import re as _re

_ZOOM_FOLDER = _re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2})\.(\d{2})\.(\d{2}) (.+)$")


def parse_zoom_folder(label: str) -> tuple[str | None, str | None, str | None]:
    """Split Zoom's '2026-07-15 20.15.35 Where we dropping_' folder name into
    (date, time, topic). Returns (None, None, None-ish) for non-Zoom names."""
    m = _ZOOM_FOLDER.match(label)
    if not m:
        return None, None, None
    return m.group(1), f"{m.group(2)}:{m.group(3)}", m.group(5).strip()


def find_latest_recording(zoom_root: Path | None = None) -> Path | None:
    """Newest '<meeting>/Audio Record' folder under ~/Documents/Zoom, or None."""
    zoom_root = zoom_root or Path.home() / "Documents" / "Zoom"
    if not zoom_root.is_dir():
        return None
    candidates = [p / "Audio Record" for p in zoom_root.iterdir()
                  if p.is_dir() and (p / "Audio Record").is_dir()]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)
from .merge import merge_segments
from .render import render_transcript, slugify, write_transcript

log = logging.getLogger("call_processor")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m call_processor.main",
        description="Turn a folder of per-participant audio tracks into a "
                    "speaker-labeled transcript (+ optional summary and profiles).",
    )
    p.add_argument("--input", default=None,
                   help="Folder of per-participant audio files (e.g. Zoom's 'Audio Record'), "
                        "or a path to a single audio file")
    p.add_argument("--latest", action="store_true",
                   help="Process the most recent recording under ~/Documents/Zoom "
                        "instead of passing --input")
    p.add_argument("--email", action="store_true",
                   help="Email the summary when done (uses the email: section of config)")
    p.add_argument("--call-name", default=None,
                   help="Call name for the output folder and headers "
                        "(default: input folder name + date)")
    p.add_argument("--model", default=None, help="Whisper model (e.g. large-v3, medium)")
    p.add_argument("--language", default=None,
                   help="Audio language code, or 'auto' to auto-detect")
    p.add_argument("--no-summary", action="store_true",
                   help="Transcript only; skip all Claude API calls")
    p.add_argument("--timestamps-only", action="store_true",
                   help="One timestamped line per sentence, no speaker names, no "
                        "summary. For a single mixed recording you intend to align "
                        "against a separately speaker-attributed transcript.")
    p.add_argument("--granularity", choices=["turn", "sentence"], default=None,
                   help="'turn' (default) collapses consecutive same-speaker "
                        "segments; 'sentence' gives every sentence its own timestamp")
    p.add_argument("--no-speaker-labels", action="store_true",
                   help="Omit speaker names from the transcript lines")
    p.add_argument("--map", dest="speaker_map", default=None,
                   help='Speaker overrides: "filename_stem=Display Name,stem2=Name Two"')
    p.add_argument("--config", default=None, help="Path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return p


def _make_progress():
    """Return (progress, task_adder) using rich if available, else a no-op shim."""
    try:
        from rich.progress import (BarColumn, Progress, SpinnerColumn,
                                   TextColumn, TimeElapsedColumn)
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
        )
        return progress
    except ImportError:
        return None


def run(args: argparse.Namespace) -> int:
    config_mod.load_dotenv()
    cfg = config_mod.load_config(args.config)

    # CLI overrides
    if args.model:
        cfg["whisper"]["model"] = args.model
    if args.language:
        cfg["whisper"]["language"] = None if args.language == "auto" else args.language
    if args.no_summary:
        cfg["summarize"]["enabled"] = False
    if args.granularity:
        cfg["transcript"]["granularity"] = args.granularity
    if args.no_speaker_labels:
        cfg["transcript"]["speaker_labels"] = False
    if args.timestamps_only:
        # One purpose: a clean timestamped text track to align against another
        # transcript. Sentence lines, no names, no bleed filter (nothing can
        # bleed between tracks when there's one source), no API calls.
        cfg["transcript"]["granularity"] = "sentence"
        cfg["transcript"]["speaker_labels"] = False
        cfg["transcript"]["min_segment_duration"] = 0.0
        cfg["summarize"]["enabled"] = False
    overrides = {**cfg.get("speakers", {}), **config_mod.parse_speaker_map(args.speaker_map)}
    speaker_labels = cfg["transcript"].get("speaker_labels", True)

    today = _dt.date.today().isoformat()
    if args.latest:
        input_dir = find_latest_recording()
        if input_dir is None:
            log.error("No Zoom recording with an 'Audio Record' folder found under "
                      "~/Documents/Zoom. Record a call first, or pass --input.")
            return 1
        log.info("Latest recording: %s", input_dir)
    elif args.input:
        input_dir = Path(args.input).expanduser()
    else:
        log.error("Pass --input <folder or audio file> or --latest.")
        return 1
    # --input may name a single file; the manifest still records a folder.
    single_file = input_dir.is_file()
    source_dir = input_dir.parent if single_file else input_dir
    if single_file:
        folder_label = input_dir.stem
    else:
        # Zoom's audio lives in "<date time topic>/Audio Record" — pull the pieces apart.
        folder_label = input_dir.parent.name if input_dir.name == "Audio Record" else input_dir.name
    rec_date, rec_time, zoom_topic = parse_zoom_folder(folder_label)
    call_date = rec_date or today
    topic_clean = (zoom_topic or folder_label).rstrip("_ ").strip()
    # "Call Summary: X" is the title of a summarised call; a raw timestamped
    # transcript is just named after its source.
    default_name = topic_clean if args.timestamps_only else f"Call Summary: {topic_clean}"
    call_name = args.call_name or default_name
    # Files stay date-prefixed so output/ sorts chronologically in Finder.
    call_slug = slugify(f"{call_date} {call_name}")

    # 1. Discover + resolve speakers
    try:
        files = discover_files(input_dir, overrides)
    except (FileNotFoundError, ValueError) as e:
        log.error("%s", e)
        return 1

    if speaker_labels:
        print("Speaker mapping:")
        for path, speaker in files.items():
            print(f"  {path.name}  ->  {speaker}")
    else:
        print(f"Source: {', '.join(p.name for p in files)}  (no speaker labels)")

    # The bleed filter exists to drop the other speaker leaking between tracks.
    # With a single source there is no other track, so it only loses real words.
    if len(files) == 1 and cfg["transcript"]["min_segment_duration"] > 0:
        log.info("Single audio source — disabling the cross-track bleed filter.")
        cfg["transcript"]["min_segment_duration"] = 0.0

    # Fail early (but keep going to the transcript) if summarize is on with no key
    summarize_enabled = cfg["summarize"]["enabled"]
    if summarize_enabled and not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning(
            "Summarize is enabled but ANTHROPIC_API_KEY is not set (put it in .env). "
            "The transcript will still be written; summary and profiles will be skipped."
        )
        summarize_enabled = False

    # 2. Transcribe each track locally
    from .transcribe import get_backend  # deferred: needs faster-whisper installed
    backend = get_backend(
        cfg["whisper"].get("backend", "faster-whisper"),
        model_name=cfg["whisper"]["model"],
        compute_type=cfg["whisper"]["compute_type"],
        min_segment_duration=cfg["transcript"]["min_segment_duration"],
    )

    all_segments: list[dict] = []
    progress = _make_progress()
    if progress:
        with progress:
            task = progress.add_task("Transcribing", total=len(files))
            for path, speaker in files.items():
                progress.update(task, description=f"Transcribing {path.name}")
                all_segments.extend(
                    backend.transcribe_file(path, speaker, cfg["whisper"]["language"])
                )
                progress.advance(task)
    else:
        for path, speaker in files.items():
            print(f"Transcribing {path.name} ...")
            all_segments.extend(
                backend.transcribe_file(path, speaker, cfg["whisper"]["language"])
            )

    # 3. Reduce segments to output lines: either collapsed speaker turns, or
    #    one line per sentence (each keeping its own timestamp).
    sentence_mode = cfg["transcript"].get("granularity") == "sentence"
    if sentence_mode:
        from .sentences import split_into_sentences
        turns = split_into_sentences(all_segments)
    else:
        turns = merge_segments(all_segments, cfg["transcript"]["merge_gap_seconds"])
    if not turns:
        log.warning("No speech detected in any track — writing an empty transcript.")

    # 3b. If no --call-name was given, compose the title from the Zoom topic +
    # the spoken opening ("this is call 4 with Turbo Squad" -> "Turbo Squad:
    # Call 4, <topic>"; one-on-ones -> "Ludi Call Summary: <topic>"). The same
    # call also yields the structured classification stored in the manifest.
    classification: dict | None = None
    if not args.call_name and summarize_enabled and turns:
        from .summarize import extract_call_title, _client
        opening = " ".join(t["text"] for t in turns[:8])[:1500]
        try:
            composed, classification = extract_call_title(
                _client(), opening_text=opening, zoom_topic=zoom_topic,
                participants=sorted(set(files.values())),
                owner=cfg.get("owner_name", ""), model=cfg["summarize"]["model"],
            )
            if composed:
                call_name = composed
                call_slug = slugify(f"{call_date} {composed}")
                log.info("Composed call title: %s", composed)
        except Exception as e:
            log.warning("Title composition failed (%s) — using: %s", e, call_name)

    # 4. Write transcript
    participants = sorted(set(files.values()))
    content = render_transcript(
        turns,
        call_name=call_name,
        date=call_date,
        time=rec_time,
        participants=participants,
        source_files=[p.name for p in files],
        timestamps=cfg["transcript"]["timestamps"],
        speaker_labels=speaker_labels,
    )
    transcript_path = write_transcript(content, cfg["paths"]["output_dir"], call_slug)

    # 5. Optional intelligence layer
    summary_path = None
    updated_profiles: list[Path] = []
    reflections: dict[str, Path] = {}
    if summarize_enabled and turns:
        from .summarize import run_intelligence_layer
        try:
            summary_path, updated_profiles, reflections = run_intelligence_layer(
                transcript_md=content,
                call_name=call_name,
                call_slug=call_slug,
                date=call_date,
                time=rec_time,
                participants=participants,
                cfg=cfg,
            )
        except Exception as e:  # never lose the transcript over an API failure
            log.warning("Summary/profile step failed (%s). Transcript is safe at %s",
                        e, transcript_path)
    elif summarize_enabled and not turns:
        log.info("Skipping summary/profiles: no speech to summarize.")

    # 6. Optional email delivery
    emailed_to: list[str] = []
    email_enabled = args.email or cfg.get("email", {}).get("enabled", False)
    if email_enabled and summary_path:
        from .emailer import send_summary_email
        try:
            emailed_to = send_summary_email(
                cfg,
                subject=call_name,
                summary_md=summary_path.read_text(encoding="utf-8"),
                attachments=[transcript_path, summary_path],
            )
        except Exception as e:
            log.warning("Email step failed (%s). Summary is safe at %s", e, summary_path)
    elif email_enabled and not summary_path:
        log.info("Email skipped: no summary was generated.")

    # 6b. Participant emails: each matched participant gets their personal
    # reflection + the shared summary. Off by default (draft mode) — reflections
    # sit in output/<slug>/reflections/ for review until send_to_participants
    # is turned on in config.yaml.
    if email_enabled and reflections and cfg["email"].get("send_to_participants"):
        from .emailer import send_summary_email as _send, strip_facilitator_sections
        contacts = config_mod.load_contacts(cfg.get("contacts_file"))
        summary_md = summary_path.read_text(encoding="utf-8") if summary_path else ""
        # Facilitator-only sections never reach participants.
        summary_md = strip_facilitator_sections(summary_md)
        for name, rpath in reflections.items():
            addr = config_mod.match_contact(name, contacts)
            if not addr:
                log.warning("No contact email found for '%s' — reflection saved at %s "
                            "but not sent. Add them to contacts.yaml.", name, rpath)
                continue
            body = rpath.read_text(encoding="utf-8")
            if summary_md:
                body += f"\n\n---\n\n# Shared call summary — {call_name}\n\n{summary_md}"
            try:
                _send(cfg, subject=f"Your reflection — {call_name}",
                      summary_md=body, attachments=[rpath, summary_path] if summary_path else [rpath],
                      to=[addr])
                emailed_to.append(f"{name} <{addr}>")
            except Exception as e:
                log.warning("Reflection email to %s failed: %s", name, e)
    elif reflections:
        log.info("Reflections saved for review (draft mode): %s",
                 ", ".join(str(p) for p in reflections.values()))

    # 6c. Write the machine-readable manifest — the integration contract for
    # downstream tools (quote/marketing database, etc.).
    from .manifest import derive_tags, write_manifest
    tags = derive_tags([zoom_topic or "", call_name, folder_label], cfg.get("tags", {}))
    out_root = Path(cfg["paths"]["output_dir"])
    call_dir = out_root / call_slug
    manifest = {
        "schema_version": 1,
        "call_name": call_name,
        "zoom_topic": (zoom_topic or "").rstrip("_ ").strip() or None,
        "date": call_date,
        "time": rec_time,
        "duration_seconds": round(max((t["end"] for t in turns), default=0), 1),
        # Without speaker labels the only "name" available is a filename, which
        # is not a participant — downstream tools must not attribute quotes to it.
        "speaker_attributed": speaker_labels,
        "participants": participants if speaker_labels else [],
        "owner": cfg.get("owner_name", ""),
        "tags": tags,
        "classification": classification,  # {"call_type","squad_name","call_number","other_party"} or null
        "source_folder": str(source_dir.resolve()),
        "source_files": [p.name for p in files],
        "artifacts": {
            "transcript": str(transcript_path.resolve()),
            "summary": str(summary_path.resolve()) if summary_path else None,
            "reflections": {n: str(p.resolve()) for n, p in reflections.items()},
            "manifest": str((call_dir / "manifest.json").resolve()),
        },
        "profiles_updated": [str(p.resolve()) for p in updated_profiles],
        "emailed_to": emailed_to,
    }
    manifest_path = write_manifest(out_root, call_slug, data=manifest)

    # 7. Run summary
    print("\n=== Run summary ===")
    print(f"Files processed : {len(files)}")
    if speaker_labels:
        print(f"Speakers        : {', '.join(participants)}")
    print(f"{'Sentences' if sentence_mode else 'Turns':<16}: {len(turns)}")
    print(f"Transcript      : {transcript_path}")
    if summary_path:
        print(f"Summary         : {summary_path}")
    if updated_profiles:
        print(f"Profiles updated: {', '.join(str(p) for p in updated_profiles)}")
    if reflections:
        print(f"Reflections     : {', '.join(str(p) for p in reflections.values())}")
    if emailed_to:
        print(f"Emailed to      : {', '.join(emailed_to)}")
    print(f"Manifest        : {manifest_path}" + (f"  (tags: {', '.join(tags)})" if tags else ""))
    if not summarize_enabled:
        print("Summary/profiles: skipped (disabled or no API key)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
