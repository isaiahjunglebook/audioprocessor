#!/bin/bash
# Install a one-word shell command that transcribes a folder of recordings.
#
# Turns the three-step "cd, activate, long path" dance into a single word you
# type from anywhere. Re-running the installer updates the existing shortcut
# rather than adding a second copy.
#
# Usage:   bash scripts/install_shortcut.sh <name> <input folder> <output folder>
# Example: bash scripts/install_shortcut.sh memos \
#            ~/Documents/'CASTLE BLINDS'/'Raw Voice Memos' \
#            ~/Documents/'CASTLE BLINDS'/'Timestamped Transcribed Memos'
# Remove:  bash scripts/install_shortcut.sh <name> --uninstall

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:-}"
IN="${2:-}"
OUT="${3:-}"
# Which batch script the shortcut runs. Override for the WhisperX pipeline:
#   SCRIPT=transcribe_folder_whisperx.sh bash scripts/install_shortcut.sh memos
SCRIPT="${SCRIPT:-transcribe_folder.sh}"

# zsh is the macOS default; fall back to bash's rc file if there's no .zshrc.
if [[ -n "${ZDOTDIR:-}" || "${SHELL:-}" == *zsh* || -f "$HOME/.zshrc" ]]; then
  RC="${ZDOTDIR:-$HOME}/.zshrc"
else
  RC="$HOME/.bash_profile"
fi

if [[ -z "$NAME" ]]; then
  echo "Usage: bash scripts/install_shortcut.sh <name> <input folder> <output folder>" >&2
  exit 1
fi

START="# >>> audioprocessor: $NAME >>>"
END="# <<< audioprocessor: $NAME <<<"

# Drop any previous copy of this shortcut so re-running never stacks them up.
if [[ -f "$RC" ]] && grep -qF "$START" "$RC"; then
  awk -v s="$START" -v e="$END" '
    $0 == s { skip = 1 } !skip { print } $0 == e { skip = 0 }
  ' "$RC" > "$RC.tmp" && mv "$RC.tmp" "$RC"
  echo "Replaced the existing '$NAME' shortcut."
fi

if [[ "${2:-}" == "--uninstall" ]]; then
  echo "Removed. Open a new Terminal window for it to take effect."
  exit 0
fi

if [[ -z "$IN" && -z "$OUT" ]]; then
  # No folders given: let the script read them from config.yaml at run time,
  # so editing config.yaml later updates the shortcut with no reinstall.
  BODY="bash \"$REPO/scripts/$SCRIPT\""
  WHERE="the folders set in config.yaml (paths.recordings_dir -> paths.transcripts_dir)"
else
  if [[ -z "$IN" || -z "$OUT" ]]; then
    echo "ERROR: pass both folders, or neither (to use config.yaml)." >&2
    exit 1
  fi
  if [[ ! -d "$IN" ]]; then
    echo "ERROR: input folder not found: $IN" >&2
    exit 1
  fi
  # Absolute paths, resolved now, so the shortcut works from any directory.
  IN="$(cd "$IN" && pwd)"
  mkdir -p "$OUT"
  OUT="$(cd "$OUT" && pwd)"
  BODY="bash \"$REPO/scripts/$SCRIPT\" \"$IN\" \"$OUT\""
  WHERE="$IN
    -> $OUT"
fi

cat >> "$RC" <<SHORTCUT
$START
$NAME() {
  $BODY
}
$END
SHORTCUT

echo ""
echo "Done. Open a NEW Terminal window, then just type:"
echo ""
echo "    $NAME"
echo ""
echo "It transcribes:"
echo "    $WHERE"
echo ""
echo "Recordings already transcribed are skipped, so adding one new memo and"
echo "typing '$NAME' again processes only that memo."
echo ""
echo "Remove it later with: bash scripts/install_shortcut.sh $NAME --uninstall"
