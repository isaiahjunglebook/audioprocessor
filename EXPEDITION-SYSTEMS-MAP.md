# The Expedition — Systems Map (for a downstream repo)

> **Read me first.** This document explains the two upstream systems that feed
> whatever you (the repo this file is dropped into) are building: (1) the
> **audio processor** — turns Zoom calls into verbatim transcripts, and (2)
> **Their Words** — harvests verbatim quotes from those transcripts into an
> anonymized canon. It describes what each is, where its files live on the Mac,
> how data flows between them, and — most importantly — the **privacy boundary**
> a downstream consumer must respect.
>
> **Authority note:** the audio-processor section is exact (it is documented
> from the running code). The Their Words section is written from its **build
> spec**; if that project's actual repo differs, the repo's own code/docs win.

---

## 0. The one-paragraph mental model

A Zoom cohort call is recorded with one clean audio track per person. The
**audio processor** transcribes each track locally and merges them into one
verbatim, speaker-labeled transcript, plus a summary, per-person profiles, and a
machine-readable `manifest.json`. **Their Words** watches that output, extracts
the men's best verbatim lines, and — only after Isaiah approves each one —
appends them to an **anonymized canon** (initials only) that is the sourcing
corpus for session themes, marketing copy, and the book. Raw transcripts never
leave the Mac; only the anonymized canon is ever published. **A downstream repo
should source from the anonymized canon, never from raw transcripts.**

```
Zoom call (separate audio per person)
   │
   ▼
[SYSTEM 1: audio processor]  ~/Documents/audioprocessor
   produces per-call:  transcript.md · summary.md · manifest.json · reflections/
   + updates:          profiles/<Name>.md
   │   (verbatim transcript + manifest)
   ▼
[SYSTEM 2: Their Words]  (separate private repo)
   ingest → candidates/ → Isaiah approves each → append to CANON
   produces:  their-words.md + their-words.json (anonymized, initials only)
   + private viewer on Vercel
   │   (anonymized canon only)
   ▼
[DOWNSTREAM: book / marketing / this repo]
   sources verbatim quotes from the canon (their-words.json)
```

---

## 1. SYSTEM 1 — the audio processor

### What it is
A local command-line tool (`call_processor`) on Isaiah's Mac. For each recorded
Zoom call it: reads the per-participant audio tracks Zoom writes → transcribes
each locally with Whisper (large-v3) → merges by timestamp into one
speaker-labeled transcript → generates a summary + per-participant profiles +
composes a clean title (via the Anthropic API) → emails the summary → writes a
machine-readable `manifest.json`. A launchd watcher makes it hands-free.

### Where it lives
| Thing | Location |
|---|---|
| Code | `~/Documents/audioprocessor/` |
| Runtime | local only; Python venv at `~/Documents/audioprocessor/.venv` |
| Git mirror (private) | `github.com/isaiahjunglebook/audioprocessor` |
| **Call outputs** | `~/Documents/audioprocessor/output/<slug>/` |
| Profiles | `~/Documents/audioprocessor/profiles/<Name>.md` |
| Zoom source audio | `~/Documents/Zoom/<date time topic>/Audio Record/` |

No server, no web host. Only network egress is the Anthropic API call
(transcript text → summary). Raw audio and transcripts never leave the machine
otherwise.

### What each call produces
```
~/Documents/audioprocessor/output/2026-08-01-turbo-squad-call-4-act-i/
    transcript.md   ← VERBATIM speaker-labeled transcript (the quote source)
    summary.md      ← summary; CONTAINS FACILITATOR-PRIVATE data — not for quoting
    manifest.json   ← machine-readable index (trigger + metadata)
    reflections/    ← per-man interpretive notes — not verbatim, not for quoting
```

### The trigger rule (critical for any consumer)
Artifacts are written over minutes; **`manifest.json` is written LAST and
ATOMICALLY** (temp file + rename). A complete `manifest.json` in a call folder
is the one reliable "this call is fully processed" signal. **Trigger on
`manifest.json` — never on `transcript.md`.**

### manifest.json schema (v1)
```json
{
  "schema_version": 1,
  "call_name": "Turbo Squad: Call 4, Act I",
  "date": "2026-08-01",
  "time": "19:00",
  "participants": ["Isaiah English", "Adam Sample", "Scott Sample"],
  "owner": "Isaiah",
  "tags": ["squad", "expedition"],
  "classification": {"call_type": "squad", "squad_name": "Turbo Squad",
                     "call_number": 4, "other_party": null},
  "artifacts": {
    "transcript": "/Users/isaiahenglish/Documents/audioprocessor/output/<slug>/transcript.md",
    "summary": "…", "reflections": {"Adam Sample": "…"}, "manifest": "…"
  }
}
```
- `tags` are **call-level selectors** (config keywords: `squad`, `expedition`).
- `classification` gives the per-quote context (Intro call / Squad call 4 / 1:1).
- `participants` are full display names; `owner` (Isaiah) is on every call.

### transcript.md format (verbatim source)
```markdown
# Turbo Squad: Call 4, Act I
- **Date:** 2026-08-01 · 19:00
- **Participants:** Isaiah English, Adam Sample, Scott Sample
---
**[00:14:22] Adam Sample:** I keep telling myself I'll be more present when
work slows down. It never slows down.
```
One turn per paragraph: `**[HH:MM:SS] Full Name:** verbatim text`. Timestamps
are seconds from call start on one shared timeline — `slug + timestamp` is a
durable pointer to the exact line.

### Known limitation
This works **only** for calls with separate audio tracks per person (Zoom local
recording). A single mixed recording (e.g. a phone call taped on Voice Memos)
cannot be reliably split by speaker — do not feed those in expecting clean
attribution.

---

## 2. SYSTEM 2 — Their Words (verbatim quote canon)

> Described from the build spec (`THEIR-WORDS-BUILDSPEC.md`). The actual repo is
> authoritative where it differs.

### What it is
A separate private repo + local pipeline that reads the audio processor's output
and harvests **verbatim quotes** from the men into an append-only, anonymized
canon — with Isaiah approving every single entry. It is the raw-material corpus
for session themes, marketing, sales pages, and the book. Verbatim only; no
paraphrase anywhere.

### What it produces (its committed, shareable output)
| File | Meaning |
|---|---|
| `their-words.md` | THE CANON — anonymized (initials only), human-readable |
| `their-words.json` | machine mirror of the canon (what the viewer and any downstream tool reads) |
| `tags.md` | the quote-level tag registry (`the-lie`, `deferral`, `father`, …) |
| `TAXONOMY-CHANGELOG.md` | dated log of tag changes |

### What it keeps local-only (gitignored, never pushed)
`roster.yaml` (full name → initials — the de-anonymization key), `candidates/`
(pre-approval material), `state/` (ingested slugs), `transcripts/` (any local
copies), `.env`.

### Entry shape (per quote)
`id` (TW-0001…) · `date` · `man` (initials) · `context` (from the manifest
classification) · `quote` (verbatim, with surrounding context + `slug`+timestamp
provenance) · `tags` (quote-level, from its own registry).

### The viewer
A private, read-only web page on **Vercel** that renders `their-words.json` as
filterable cards (by tag, by man, full-text search, copy buttons, stat counts).
Auto-redeploys on every push. Behind **Vercel Deployment Protection** (platform
auth, not hand-rolled). It reads the anonymized canon only — no write path, no
transcript access.

### Two tag systems — do not conflate
- **Audio-processor `manifest.tags`** = call-level selectors ("is this an
  Expedition call?"). Used to decide which calls to ingest.
- **Their Words `tags`** = quote-level semantic tags applied during review.
  These live only in Their Words.

---

## 3. How a downstream repo should plug in

**The golden rule: source from the anonymized canon, not from raw transcripts.**

| If your repo needs… | Read from | Never read |
|---|---|---|
| Verbatim quotes for copy/book | Their Words' `their-words.json` (canon) | audio processor `transcript.md` directly |
| Which quotes exist / counts / tags | `their-words.json` | — |
| Call-level metadata (dates, participants) | audio processor `manifest.json` (read-only) | its `.env`, `contacts.yaml` |

Why: the canon is the only surface that is anonymized (initials only) and
human-approved. Raw transcripts contain full names and un-vetted material and
are gitignored for exactly this reason. A book/marketing tool that reads raw
transcripts would bypass both the anonymization and Isaiah's approval gate.

### Hard boundaries (non-negotiable, inherited from both systems)
1. **One-way data flow.** audio processor → Their Words → downstream. No
   downstream repo writes back into `~/Documents/audioprocessor/` or Their
   Words' canon.
2. **Raw transcripts, audio, roster, and candidates never leave the Mac** —
   never committed, never pushed, never uploaded, never emailed.
3. **The canon is initials-only.** Any external output (marketing, site, book)
   strips identifying detail. Named attribution only with that man's explicit
   recorded permission.
4. **`summary.md`, `reflections/`, and `profiles/` are interpretive or
   facilitator-private** (the summary now contains a private "Facilitator
   signal" behavioral section). They are **not** verbatim quote sources — never
   ingest them as quotes.
5. The men are told on intro calls: recorded to build from, anonymized outside
   the squad, named only with permission.

---

## 4. Quick file-location cheat sheet

| System | Read | Absolute location |
|---|---|---|
| Audio processor | call outputs | `~/Documents/audioprocessor/output/<slug>/` |
| Audio processor | trigger/metadata | `…/output/<slug>/manifest.json` |
| Audio processor | verbatim transcript | path inside `manifest.artifacts.transcript` |
| Their Words | anonymized canon | `<their-words-repo>/their-words.json` |
| Their Words | tag registry | `<their-words-repo>/tags.md` |

If anything here is insufficient, the fuller sources are the audio processor's
`SYSTEM.md` and Their Words' own `THEIR-WORDS-BUILDSPEC.md` + repo.
