#!/bin/bash
# UserPromptSubmit hook: auto-compact verbose prose prompts before Claude processes them.
# Runs synchronously — output is prepended to the context Claude sees.
# Prints nothing if prompt is short, looks like code/structured data, or backend is down.

cd "$(dirname "$0")/../.." || exit 0

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

# Read stdin once (Claude Code passes JSON: {"prompt": "..."})
INPUT=$(cat)

# Fast exit for short messages — skip Python startup entirely
WORD_COUNT=$(printf '%s' "$INPUT" | wc -w | tr -d ' ')
[ "${WORD_COUNT:-0}" -lt 40 ] && exit 0

# Try daemon first (no Python startup cost); fall back to direct invocation
printf 'compress-prompt\n%s' "$INPUT" | \
    curl -sf --connect-timeout 0.5 --max-time 8 \
    -X POST http://localhost:7737/run --data-binary @- 2>/dev/null \
    || printf '%s' "$INPUT" | "$PYTHON" scripts/hook_runner.py compress-prompt 2>/dev/null

exit 0
