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
                   help="Folder of per-participant audio files (e.g. Zoom's 'Audio Record')")
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
    overrides = {**cfg.get("speakers", {}), **config_mod.parse_speaker_map(args.speaker_map)}

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
        log.error("Pass --input <folder> or --latest.")
        return 1
    # Zoom's audio lives in "<meeting name>/Audio Record" — use the meeting name.
    folder_label = input_dir.parent.name if input_dir.name == "Audio Record" else input_dir.name
    call_name = args.call_name or f"{folder_label} — {today}"
    call_slug = slugify(call_name)

    # 1. Discover + resolve speakers
    try:
        files = discover_files(input_dir, overrides)
    except (FileNotFoundError, ValueError) as e:
        log.error("%s", e)
        return 1

    print("Speaker mapping:")
    for path, speaker in files.items():
        print(f"  {path.name}  ->  {speaker}")

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

    # 3. Merge by timestamp into speaker turns
    turns = merge_segments(all_segments, cfg["transcript"]["merge_gap_seconds"])
    if not turns:
        log.warning("No speech detected in any track — writing an empty transcript.")

    # 3b. If no --call-name was given, try the spoken title from the call's opening
    # ("August 1st 2026, Squad 1, Call 1" said into the mic becomes the file name).
    if not args.call_name and summarize_enabled and turns:
        from .summarize import extract_call_title, _client
        opening = " ".join(t["text"] for t in turns[:8])[:1500]
        try:
            spoken = extract_call_title(_client(), opening, model=cfg["summarize"]["model"])
            if spoken:
                call_name, call_slug = spoken, slugify(spoken)
                log.info("Using spoken call title: %s", spoken)
        except Exception as e:
            log.debug("Spoken-title extraction skipped: %s", e)

    # 4. Write transcript
    participants = sorted(set(files.values()))
    content = render_transcript(
        turns,
        call_name=call_name,
        date=today,
        participants=participants,
        source_files=[p.name for p in files],
        timestamps=cfg["transcript"]["timestamps"],
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
                date=today,
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
                subject=f"Call summary — {call_name}",
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
        from .emailer import send_summary_email as _send
        contacts = config_mod.load_contacts(cfg.get("contacts_file"))
        summary_md = summary_path.read_text(encoding="utf-8") if summary_path else ""
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

    # 7. Run summary
    print("\n=== Run summary ===")
    print(f"Files processed : {len(files)}")
    print(f"Speakers        : {', '.join(participants)}")
    print(f"Turns           : {len(turns)}")
    print(f"Transcript      : {transcript_path}")
    if summary_path:
        print(f"Summary         : {summary_path}")
    if updated_profiles:
        print(f"Profiles updated: {', '.join(str(p) for p in updated_profiles)}")
    if reflections:
        print(f"Reflections     : {', '.join(str(p) for p in reflections.values())}")
    if emailed_to:
        print(f"Emailed to      : {', '.join(emailed_to)}")
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
