#!/bin/bash
# Batch a folder of recordings into speaker-labeled, timestamped transcripts
# using WhisperX (transcription + diarization) installed in its own virtualenv.
#
# Unlike transcribe_folder.sh — which produces timestamps only and leaves
# attribution to you — this separates the voices acoustically and puts names on
# them. Names are assigned by total speaking time (see whisperx_md.py), so pass
# them in order of who talks most.
#
# Recordings that already have a transcript are skipped, so an interrupted run
# resumes. The raw WhisperX JSON is kept alongside the transcripts, so speaker
# names can be corrected later without re-transcribing anything.
#
# Usage: bash scripts/transcribe_folder_whisperx.sh <input folder> <output folder> ["Name1,Name2"]
#
# Environment overrides:
#   WHISPERX_VENV  path to the WhisperX virtualenv  (default ~/Documents/whisperx-tool/.venv)
#   SPEAKERS       number of people in the recordings (default 2)
#   WHISPER_MODEL  Whisper model to use             (default large-v3)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"   # config.yaml is resolved relative to the repo

# The converter is pure standard library, so any Python 3 can run it.
CONVERT_PY="${CONVERT_PY:-$REPO/.venv/bin/python}"
[[ -x "$CONVERT_PY" ]] || CONVERT_PY="$(command -v python3)"

cfg() { "$CONVERT_PY" -m call_processor.paths "$1" 2>/dev/null || true; }

# Environment beats config.yaml, which beats the built-in default.
WHISPERX_VENV="${WHISPERX_VENV:-$(cfg whisperx.venv)}"
WHISPERX_VENV="${WHISPERX_VENV:-$HOME/Documents/whisperx-tool/.venv}"
SPEAKERS="${SPEAKERS:-$(cfg whisperx.num_speakers)}"
SPEAKERS="${SPEAKERS:-2}"
WHISPER_MODEL="${WHISPER_MODEL:-$(cfg whisperx.model)}"
WHISPER_MODEL="${WHISPER_MODEL:-large-v3}"

WHISPERX="$WHISPERX_VENV/bin/whisperx"
VENV_PY="$WHISPERX_VENV/bin/python"

if [[ -z "${TRANSCRIBE_CAFFEINATED:-}" ]] && command -v caffeinate >/dev/null 2>&1; then
  export TRANSCRIBE_CAFFEINATED=1
  exec caffeinate -i bash "$0" "$@"
fi

IN="${1:-$(cfg paths.recordings_dir)}"
OUT="${2:-$(cfg paths.transcripts_dir)}"
NAMES="${3:-$(cfg whisperx.speaker_names)}"

if [[ -z "$IN" || -z "$OUT" ]]; then
  echo "Usage: bash scripts/transcribe_folder_whisperx.sh [input folder] [output folder] [\"Name1,Name2\"]" >&2
  echo "" >&2
  echo "Or set them once in config.yaml and pass nothing:" >&2
  echo "  paths:" >&2
  echo "    recordings_dir:  ~/Documents/CASTLE BLINDS/Raw Voice Memos" >&2
  echo "    transcripts_dir: ~/Documents/CASTLE BLINDS/Timestamped Transcribed Memos" >&2
  echo "  whisperx:" >&2
  echo "    speaker_names: [\"Dad\", \"Isaiah\"]   # most talkative first" >&2
  exit 1
fi
if [[ ! -d "$IN" ]]; then
  echo "ERROR: input folder not found: $IN" >&2
  exit 1
fi
if [[ ! -x "$WHISPERX" ]]; then
  echo "ERROR: whisperx not found at $WHISPERX" >&2
  echo "Install it, or point WHISPERX_VENV at the right virtualenv." >&2
  exit 1
fi

# Python installed from python.org ships without a usable CA bundle, so
# torch.hub's model download fails TLS verification. certifi has the bundle.
if [[ -z "${SSL_CERT_FILE:-}" ]] && [[ -x "$VENV_PY" ]]; then
  if CERTS="$("$VENV_PY" -c 'import certifi; print(certifi.where())' 2>/dev/null)"; then
    export SSL_CERT_FILE="$CERTS"
  fi
fi

JSON_DIR="$OUT/whisperx-json"
mkdir -p "$OUT" "$JSON_DIR"

transcribed=0
skipped=0
failed=()

while IFS= read -r -d '' f; do
  base="$(basename "$f")"
  stem="${base%.*}"
  target="$OUT/$stem.md"
  json="$JSON_DIR/$stem.json"

  if [[ -f "$target" ]]; then
    echo "skip   $base  (transcript already exists)"
    skipped=$((skipped + 1))
    continue
  fi

  echo ""
  echo "=====  $base"

  # Re-use an existing JSON so a failure in the (cheap) naming step never
  # costs another full (expensive) transcription pass.
  if [[ ! -f "$json" ]]; then
    if ! "$WHISPERX" "$f" \
        --model "$WHISPER_MODEL" \
        --compute_type int8 \
        --diarize \
        --min_speakers "$SPEAKERS" --max_speakers "$SPEAKERS" \
        --language en \
        --output_format json \
        --output_dir "$JSON_DIR"; then
      echo "FAILED: $base — continuing with the rest" >&2
      failed+=("$base")
      rm -f "$json"
      continue
    fi
  else
    echo "(re-using existing $stem.json)"
  fi

  if "$CONVERT_PY" -m call_processor.whisperx_md "$json" \
      ${NAMES:+--names "$NAMES"} --title "$stem" --out "$target"; then
    transcribed=$((transcribed + 1))
  else
    echo "FAILED to convert: $base" >&2
    failed+=("$base")
    rm -f "$target"
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
echo "Raw JSON    : $JSON_DIR  (re-name speakers without re-transcribing)"
