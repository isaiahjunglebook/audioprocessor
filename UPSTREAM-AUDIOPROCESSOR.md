# Upstream system reference — the "audioprocessor" call pipeline

> **Purpose of this file.** This document describes the audio/transcription
> system that feeds THIS project ("Their Words"). It is the integration
> reference: what the upstream system is, where it lives on the machine, what it
> produces, in what format, and the exact contract Their Words builds against.
> Commit this file into the Their Words repo. When in doubt, the upstream repo's
> own `SYSTEM.md` is the fuller source of truth.
>
> **One-line summary:** a local Mac pipeline turns per-participant Zoom audio
> into verbatim, speaker-labeled transcripts (plus summaries/profiles). Their
> Words consumes those transcripts to harvest verbatim quotes. Data flows one
> way: audioprocessor **produces**, Their Words **consumes**. Their Words never
> writes into the audioprocessor folders.

---

## 1. What the upstream system is

A command-line tool ("audioprocessor" / package `call_processor`) that runs
fully locally on Isaiah's Mac. For every recorded Zoom call it:

1. Reads the **per-participant audio tracks** Zoom writes (one clean file per
   speaker — no diarization guesswork; every word in a track is that speaker).
2. Transcribes each track locally with Whisper (large-v3), on-device, private.
3. Merges the tracks by timestamp into one speaker-labeled transcript.
4. Generates an executive summary + per-participant relationship profiles, and
   composes a clean call title — via the Anthropic API.
5. Emails the summary; optionally emails participants their own reflection.
6. Writes a machine-readable `manifest.json` — **the integration contract.**

A background launchd watcher makes it hands-free: call ends → files land →
processing runs → email arrives. No manual step required.

---

## 2. How it's hosted / where it lives

| Thing | Location |
|---|---|
| Upstream project code | `~/Documents/audioprocessor/` |
| Runtime | Local only — Python venv at `~/Documents/audioprocessor/.venv` |
| Invoked as | `~/Documents/audioprocessor/.venv/bin/python -m call_processor.main` (alias `processcall`) |
| Git mirror (private) | `github.com/isaiahjunglebook/audioprocessor` |
| **Call outputs (READ THESE)** | `~/Documents/audioprocessor/output/<slug>/` |
| Participant profiles | `~/Documents/audioprocessor/profiles/<Name>.md` |
| Zoom source recordings | `~/Documents/Zoom/<date time topic>/Audio Record/` |
| Automation | launchd agent `com.callprocessor.watcher`; logs in `~/Documents/audioprocessor/logs/watcher.log` |

There is **no server and no web host** — it is a local process on one Mac. The
only network egress is the Anthropic API call (transcript text → summary). Raw
audio and raw transcripts never leave the machine except through that API call.

---

## 3. What each processed call produces

```
~/Documents/audioprocessor/output/2026-08-01-turbo-squad-call-4-act-i/
    transcript.md      ← VERBATIM speaker-labeled transcript  (Their Words' quote source)
    summary.md         ← executive summary — CONTAINS FACILITATOR-PRIVATE DATA (do NOT ingest)
    manifest.json      ← machine-readable index — the trigger + metadata (READ THIS)
    reflections/       ← per-man interpretive reflections (do NOT ingest as quotes)
      Adam.md
~/Documents/audioprocessor/profiles/
    Adam.md            ← evolving dossier, updated in place each call (interpretive, not verbatim)
```

**What Their Words should read:** `manifest.json` (to trigger + get metadata)
and `transcript.md` (the verbatim source). **What Their Words must NOT ingest as
quotes:** `summary.md` (AI-written, and now contains a private "Facilitator
signal" behavioral-read section), `reflections/`, and `profiles/` (all
interpretive, not the men's verbatim words).

---

## 4. THE TRIGGER RULE (critical)

Artifacts are written over a span of minutes — transcript first, then summary a
minute later after API calls, and **`manifest.json` is written LAST and
ATOMICALLY** (temp file + rename).

> **A complete `manifest.json` appearing in a call folder is the one and only
> reliable "this call is fully processed" signal. Their Words triggers on
> manifest.json — never on transcript.md** (which appears before the call is
> fully done and could be read half-processed).

Since manifests are never mutated after a run, Their Words keeps a set of
already-ingested slugs (its own gitignored `state/`) and only processes new
folders. The `output/` directory is effectively the queue.

---

## 5. `manifest.json` schema (v1) — the contract

```json
{
  "schema_version": 1,
  "call_name": "Turbo Squad: Call 4, Act I",
  "zoom_topic": "Act I",
  "date": "2026-08-01",
  "time": "19:00",
  "duration_seconds": 5520.0,
  "participants": ["Isaiah English", "Adam Sample", "Scott Sample"],
  "owner": "Isaiah",
  "tags": ["squad", "expedition"],
  "classification": {
    "call_type": "squad",            // "squad" | "one_on_one" | "other" | null
    "squad_name": "Turbo Squad",
    "call_number": 4,
    "other_party": null              // set for one_on_one calls
  },
  "source_folder": "…absolute…/Audio Record",
  "source_files": ["audioIsaiahEnglish….m4a", "audioADAM….m4a"],
  "artifacts": {
    "transcript": "/Users/isaiahenglish/Documents/audioprocessor/output/<slug>/transcript.md",
    "summary":    "…/summary.md",
    "reflections": {"Adam Sample": "…/reflections/Adam Sample.md"},
    "manifest":   "…/manifest.json"
  },
  "profiles_updated": ["…/profiles/Adam Sample.md"],
  "emailed_to": ["mgmt.junglebook@gmail.com"]
}
```

Field notes for Their Words:
- **`tags`** are **call-level selectors** (config-driven keyword rules in the
  upstream `config.yaml`: `squad`, `expedition`, …). Use them to decide *which
  calls to ingest*. These are NOT the same as Their Words' quote-level semantic
  tags (`the-lie`, `deferral`, …) — those belong to Their Words alone.
- **`classification`** gives the per-quote `context` value (Intro call /
  Squad call 4 / 1:1). May be `null` (manual runs, API failure) — fall back to
  `call_name` + `tags`.
- **`participants`** are full display names. Their Words keeps its own
  gitignored roster mapping full name → canonical initials, and derives `man`
  from that. **`owner` (Isaiah) is a participant on every call — exclude his
  turns from the men's quote corpus** (or tag separately as
  `founder-story-resonance`).
- All paths are **absolute** — read the transcript in place; don't copy it into
  a pushed folder.

---

## 6. `transcript.md` format (the verbatim quote source)

```markdown
# Turbo Squad: Call 4, Act I

- **Date:** 2026-08-01 · 19:00
- **Participants:** Isaiah English, Adam Sample, Scott Sample
- **Duration:** 00:50:13
- **Source files:** audioIsaiahEnglish….m4a, audioADAM….m4a

---

**[00:14:22] Adam Sample:** I keep telling myself I'll be more present when work
slows down. It never slows down.

**[00:14:41] Isaiah English:** Say more about "it never slows down."
```

- One turn per blank-line-separated paragraph:
  `**[HH:MM:SS] Full Name:** verbatim text`.
- Text is **verbatim** from Whisper — this is exactly what Their Words pulls
  quotes from. No cleanup was applied.
- Timestamps are seconds from call start on one shared timeline. Store
  **`slug + timestamp`** with each quote — a durable pointer back to the exact
  transcript line and the moment in the source audio.
- Speaker names match `manifest.participants` and are the keys for the roster.

---

## 7. Hard boundary (ownership)

- Their Words **reads** `output/*/manifest.json` and the transcript paths inside
  them. It **never** writes anything into `~/Documents/audioprocessor/`.
- Their Words **never** reads the upstream project's `.env`,
  `contacts.yaml`, `profiles/`, `summary.md`, or `reflections/` for quote
  material — those are secrets or interpretive/private content.
- One-way flow: audioprocessor produces → Their Words consumes. Neither project
  writes into the other's folders.

---

## 8. Privacy facts inherited from upstream

- Raw transcripts and raw audio live on the Mac only; they are gitignored in the
  upstream repo and never pushed. Their Words must uphold the same: raw
  transcripts, roster, and pre-approval candidates never leave the machine.
- The men are told on intro calls: recorded to build from, anonymized outside
  the squad, named only with explicit permission.
- The upstream `summary.md` now contains a facilitator-private "Facilitator
  signal" behavioral section; it is stripped from any participant-bound email.
  Their Words has no reason to touch `summary.md` at all — read only
  `transcript.md`.

---

## 9. Quick reference — commands (upstream, for context)

| Task | Command (run in `~/Documents/audioprocessor`) |
|---|---|
| Process newest call manually | `processcall` |
| Process a specific folder | `python -m call_processor.main --input "<path>/Audio Record"` |
| Watch automation live | `tail -f logs/watcher.log` |
| Latest upstream code | `git pull` |

Their Words does not run any of these — they're listed so you understand how
the folders you're reading get populated.
