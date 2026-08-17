# Call Processor — local multitrack call transcription

Turns a folder of **per-participant audio files** (e.g. Zoom's "Record separate
participant audio files") into a single, perfectly speaker-labeled transcript —
plus an optional executive summary and a compounding profile of each participant.

## Why this works so well

The fragile part of transcription is **diarization** — an AI guessing *who spoke
when* from one mixed recording. This tool never does diarization, because the
input already solves it: each participant is recorded to their **own file**.
Every word in `Jane.m4a` is Jane, with certainty. Attribution is a filename
lookup, not a machine-learning problem. Each track is transcribed independently
(locally, with Whisper), tagged with its speaker, and merged back together by
timestamp into one conversation. All tracks come from the same recording
session and share one timeline, so no clock-sync or drift correction is needed.

**Separate tracks in → labeled transcript out, no guessing.**

## Setup (macOS / Apple Silicon)

```bash
# 1. System dep (decodes .m4a etc.)
brew install ffmpeg

# 2. Environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. API key (only needed for summaries/profiles — transcription is 100% local)
cp .env.example .env        # then put ANTHROPIC_API_KEY=... in .env

# 4. First run downloads the Whisper model once (~1.5GB for large-v3), then runs offline
python -m call_processor.main --input "<path to Audio Record folder>" --call-name "Test call"
```

**Linux/Windows:** works as-is on CPU. On an NVIDIA GPU, edit `config.yaml`
(`whisper.compute_type: float16`) and pass `device="cuda"` — see the note in
`call_processor/transcribe.py`. Install ffmpeg via your package manager
(`apt install ffmpeg`, `choco install ffmpeg`).

## Getting separate tracks from Zoom

Zoom → **Settings → Recording → "Record a separate audio file of each
participant"** (host must record locally). After the meeting, Zoom writes one
file per participant into `.../Zoom/<meeting>/Audio Record/`. Point `--input`
at that folder.

## Usage

```bash
python -m call_processor.main \
  --input "/Users/you/Documents/Zoom/2026-07-15 Acme/Audio Record" \
  --call-name "Acme discovery — 2026-07-15" \
  [--model large-v3] \
  [--language en] \
  [--no-summary] \
  [--map "audio1234=Isaiah,audio5678=Jane Cooper"] \
  [--granularity turn|sentence] \
  [--no-speaker-labels] \
  [--config ./config.yaml]
```

- `--input` (required): folder of per-participant audio files, or a single audio file.
- `--call-name`: used for the output folder + headers. Defaults to the input
  folder name + today's date.
- `--map`: inline speaker overrides (`filename_stem=Display Name`, comma-separated).
  The same overrides can live in `config.yaml` under `speakers:`.
- `--no-summary`: transcript only; no API calls at all.
- `--granularity`: `turn` (default) collapses consecutive same-speaker segments
  into one line; `sentence` gives every sentence its own `[HH:MM:SS]`, cut on
  Whisper's word timings.
- `--no-speaker-labels`: lines read `**[00:01:05]** text` with no name.
- `--out`: write the transcript to an exact file path (parent folders created)
  instead of `output/<slug>/transcript.md` — handy for batching into a folder
  you organise yourself.

Outputs:

- `output/<call-slug>/transcript.md` — chronological, speaker-labeled transcript
- `output/<call-slug>/summary.md` — executive summary (if summarize enabled)
- `profiles/<Speaker Name>.md` — evolving dossier per non-owner participant,
  updated in place each call (if summarize enabled)

## One mixed recording: timestamps without speakers

Sometimes you have a single already-mixed file (a voice memo, a download) and
you already have a speaker-attributed transcript of it from somewhere else. You
don't need this tool to guess speakers — you need a **timestamp on every
sentence** so you can line the two up.

```bash
python -m call_processor.main --input ~/Downloads/conversation.m4a --timestamps-only
```

`--timestamps-only` is a preset: `--input` takes the file directly, every
sentence gets its own line and timestamp, no speaker names are printed, the
cross-track bleed filter is off (nothing can bleed when there's one source),
and no API calls are made. You get:

```markdown
**[00:00:00]** So we met Dr. Cooper.

**[00:00:04]** She said yes.
```

To batch a whole folder of recordings, one transcript each:

```bash
bash scripts/transcribe_folder.sh <input folder> <output folder>
```

Recordings that already have a transcript are skipped, so an interrupted run —
or a recording added later — resumes instead of redoing hours of work. A file
that fails is reported at the end without stopping the batch, and re-running
retries only the failures.

Point `--input` at each **file**, not at a folder, if you call
`call_processor.main` directly — a folder is read as the per-participant tracks
of one call and would merge separate recordings into a single transcript. The
batch script above handles this for you.

Once a transcript exists, `prompts/attribute_speakers.md` is a reusable prompt
for the second pass: hand it and the transcript to Claude to get speaker labels
attached, with an explicit list of the lines it wasn't sure about.

The run's `manifest.json` records `"speaker_attributed": false` and an empty
`participants` list, so a downstream tool never mistakes a filename for a
speaker. This mode does **not** do diarization — attribution still comes from
separate tracks, or from the other transcript you're aligning against.

## Speaker names

Names resolve in priority order:

1. Explicit override (`--map` or `speakers:` in config), keyed by filename stem.
2. Derived from the filename: Zoom prefixes files with the participant's name;
   the tool strips `audioNNNN_` prefixes, trailing `_<digits>` / GUID junk,
   collapses `_`/`-` to spaces, and title-cases.
3. Fallback to the raw stem, with a logged warning suggesting an override.

A single combined/mixed file that Zoom sometimes also drops in the folder
(e.g. `audio_only.m4a`) is detected heuristically and skipped — the log shows
what was skipped so you can correct it with `--map` if the guess was wrong.

## Privacy

Transcription runs **entirely on your machine** ($0 marginal cost, works
offline after the one-time model download). The **only** thing that ever leaves
your machine is the transcript text sent to the Anthropic API for the optional
summary/profile step — disable it with `--no-summary` or
`summarize.enabled: false` for fully-local operation.

## Audio tips

- **Both parties on headphones = flawless.** Without headphones, each mic can
  faintly pick up the other person through the speakers; `vad_filter` plus the
  `min_segment_duration` filter remove most of that bleed, but you may need an
  occasional manual label fix.
- Phone dial-in participants are merged by Zoom into one track and will appear
  as one speaker.
- Someone joining late is fine — their timestamps simply start later.

## Tests

```bash
python -m unittest discover tests -v     # or: pytest tests/
```

`tests/test_merge.py` proves the timestamp-merge logic with hand-made segments —
no audio or model download needed.

## Project layout

```
call_processor/
  main.py          # CLI entry, orchestration
  config.py        # defaults ← config.yaml ← CLI flags; .env loading
  discover.py      # find files, skip combined/mixed, resolve speakers
  transcribe.py    # backend seam + faster-whisper impl (mlx-whisper can drop in)
  merge.py         # sort + collapse into speaker turns
  sentences.py     # sort + split into per-sentence lines (granularity: sentence)
  render.py        # transcript markdown writer
  summarize.py     # Claude summary + compounding profile updates
prompts/           # editable prompt text for summary + profiles
tests/             # pure-python unit tests
```

## One-word shortcut

Tired of remembering the paths? Install a single command that transcribes a
folder of recordings from anywhere:

```bash
bash scripts/install_shortcut.sh memos \
  ~/Documents/'CASTLE BLINDS'/'Raw Voice Memos' \
  ~/Documents/'CASTLE BLINDS'/'Timestamped Transcribed Memos'
```

Open a new Terminal window and type `memos`. Re-running the installer updates
the shortcut instead of adding a second copy; remove it with
`bash scripts/install_shortcut.sh memos --uninstall`.

## Speaker names from a single mixed recording (WhisperX)

`--timestamps-only` gives timestamps but no speakers. To get both from one
mixed recording, install [WhisperX](https://github.com/m-bain/whisperX) in its
own virtualenv (keeping its dependencies away from this repo's), accept the
pyannote model conditions on HuggingFace, then:

```bash
bash scripts/transcribe_folder_whisperx.sh <input folder> <output folder> "Dad,Isaiah"
```

Same resume-and-retry behaviour as `transcribe_folder.sh`. WhisperX separates
voices but can't know whose they are, so it emits `SPEAKER_00`/`SPEAKER_01`;
`call_processor/whisperx_md.py` converts its JSON into this repo's transcript
format and puts the supplied names on those labels **in order of total speaking
time**. That's a heuristic — the transcript header says so, so a wrong guess is
visible rather than silent. Fix one without re-transcribing:

```bash
python -m call_processor.whisperx_md "<output>/whisperx-json/<name>.json" \
  --map "SPEAKER_00=Isaiah,SPEAKER_01=Dad" --out "<output>/<name>.md"
```

The raw JSON is kept for exactly this reason.

## Drag-and-drop page

```bash
python scripts/web_ui.py
```

Opens `http://127.0.0.1:8756` — drop in a recording, pick where the transcript
should be saved (**Choose…** opens the real macOS folder dialog; a browser can
only return an opaque handle, but this server is on the same machine and can
raise the native chooser itself), and it runs the batch scripts above. Jobs run one at a time
(transcription is CPU-bound; running several at once just makes them all
slower). It binds to 127.0.0.1 only, because the server starts processes and
must not be reachable from the network. Nothing is uploaded anywhere — the
audio goes from your browser to a server on the same machine.

## Set your folders once

Typing long paths on every run gets old. Put them in `config.yaml`:

```yaml
paths:
  recordings_dir:  ~/Documents/CASTLE BLINDS/Raw Voice Memos
  transcripts_dir: ~/Documents/CASTLE BLINDS/Timestamped Transcribed Memos
whisperx:
  speaker_names: ["Dad", "Isaiah"]   # most talkative first
```

Then every entry point works with no arguments:

```bash
bash scripts/transcribe_folder.sh              # timestamps only
bash scripts/transcribe_folder_whisperx.sh     # speaker names too
python3 scripts/web_ui.py                      # page opens pre-filled
```

Command-line arguments still win over config, and environment variables
(`WHISPERX_VENV`, `SPEAKERS`, `WHISPER_MODEL`) win over both. `config.yaml` is
gitignored, so **transcripts and folder paths stay off GitHub** — keep the
recordings and transcripts outside the repo, in a folder of your own.

Install the one-word shortcut against config rather than fixed folders, so
editing `config.yaml` later needs no reinstall:

```bash
bash scripts/install_shortcut.sh memos
SCRIPT=transcribe_folder_whisperx.sh bash scripts/install_shortcut.sh memos
```

### Progress

The page shows a live percentage while a job runs. There's no progress API to
ask — the percentage is read out of the transcriber's own output (WhisperX
prints a `[12.3 --> 45.6]` line per segment; `call_processor` prints
`[progress] position/total`) and measured against the recording's duration from
`ffprobe`. Diarization runs after transcription and reports nothing useful, so
the bar holds while the label switches to "finding speakers".

`call_processor` only emits those progress lines when its output is being
captured — on a terminal the rich progress bar already shows this, and the
extra lines would scribble over it.

## Several projects

One tool, several bodies of work — each with its own folders and speakers:

```yaml
default_project: castle
projects:
  castle:
    recordings_dir:  ~/Documents/CASTLE BLINDS/Raw Voice Memos
    transcripts_dir: ~/Documents/CASTLE BLINDS/Timestamped Transcribed Memos
    speaker_names:   ["Dad", "Isaiah"]
  interviews:
    recordings_dir:  ~/Documents/Interviews/raw
    transcripts_dir: ~/Documents/Interviews/transcripts
    speaker_names:   ["Isaiah", "Guest"]
```

```bash
bash scripts/transcribe_folder.sh                  # default_project
bash scripts/transcribe_folder.sh -p interviews    # a specific one
```

Anything a project doesn't set falls back to the top-level `paths:` and
`whisperx:` sections, so a single-project setup needs no `projects:` block and
behaves exactly as before. A `-p` name that isn't in the config is an error
rather than a silent fall-through — a typo shouldn't quietly write a client's
transcripts into your family folder.

With no `default_project`, a lone project is still used automatically; several
projects and no default means the top-level settings apply, because guessing
between them is worse than not guessing.

The web page grows a project picker when projects exist, and switching it fills
in that project's folder and speakers. Per-project shortcuts work too:

```bash
bash scripts/install_shortcut.sh castle
PROJECT=interviews bash scripts/install_shortcut.sh interviews
```
