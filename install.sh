#!/bin/bash
# Install llm-notes skills globally for Claude Code
# After install, use /kb-init, /kb-compile, /kb-qa, /kb-lint, /kb-slides, /kb-viz, /kb-search from any directory

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$SKILLS_DIR"

for skill in kb-init kb-compile kb-qa kb-lint kb-slides kb-viz kb-search; do
  ln -sfn "$SCRIPT_DIR/skills/$skill" "$SKILLS_DIR/$skill"
  echo "Installed /$skill"
done

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo ""
  echo "Python interpreter not found: $PYTHON_BIN"
  exit 1
fi

if "$PYTHON_BIN" -m pip install --user -e "$SCRIPT_DIR" >/dev/null 2>&1; then
  echo "Installed llm-notes Python helpers"
elif "$PYTHON_BIN" -m pip install -e "$SCRIPT_DIR" >/dev/null 2>&1; then
  echo "Installed llm-notes Python helpers"
elif "$PYTHON_BIN" -m pip install --user -e "$SCRIPT_DIR" --break-system-packages >/dev/null 2>&1; then
  echo "Installed llm-notes Python helpers"
elif "$PYTHON_BIN" -m pip install -e "$SCRIPT_DIR" --break-system-packages >/dev/null 2>&1; then
  echo "Installed llm-notes Python helpers"
else
  echo ""
  echo "Failed to install the llm-notes Python helpers."
  echo "Try running manually: $PYTHON_BIN -m pip install --user -e \"$SCRIPT_DIR\""
  exit 1
fi

echo ""
echo "Done! Skills are now available globally in Claude Code."
echo "Try: /kb-init ."
