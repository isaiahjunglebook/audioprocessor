"""Optional intelligence layer: executive summary + compounding participant profiles.

This is the only part of the tool that talks to the network — it sends the
transcript text to the Anthropic API. Everything is wrapped so that an API
failure never loses work: the transcript is already on disk before this runs.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Rough character budget before we chunk-summarize instead of one-shot.
# Sonnet's context is large; ~600K chars ≈ 150K tokens leaves ample headroom.
MAX_ONESHOT_CHARS = 600_000
CHUNK_CHARS = 300_000


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def _client():
    from anthropic import Anthropic
    return Anthropic()  # reads ANTHROPIC_API_KEY from env; never hardcode the key


def _complete(client, *, system: str, user_content: str, model: str, max_tokens: int) -> str:
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("The model declined to process this content.")
    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    # Strip accidental code fences around the whole document.
    if text.startswith("```"):
        text = text.strip("`\n")
        if text.startswith("markdown"):
            text = text[len("markdown"):].lstrip("\n")
    return text


def _chunk(text: str, size: int) -> list[str]:
    """Split on turn boundaries (blank lines) into chunks of at most ~size chars."""
    chunks, current, current_len = [], [], 0
    for block in text.split("\n\n"):
        if current and current_len + len(block) > size:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(block)
        current_len += len(block) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def generate_summary(client, transcript_md: str, *, call_name: str, date: str,
                     model: str, max_tokens: int) -> str:
    """Executive summary; map-reduce over chunks if the transcript is enormous."""
    system = _load_prompt("summary")
    header = f"Call: {call_name} — {date}\n\n"

    if len(transcript_md) <= MAX_ONESHOT_CHARS:
        return _complete(client, system=system, user_content=header + transcript_md,
                         model=model, max_tokens=max_tokens)

    log.info("Transcript is very long (%d chars) — chunk-summarizing.", len(transcript_md))
    partials = []
    chunks = _chunk(transcript_md, CHUNK_CHARS)
    for i, chunk in enumerate(chunks, 1):
        partials.append(_complete(
            client, system=system,
            user_content=f"{header}(Part {i} of {len(chunks)} of a long call)\n\n{chunk}",
            model=model, max_tokens=max_tokens,
        ))
    combined = "\n\n---\n\n".join(partials)
    return _complete(
        client, system=system,
        user_content=(f"{header}The following are partial summaries of consecutive parts of "
                      f"one long call. Merge them into a single summary in the required "
                      f"format, deduplicating overlap.\n\n{combined}"),
        model=model, max_tokens=max_tokens,
    )


def update_profile(client, *, name: str, transcript_md: str, call_name: str, date: str,
                   profiles_dir: Path, model: str, max_tokens: int) -> Path:
    """Load, update via Claude, and overwrite profiles/<name>.md."""
    profiles_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "Unknown"
    path = profiles_dir / f"{safe_name}.md"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""

    system = _load_prompt("profile").replace("<Name>", name)
    user_content = (
        f"Existing profile for {name}:\n\n{existing or '(no profile yet)'}\n\n"
        f"---\nCall: {call_name}\nCall date: {date}\n---\n\n"
        f"Transcript:\n\n{transcript_md}"
    )
    updated = _complete(client, system=system, user_content=user_content,
                        model=model, max_tokens=max_tokens)
    path.write_text(updated + "\n", encoding="utf-8")
    return path


def run_intelligence_layer(*, transcript_md: str, call_name: str, call_slug: str,
                           date: str, participants: list[str], cfg: dict
                           ) -> tuple[Path | None, list[Path]]:
    """Write output/<slug>/summary.md and update profiles for non-owner participants.

    Failures are logged and never abort the run — the transcript is already saved.
    Returns (summary_path or None, [updated profile paths]).
    """
    model = cfg["summarize"]["model"]
    max_tokens = cfg["summarize"]["max_tokens"]
    owner = cfg.get("owner_name", "").strip().casefold()
    client = _client()

    summary_path: Path | None = None
    try:
        summary = generate_summary(client, transcript_md, call_name=call_name,
                                   date=date, model=model, max_tokens=max_tokens)
        summary_path = Path(cfg["paths"]["output_dir"]) / call_slug / "summary.md"
        summary_path.write_text(summary + "\n", encoding="utf-8")
        log.info("Wrote summary to %s", summary_path)
    except Exception as e:
        log.warning("Summary generation failed: %s", e)

    updated: list[Path] = []
    profiles_dir = Path(cfg["paths"]["profiles_dir"])
    for name in participants:
        if owner and owner in name.strip().casefold():
            log.info("Skipping profile for owner: %s", name)
            continue
        try:
            path = update_profile(client, name=name, transcript_md=transcript_md,
                                  call_name=call_name, date=date,
                                  profiles_dir=profiles_dir, model=model,
                                  max_tokens=max_tokens)
            updated.append(path)
            log.info("Updated profile: %s", path)
        except Exception as e:
            log.warning("Profile update for %s failed: %s", name, e)
    return summary_path, updated
