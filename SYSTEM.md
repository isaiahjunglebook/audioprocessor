# The Expedition — Call Processing System (handoff & integration doc)

> **Purpose of this document.** This is the authoritative description of the
> call-transcription system, written so that a *separate* downstream project
> (the quote / marketing / book database, referred to here as "the DB tool")
> knows exactly what this system produces, where every file lands, and how to
> read it reliably. If you are an AI or developer building the DB tool, **read
> this file first** — the §"Integration contract" section is what you build
> against. Do not parse folder names or Markdown; read `manifest.json`.

---

## 1. What this system is (in one paragraph)

A local, macOS command-line tool that turns a folder of **per-participant Zoom
audio tracks** (one clean audio file per speaker) into a **speaker-labeled
merged transcript**, an **executive summary**, per-participant **relationship
profiles that compound over time**, and — for cohort calls — optional
**personalized reflections**. It runs fully on the user's Mac (transcription is
local via OpenAI's Whisper model; $0 per call, private). The only network call
is sending the transcript text to the Anthropic API to generate the summary,
profiles, reflections, and the composed title. A background watcher makes the
whole thing hands-free: finish a Zoom call → files appear → the system
processes them → an email arrives.

**Core design principle:** each participant is recorded to their own file, so
"who said what" is a filename lookup, not AI guesswork (no diarization). Every
word in `audioLudiSmith….m4a` is Ludi, with certainty.

---

## 2. Where it lives

| Thing | Location |
|---|---|
| The project code | `~/Documents/audioprocessor/` |
| Git remote | `github.com/isaiahjunglebook/audioprocessor`, branch `claude/new-session-cl7bxm` |
| Python environment | `~/Documents/audioprocessor/.venv/` |
| Config | `~/Documents/audioprocessor/config.yaml` |
| Secrets | `~/Documents/audioprocessor/.env` (API key, Gmail app password — never committed) |
| Private contacts | `~/Documents/audioprocessor/contacts.yaml` (never committed) |
| **Generated outputs** | `~/Documents/audioprocessor/output/` ← the DB tool reads here |
| **Participant profiles** | `~/Documents/audioprocessor/profiles/` ← compounding dossiers |
| Prompts (editable) | `~/Documents/audioprocessor/prompts/` |
| Automation logs | `~/Documents/audioprocessor/logs/watcher.log` |
| The Zoom source recordings | `~/Documents/Zoom/<date time topic>/Audio Record/` |

---

## 3. The end-to-end flow

```
Zoom call ends
   │  Zoom writes ~/Documents/Zoom/2026-08-01 19.00.00 Where we dropping_/
   │     ├── Audio Record/audioIsaiahEnglish….m4a   (per-participant tracks)
   │     ├── Audio Record/audioLudiSmith….m4a
   │     ├── audio1900….m4a   (combined mix — IGNORED)
   │     └── video….mp4       (IGNORED)
   ▼
launchd watcher notices the new folder, waits ~90s for files to stop changing
   ▼
call_processor runs:
   1. discover  → find per-participant tracks, resolve speaker names
   2. transcribe → Whisper (local) turns each track into timestamped segments
   3. merge     → sort all segments by time, collapse same-speaker runs to turns
   4. render    → write transcript.md
   5. summarize → Claude writes summary.md, updates profiles, (opt.) reflections,
                  and composes the clean call title
   6. email     → send the summary to the owner (and, if enabled, participants)
   7. manifest  → write manifest.json (the machine-readable index)
   ▼
output/<slug>/  now contains transcript.md, summary.md, manifest.json,
                and (for cohorts) reflections/<Name>.md
```

---

## 4. How calls are named

Zoom names its recording folder `YYYY-MM-DD HH.MM.SS <meeting topic>`. The
system parses that into date, time, and topic, then composes a human title from
the topic + who's on the call + what the owner announces in the first ~30
seconds. Rules (defined in `prompts/title.md`, tunable):

| Call type | Owner announces… | Composed title |
|---|---|---|
| Squad / cohort | "this is call 4 with Turbo Squad" (topic = "Act I") | `Turbo Squad: Call 4, Act I` |
| One-on-one | "this call is with Ludi…" (topic = "Where we dropping?") | `Ludi Call Summary: Where we dropping?` |
| Anything else | (nothing) | `Call Summary: <topic>` |

This composed title is the **email subject** and the **`call_name`** in the
manifest. The **folder slug** is always date-prefixed
(`2026-08-01-ludi-call-summary-where-we-dropping`) so `output/` sorts
chronologically in Finder.

---

## 5. Output layout (one folder per call)

```
output/
  2026-08-01-ludi-call-summary-where-we-dropping/
    transcript.md      ← full speaker-labeled transcript (see §6)
    summary.md         ← executive summary (headline + date/time + sections)
    manifest.json      ← MACHINE-READABLE INDEX — read this (see §7)
    reflections/       ← only for cohort calls with reflections enabled
      Ludi Smith.md
profiles/
  Ludi Smith.md        ← updated in place after every call this person is on
```

Re-running a call overwrites that call's transcript/summary/manifest cleanly.
Profiles are updated (the "## Call log" section appends), not overwritten.

---

## 6. transcript.md format

```markdown
# Ludi Call Summary: Where we dropping?

- **Date:** 2026-08-01 · 19:00
- **Participants:** Isaiah English, Ludi Smith
- **Duration:** 00:47:12
- **Source files:** audioIsaiahEnglish….m4a, audioLudiSmith….m4a

---

**[00:00:04] Isaiah English:** Hey Ludi, thanks for hopping on…

**[00:00:11] Ludi Smith:** Really well actually — we hit about eighty percent…
```

- One turn per blank-line-separated paragraph.
- Each turn: `**[HH:MM:SS] <Speaker Name>:** <verbatim text>`.
- Text is verbatim from Whisper (this is what the DB tool pulls quotes from).
- Timestamps are seconds from the start of the call (shared timeline across all
  tracks, since all tracks start at t=0).

---

## 7. Integration contract — `manifest.json`

**This is the file the DB tool should read.** One per call, at
`output/<slug>/manifest.json`. Stable schema (`schema_version` will bump if the
shape ever changes). Example:

```json
{
  "schema_version": 1,
  "call_name": "Ludi Call Summary: Where we dropping?",
  "zoom_topic": "Where we dropping",
  "date": "2026-08-01",
  "time": "19:00",
  "duration_seconds": 2832.0,
  "participants": ["Isaiah English", "Ludi Smith"],
  "owner": "Isaiah",
  "tags": ["expedition"],
  "source_folder": "/Users/isaiahenglish/Documents/Zoom/2026-08-01 19.00.00 Where we dropping_/Audio Record",
  "source_files": ["audioIsaiahEnglish….m4a", "audioLudiSmith….m4a"],
  "artifacts": {
    "transcript": "/Users/isaiahenglish/Documents/audioprocessor/output/<slug>/transcript.md",
    "summary": "/Users/isaiahenglish/Documents/audioprocessor/output/<slug>/summary.md",
    "reflections": { "Ludi Smith": "/…/reflections/Ludi Smith.md" },
    "manifest": "/…/manifest.json"
  },
  "profiles_updated": ["/…/profiles/Ludi Smith.md"],
  "emailed_to": ["mgmt.junglebook@gmail.com"]
}
```

Field notes for the DB tool:
- **`tags`** — the primary selector. Derived from a keyword map in `config.yaml`
  under `tags:` (e.g. tag `expedition` applies when the topic/title contains
  "where we dropping", "intro call", "expedition", etc.). The DB tool should
  **filter on this array** — e.g. ingest every call whose `tags` includes
  `expedition` or `squad`. To add/adjust what counts as a tag, edit
  `config.yaml`; no code change.
- **`artifacts.transcript`** — absolute path to the verbatim transcript to pull
  phrases from. All paths are absolute, so the DB tool can live anywhere.
- **`participants`** — the cleaned display names (also the keys used in
  `profiles/` and `reflections/`).
- Paths use the owner's real home dir at run time; treat them as absolute.

### Recommended DB-tool ingestion pattern

```
for each output/*/manifest.json:
    m = read json
    if wanted_tag in m["tags"]:            # e.g. "expedition" or "squad"
        transcript = read_text(m["artifacts"]["transcript"])
        extract verbatim quotes / phrases from transcript
        store with provenance: call_name, date, participants, tags, source path
```

Because manifests are append-only per call and never mutated after a run, the DB
tool can keep a "last ingested" set of slugs and only process new folders — the
`output/` directory *is* the queue.

---

## 8. profiles/ — the compounding dossiers

`profiles/<Name>.md`, one per non-owner participant, **updated in place** every
call. Schema (from `prompts/profile.md`): Relationship, Snapshot, What they care
about, Communication style, Commitments, Open threads, Personal details, Call
log. The DB tool may read these for per-person context, but they are
*interpretive* (AI-written) — for verbatim quotes, always use the transcript.

---

## 9. Configuration & secrets (what the DB tool must NOT touch)

- `config.yaml` — models, tags, email, paths. Owner-editable.
- `.env` — `ANTHROPIC_API_KEY`, `GMAIL_APP_PASSWORD`. **Secrets. Never read,
  copy, log, or transmit these.**
- `contacts.yaml` — participant emails. **Private PII. Do not export.**

The DB tool should treat `output/`, `profiles/`, and manifests as its inputs and
never write into this project's folders — keep the two systems' file ownership
separate to avoid one clobbering the other.

---

## 10. Privacy & consent (important for the men's-circle use)

These transcripts contain candid, personal group conversation, and reflections
contain therapeutically-adjacent observations about named individuals. Any
downstream use — marketing copy, a book, quotes — must respect that the source
is private group work. Verbatim phrases tie back to identifiable people via the
manifest. Before anything sourced here is published, it should be de-identified
and/or consented. The reflection emails to participants are deliberately
**off by default** for the same reason.

---

## 11. Operating cheatsheet

| Task | Command (run in `~/Documents/audioprocessor`) |
|---|---|
| Open the project | `cd ~/Documents/audioprocessor && source .venv/bin/activate` |
| Process newest call manually | `processcall` |
| Process a specific folder | `python -m call_processor.main --input "<path>/Audio Record"` |
| Get latest code | `git pull` |
| Turn on hands-free automation | `bash scripts/install_automation.sh` |
| Turn it off | `bash scripts/install_automation.sh uninstall` |
| Watch the automation live | `tail -f logs/watcher.log` |
| Edit the summary format | edit `prompts/summary.md` |
| Edit tag rules | edit `config.yaml` under `tags:` |

---

## 12. Component map (for developers)

| File | Responsibility |
|---|---|
| `call_processor/discover.py` | Find tracks, skip combined/video, resolve speaker names |
| `call_processor/transcribe.py` | Whisper backend behind a swappable seam |
| `call_processor/merge.py` | Sort segments by time, collapse into turns |
| `call_processor/render.py` | Write transcript.md; slugify; timestamps |
| `call_processor/summarize.py` | Claude: summary, profiles, reflections, title |
| `call_processor/emailer.py` | SMTP delivery (Gmail), Markdown→HTML |
| `call_processor/manifest.py` | Write manifest.json; derive tags |
| `call_processor/config.py` | Defaults ← config.yaml ← CLI flags; .env; contacts |
| `call_processor/main.py` | CLI + orchestration |
| `scripts/watch_and_process.py` | The folder watcher (launchd runs it) |
| `scripts/install_automation.sh` | One-command automation installer |
| `prompts/*.md` | Editable prompt text (summary, profile, reflection, title) |
```
