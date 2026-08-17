#!/bin/bash
# Batch a folder of single-file recordings into timestamped transcripts.
#
# One transcript per recording, named after its source. Recordings that already
# have a transcript are skipped, so an interrupted run — or a new recording
# dropped in next week — picks up where it left off instead of redoing hours of
# work. A file that fails is reported at the end; it never stops the batch.
#
# This is the mixed-recording path: timestamps, no speaker labels (see
# --timestamps-only in README.md). For per-participant Zoom tracks, run
# call_processor.main against the "Audio Record" folder instead.
#
# Usage: bash scripts/transcribe_folder.sh <input folder> <output folder>

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-$REPO/.venv/bin/python}"

# Transcription runs about as long as the audio, so a batch can outlast the
# screensaver. Re-exec under caffeinate once so the Mac stays awake for it.
if [[ -z "${TRANSCRIBE_CAFFEINATED:-}" ]] && command -v caffeinate >/dev/null 2>&1; then
  export TRANSCRIBE_CAFFEINATED=1
  # Re-exec through `bash` explicitly: caffeinate would otherwise have to
  # execute this file directly, which fails when it lacks the execute bit.
  exec caffeinate -i bash "$0" "$@"
fi

cd "$REPO"   # config.yaml and output/ are resolved relative to the repo

# -p/--project selects a named block in config.yaml; PROJECT= does the same.
if [[ "${1:-}" == "-p" || "${1:-}" == "--project" ]]; then
  PROJECT="${2:-}"; shift 2
fi
PROJECT="${PROJECT:-}"

IN="${1:-}"
OUT="${2:-}"

# Unset folders fall back to config.yaml, so the everyday case is just
# `bash scripts/transcribe_folder.sh` with nothing to remember or retype.
if [[ -x "$PY" ]]; then
  if [[ -n "$PROJECT" ]] && ! "$PY" -m call_processor.projects --get transcripts_dir --project "$PROJECT" >/dev/null 2>&1; then
    echo "ERROR: no project named '$PROJECT' in config.yaml." >&2
    echo "Available: $("$PY" -m call_processor.projects --list 2>/dev/null | tr '\n' ' ')" >&2
    exit 1
  fi
  proj() {
    "$PY" -m call_processor.projects --get "$1" ${PROJECT:+--project "$PROJECT"} 2>/dev/null || true
  }
  [[ -z "$IN" ]] && IN="$(proj recordings_dir)"
  [[ -z "$OUT" ]] && OUT="$(proj transcripts_dir)"
fi

if [[ -z "$IN" || -z "$OUT" ]]; then
  echo "Usage: bash scripts/transcribe_folder.sh [input folder] [output folder]" >&2
  echo "" >&2
  echo "Or set them once in config.yaml and pass nothing:" >&2
  echo "  paths:" >&2
  echo "    recordings_dir:  ~/Documents/CASTLE BLINDS/Raw Voice Memos" >&2
  echo "    transcripts_dir: ~/Documents/CASTLE BLINDS/Timestamped Transcribed Memos" >&2
  exit 1
fi

if [[ ! -d "$IN" ]]; then
  echo "ERROR: input folder not found: $IN" >&2
  exit 1
fi
if [[ ! -x "$PY" ]]; then
  echo "ERROR: $PY not found. Run the setup steps in README.md first." >&2
  exit 1
fi

mkdir -p "$OUT"

transcribed=0
skipped=0
failed=()

while IFS= read -r -d '' f; do
  base="$(basename "$f")"
  target="$OUT/${base%.*}.md"

  if [[ -f "$target" ]]; then
    echo "skip   $base  (transcript already exists)"
    skipped=$((skipped + 1))
    continue
  fi

  echo ""
  echo "=====  $base"
  if "$PY" -m call_processor.main --timestamps-only --input "$f" --out "$target"; then
    transcribed=$((transcribed + 1))
  else
    echo "FAILED: $base — continuing with the rest" >&2
    failed+=("$base")
    rm -f "$target"   # never leave a half-written transcript to be skipped later
  fi
done < <(find "$IN" -type f \
  \( -iname '*.m4a' -o -iname '*.mp3' -o -iname '*.wav' \
     -o -iname '*.flac' -o -iname '*.aac' \) -print0 | sort -z)

echo ""
echo "=== Batch summary ==="
echo "Transcribed : $transcribed"
echo "Skipped     : $skipped (already had a transcript)"
if (( ${#failed[@]} )); then
  echo "Failed      : ${#failed[@]}"
  for name in "${failed[@]}"; do echo "  - $name"; done
  echo ""
  echo "Re-run this same command to retry only the failures."
  exit 1
fi
echo "Output      : $OUT"
