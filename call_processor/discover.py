"""File discovery and speaker-name resolution.

Each audio file in the input folder is one participant's isolated track, so
speaker attribution is a filename lookup. This module finds the usable tracks,
skips the combined/mixed file Zoom sometimes also writes, and resolves a
display name for each track.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

AUDIO_EXTS = {".m4a", ".wav", ".mp3", ".flac", ".aac"}

# Zoom artifacts commonly found in per-participant filenames.
_LEADING_AUDIO_PREFIX = re.compile(r"^audio\d*[_-]", re.IGNORECASE)
_TRAILING_DIGITS = re.compile(r"[_-]\d+$")
_GUID = re.compile(
    r"[_-]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
# Names that indicate the combined "everyone" file, not a per-participant track.
_COMBINED_HINT = re.compile(r"(audio[_-]?only|combined|mixed|^recording$)", re.IGNORECASE)


def derive_speaker_name(stem: str) -> str | None:
    """Derive a human display name from a filename stem, or None if hopeless."""
    name = _GUID.sub("", stem)
    name = _LEADING_AUDIO_PREFIX.sub("", name)
    # Zoom's local-recording style has no separators: "audioIsaiahEnglish11900040134".
    name = re.sub(r"^audio(?=[A-Z0-9])", "", name)
    if re.fullmatch(r"(audio)?\d*", name, re.IGNORECASE):
        return None  # nothing left but the Zoom "audioNNNN" artifact
    # Strip trailing numeric suffixes repeatedly (e.g. "jane_cooper_2_1").
    while True:
        stripped = _TRAILING_DIGITS.sub("", name)
        if stripped == name:
            break
        name = stripped
    name = re.sub(r"\d+$", "", name)  # bare trailing meeting id, no separator
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)  # split camelCase
    name = re.sub(r"[_-]+", " ", name).strip()
    if not name or not re.search(r"[A-Za-z]", name):
        return None
    return " ".join(w if w.isupper() else w.capitalize() for w in name.split())


def _looks_combined(stem: str) -> bool:
    return bool(_COMBINED_HINT.search(stem))


def discover_files(input_dir: str | Path, overrides: dict[str, str] | None = None) -> dict[Path, str]:
    """Return {audio_path: speaker_name} for the usable per-participant tracks.

    ``overrides`` maps filename stems to display names and always wins.
    Raises FileNotFoundError / ValueError with a clear message on bad input.
    """
    overrides = overrides or {}
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input folder not found: {input_dir}")

    candidates = sorted(
        p for p in input_dir.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in AUDIO_EXTS
    )
    if not candidates:
        raise ValueError(
            f"No audio files ({', '.join(sorted(AUDIO_EXTS))}) found in {input_dir}. "
            "Point --input at the folder containing the per-participant tracks "
            "(e.g. Zoom's 'Audio Record' folder)."
        )

    # Skip the combined/mixed file by name hint — but only when other tracks
    # remain, so a folder holding just one oddly-named file still works.
    named_combined = [p for p in candidates if _looks_combined(p.stem) and p.stem not in overrides]
    kept = [p for p in candidates if p not in named_combined]
    if named_combined and kept:
        for p in named_combined:
            log.warning(
                "Skipping '%s' — looks like the combined/mixed recording, not a "
                "per-participant track. If it IS a participant, add an override: "
                "--map \"%s=Their Name\"", p.name, p.stem,
            )
    else:
        kept = candidates  # nothing else left; keep everything

    # Secondary heuristic: if every remaining file except one maps to a distinct
    # clean speaker name and the odd one out is also the largest file, it's
    # probably the combined recording.
    if len(kept) >= 3:
        unnamed = [p for p in kept if p.stem not in overrides and derive_speaker_name(p.stem) is None]
        if len(unnamed) == 1:
            largest = max(kept, key=lambda p: p.stat().st_size)
            if unnamed[0] == largest:
                log.warning(
                    "Skipping '%s' — largest file and no participant name could be "
                    "derived, so it's probably the combined recording. Override with "
                    "--map \"%s=Their Name\" if wrong.", largest.name, largest.stem,
                )
                kept = [p for p in kept if p != largest]

    if len(kept) == 1:
        log.warning(
            "Only one usable track found (%s) — proceeding with a "
            "single-speaker transcript.", kept[0].name,
        )

    mapping: dict[Path, str] = {}
    for p in kept:
        if p.stem in overrides:
            mapping[p] = overrides[p.stem]
            continue
        derived = derive_speaker_name(p.stem)
        if derived is None:
            log.warning(
                "Couldn't derive a clean speaker name from '%s'; using the raw "
                "stem. Add an override: --map \"%s=Their Name\"", p.name, p.stem,
            )
            derived = p.stem
        mapping[p] = derived
    return mapping
