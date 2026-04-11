#!/bin/bash
# UserPromptSubmit hook: auto-compact verbose prose prompts before Claude processes them.
# Runs synchronously — output is prepended to the context Claude sees.
# Prints nothing if prompt is short, looks like code/structured data, or backend is down.

cd "$(dirname "$0")/../.." || exit 0

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

# Claude Code passes the prompt as JSON on stdin: {"prompt": "..."}
# compress-prompt reads it, skips non-prose, outputs compressed version + instruction.
"$PYTHON" scripts/hook_runner.py compress-prompt 2>/dev/null

exit 0
