"""Split transcript segments into one entry per sentence.

Whisper emits segments that are roughly phrase-shaped: sometimes two sentences
in one segment, sometimes half of one. When a transcript is going to be lined
up against a *separate* transcript (e.g. a speaker-attributed export from
another tool), what matters is a timestamp on every sentence — not tidy turns.

This module does that split using the word-level timings Whisper already
produces (``word_timestamps=True`` in the backend), so every sentence keeps a
real start/end taken from its first and last word, never an interpolated guess.

Pure data logic — no audio, no I/O. Segments are dicts with ``start``, ``end``,
``speaker``, ``text``, and optionally ``words``: a list of
``{"start", "end", "word"}``. A segment with no word timings passes through
whole, so a backend that can't supply them still works.
"""

from __future__ import annotations

_TERMINATORS = (".", "!", "?", "…")

# Trailing characters that can sit *after* the sentence-ending punctuation.
_CLOSERS = "\"'”’)]}»"

# Words that end in a period without ending a sentence.
_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "mt.",
    "vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.", "approx.", "no.",
}


def ends_sentence(word: str) -> bool:
    """True if ``word`` closes a sentence.

    Guards the two common false positives: abbreviations ("Dr.") and single
    initials ("J."), both of which end in a period mid-sentence.
    """
    stripped = word.strip().rstrip(_CLOSERS)
    if not stripped.endswith(_TERMINATORS):
        return False
    if stripped.casefold() in _ABBREVIATIONS:
        return False
    core = stripped.rstrip("".join(_TERMINATORS))
    if len(core) == 1 and core.isalpha() and core.isupper():
        return False  # an initial, e.g. "J." in "J. Cooper"
    return True


def _build(words: list[dict], speaker: str) -> dict | None:
    """Assemble one sentence dict from consecutive word dicts."""
    text = "".join(w["word"] for w in words).strip()
    if not text:
        return None
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "speaker": speaker,
        "text": text,
    }


def split_segment(segment: dict) -> list[dict]:
    """Split one segment into per-sentence segments.

    Returns ``[segment]`` (minus its ``words``) when there are no usable word
    timings, so callers can treat the result uniformly.
    """
    words = segment.get("words") or []
    speaker = segment.get("speaker", "")
    if not words:
        text = segment["text"].strip()
        if not text:
            return []
        return [{"start": segment["start"], "end": segment["end"],
                 "speaker": speaker, "text": text}]

    out: list[dict] = []
    current: list[dict] = []
    for word in words:
        current.append(word)
        if ends_sentence(word["word"]):
            built = _build(current, speaker)
            if built:
                out.append(built)
            current = []
    if current:  # trailing words with no terminal punctuation
        built = _build(current, speaker)
        if built:
            out.append(built)
    return out


def split_into_sentences(all_segments: list[dict]) -> list[dict]:
    """Split every segment into sentences and return them in time order.

    Sorting is by (start, end), the same ordering :func:`merge.merge_segments`
    uses, so multi-track input still interleaves correctly — this function is
    simply the non-collapsing alternative to merging.
    """
    sentences: list[dict] = []
    for segment in all_segments:
        sentences.extend(split_segment(segment))
    sentences.sort(key=lambda s: (s["start"], s["end"]))
    return sentences
