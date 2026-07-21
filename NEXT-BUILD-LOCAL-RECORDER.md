# Kickoff prompt — next build: local multitrack recorder for casual calls

> **Paste this whole file as your first message in a new Claude Code session
> opened on the `audioprocessor` repo.** It orients the fresh session on what
> already exists and defines the next thing to build. (Starting a new session
> keeps the context window clean — the previous session got long.)

---

## Orientation (read before building)

You are in the `~/Documents/audioprocessor` repo. A complete, working system
already exists here: it turns **per-participant Zoom audio tracks** into
verbatim speaker-labeled transcripts, summaries, per-person profiles, and a
`manifest.json`, then emails the summary — hands-free via a launchd watcher.

**Read `SYSTEM.md` first** for the full architecture, the `output/<slug>/`
layout, the `manifest.json` schema, and the transcript format. Do not change
that pipeline — you are adding a new *front-end* that feeds it.

Key fact you will build against: the pipeline ingests a **folder containing one
audio file per speaker** (Zoom writes these to `.../<meeting>/Audio Record/`).
Given such a folder, `python -m call_processor.main --input "<folder>"` does
everything downstream. So if a new recorder produces the same folder shape, the
entire existing system handles the rest with zero changes.

---

## What to build

A **locally-hosted macOS recorder** for casual 1:1 calls that are NOT on Zoom —
WhatsApp, iMessage/FaceTime, or any app. The problem: Zoom's per-participant
recording is what makes transcription clean, but casual calls with friends feel
better on WhatsApp, which gives no separate tracks. Solve it locally.

### The core idea
On a Mac, two audio streams can be captured separately:
- **My microphone** → my voice (one track).
- **System audio output** (what the call app plays to me) → the other person's
  voice (a second track).

Capturing these as two separate files reproduces the per-person separation the
pipeline needs — app-agnostic (works for WhatsApp, iMessage, FaceTime, phone via
Continuity, anything). With headphones on, separation is essentially perfect
(the mic hears only me; the system-audio track has only them).

### The handoff contract (this is the whole integration)
The recorder must, on stop, write a folder shaped like the pipeline expects:

```
~/Documents/audioprocessor/casual/<YYYY-MM-DD HH.MM.SS Title>/Audio Record/
    <MyName>.wav      ← my mic
    <TheirName>.wav   ← system audio (their voice)
```

Then either invoke `python -m call_processor.main --input "<that Audio Record
folder>" --call-name "<Title>"` directly, or drop it where the watcher can find
it. (Decide with the user whether to extend the existing watcher to also scan a
`casual/` root, or have the recorder invoke the pipeline itself on stop — the
latter is simpler and more predictable.)

Filenames become speaker names (the pipeline title-cases them), so naming the
two files after the two people gives correct labels for free.

### Technical approach (research current best options, then propose)
Capturing system audio on macOS needs a virtual audio device. Evaluate:
- **BlackHole** (free, open-source virtual audio driver) + an Aggregate/Multi-
  Output Device in Audio MIDI Setup, so system audio is routed to both the
  speakers/headphones AND a capture channel.
- **Loopback** (Rogue Amoeba, paid) — more polished, easier multi-source setup.
- macOS `ScreenCaptureKit` can capture system audio programmatically (modern,
  no third-party driver) — worth checking if it can cleanly separate app audio.

Recommend the simplest reliable path for a non-technical user. A one-time device
setup + a dead-simple start/stop is the goal. Propose the UX (a tiny menu-bar
app? a CLI with a global hotkey? a Shortcut?) — keep it boring and reliable;
match the existing project's Python-first, low-dependency style where possible.

### Requirements
1. Two separate output files (my mic, their audio) — never a single mixed file.
2. Writes the `Audio Record`-style folder above so the existing pipeline
   ingests it unchanged.
3. One-action start, one-action stop. No fiddling mid-call.
4. Handles headphones (the good case) and documents that headphones = best
   quality.
5. Reuses the existing config, output locations, and the pipeline's summary/
   email/manifest path — do not duplicate that logic.

### Consent — build this in, don't skip it
Recording a call has legal and ethical weight, and unlike Zoom there is no
built-in "this call is being recorded" banner. Casual friends on WhatsApp will
not expect it. Bake in a norm: the tool should make it easy/normal to tell the
other person they're being recorded (and, for the men's-circle ethos, why).
Discuss with the user how they want consent handled before shipping auto-record.
Two-party-consent jurisdictions exist — flag it; don't give legal advice.

### Explicitly out of scope
- Do not try to split a single already-mixed recording (e.g. a Voice Memos
  file) into speakers — that's the diarization problem this whole system avoids.
  This build is about capturing two clean streams at record time.
- Do not modify the transcription/merge/summary pipeline. Feed it; don't change
  it.

---

## Suggested build order
1. Confirm the capture approach on the user's actual Mac (test that mic and
   system audio land in two separate files with real audio).
2. Minimal recorder: start → record two streams → stop → write the `Audio
   Record` folder.
3. Wire the handoff (invoke the pipeline on stop). Verify a real casual call
   flows all the way to a summary email.
4. UX polish (hotkey / menu bar), naming prompts (who's the other person),
   consent affordance.
5. Document setup in the README; commit after each step.
```
