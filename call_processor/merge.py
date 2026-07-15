"""Merge per-track transcript segments into one chronological conversation.

Pure data logic — no audio, no I/O. Segments are dicts with ``start``, ``end``,
``speaker``, and ``text`` keys.
"""

from __future__ import annotations

DEFAULT_MERGE_GAP_SECONDS = 1.5


def merge_segments(all_segments: list[dict], merge_gap_seconds: float = DEFAULT_MERGE_GAP_SECONDS) -> list[dict]:
    """Sort segments from every track by start time and collapse consecutive
    same-speaker segments into single turns.

    A same-speaker segment extends the current turn when the gap since the
    turn's end is under ``merge_gap_seconds`` — and also when segments simply
    run back-to-back or overlap (gap <= 0), which is the common case for
    consecutive breaths within one utterance.
    """
    segments = sorted(all_segments, key=lambda s: (s["start"], s["end"]))
    turns: list[dict] = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        if turns and turns[-1]["speaker"] == seg["speaker"]:
            gap = seg["start"] - turns[-1]["end"]
            if gap < merge_gap_seconds:
                turns[-1]["text"] += " " + text
                turns[-1]["end"] = max(turns[-1]["end"], seg["end"])
                continue
        turns.append({
            "start": seg["start"],
            "end": seg["end"],
            "speaker": seg["speaker"],
            "text": text,
        })
    return turns
