"""Transcription backends behind one swappable seam.

The rest of the pipeline only calls :func:`get_backend`, which returns an
object with ``transcribe_file(path, speaker, language) -> list[segment]``.
Adding a new backend (e.g. mlx-whisper on Apple Silicon) means implementing
that one method and registering it in ``_BACKENDS`` — merge/render/summarize
code never changes.

Segments are dicts: {"start": float, "end": float, "speaker": str, "text": str}.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class FasterWhisperBackend:
    """Default backend: faster-whisper (CTranslate2). Runs locally on CPU with
    int8 on Apple Silicon; on an NVIDIA GPU use device="cuda", compute_type="float16".
    """

    def __init__(self, model_name: str = "large-v3", compute_type: str = "int8",
                 device: str = "cpu", min_segment_duration: float = 0.4):
        # Imported lazily so the rest of the package (tests, config) works
        # without faster-whisper installed.
        from faster_whisper import WhisperModel

        log.info("Loading Whisper model '%s' (%s/%s) — first run downloads it once...",
                 model_name, device, compute_type)
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self.min_segment_duration = min_segment_duration

    def transcribe_file(self, path: str | Path, speaker: str,
                        language: str | None = "en") -> list[dict]:
        segments, _info = self.model.transcribe(
            str(path),
            language=language,          # None = auto-detect
            vad_filter=True,            # drops silence + faint cross-track bleed
            word_timestamps=True,
        )
        out: list[dict] = []
        dropped = 0
        for s in segments:             # generator — segments stream, audio isn't held in memory
            text = s.text.strip()
            if not text:
                continue
            # Cheap extra bleed filter: very short segments with little text
            # are usually the other speaker leaking through the mic.
            if (s.end - s.start) < self.min_segment_duration and len(text) < 12:
                dropped += 1
                continue
            segment = {"start": s.start, "end": s.end, "speaker": speaker, "text": text}
            # Word timings ride along so sentence-granularity output can cut on
            # real word boundaries instead of interpolating (see sentences.py).
            words = [
                {"start": w.start, "end": w.end, "word": w.word}
                for w in (getattr(s, "words", None) or [])
                if w.start is not None and w.end is not None
            ]
            if words:
                segment["words"] = words
            out.append(segment)
        if dropped:
            log.info("Dropped %d ultra-short segment(s) from %s (likely cross-track bleed)",
                     dropped, Path(path).name)
        return out


_BACKENDS = {
    "faster-whisper": FasterWhisperBackend,
    # "mlx-whisper": MlxWhisperBackend,   # future: Apple-Silicon-native (Metal)
}


def get_backend(name: str = "faster-whisper", **kwargs):
    """Instantiate a transcription backend by name."""
    try:
        cls = _BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"Unknown transcription backend '{name}'. Available: {', '.join(_BACKENDS)}"
        ) from None
    return cls(**kwargs)
