#!/bin/bash
# Install llm-notes skills globally for Claude Code
# After install, use /kb-init, /kb-compile, /kb-qa, /kb-lint, /kb-slides, /kb-viz, /kb-search from any directory

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"

mkdir -p "$SKILLS_DIR"

for skill in kb-init kb-compile kb-qa kb-lint kb-slides kb-viz kb-search; do
  ln -sfn "$SCRIPT_DIR/skills/$skill" "$SKILLS_DIR/$skill"
  echo "Installed /$skill"
done

echo ""
echo "Done! Skills are now available globally in Claude Code."
echo "Try: /kb-init ."
