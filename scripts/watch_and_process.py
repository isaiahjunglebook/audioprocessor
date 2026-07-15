"""Automatic processor: scan ~/Documents/Zoom for new recordings and process them.

Run by a launchd agent whenever the Zoom folder changes (plus a periodic sweep).
Design constraints this handles:

- Zoom writes files progressively and "converts" after the call ends, so a
  recording is only processed once its files have been stable for a while.
- Each meeting folder gets a marker file after successful processing, so
  nothing is ever processed twice.
- Existing recordings are grandfathered at install time (--mark-existing),
  so turning on automation doesn't churn through your whole back catalog.
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

ZOOM_ROOT = Path.home() / "Documents" / "Zoom"
MARKER = ".call_processed"
STABLE_SECONDS = 90   # newest file must be this old — i.e. Zoom finished writing


def _log(msg: str) -> None:
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def _newest_mtime(folder: Path) -> float:
    mtimes = [p.stat().st_mtime for p in folder.rglob("*") if p.is_file()]
    return max(mtimes, default=folder.stat().st_mtime)


def _candidates() -> list[Path]:
    """Meeting folders that have an Audio Record dir and no processed marker."""
    if not ZOOM_ROOT.is_dir():
        return []
    return sorted(
        p for p in ZOOM_ROOT.iterdir()
        if p.is_dir() and (p / "Audio Record").is_dir() and not (p / MARKER).exists()
    )


def mark_existing() -> None:
    for meeting in _candidates():
        (meeting / MARKER).write_text("grandfathered at automation install\n")
        _log(f"Marked existing recording as processed: {meeting.name}")


def process_new() -> int:
    import os
    os.chdir(REPO_ROOT)  # output/, profiles/, config.yaml, .env all live here
    failures = 0
    for meeting in _candidates():
        age = time.time() - _newest_mtime(meeting)
        if age < STABLE_SECONDS:
            _log(f"Skipping (still being written, {int(age)}s old): {meeting.name}")
            continue
        _log(f"Processing: {meeting.name}")
        from call_processor.main import main as run_main
        rc = run_main(["--input", str(meeting / "Audio Record")])
        if rc == 0:
            (meeting / MARKER).write_text(
                f"processed {datetime.datetime.now().isoformat(timespec='seconds')}\n"
            )
            _log(f"Done: {meeting.name}")
        else:
            failures += 1
            _log(f"FAILED (exit {rc}) — will retry on next run: {meeting.name}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark-existing", action="store_true",
                        help="Mark all current recordings as already processed")
    args = parser.parse_args()
    if args.mark_existing:
        mark_existing()
        return 0
    return process_new()


if __name__ == "__main__":
    sys.exit(main())
