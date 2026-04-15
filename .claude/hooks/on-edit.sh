#!/bin/bash
# PostToolUse hook for Edit|MultiEdit|Write: log file changes to state.
# Runs async (non-blocking) — state logging must never slow Claude down.
# Reads tool input JSON from stdin (provided by Claude Code).

cd "$(dirname "$0")/../.." || exit 0

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

# Extract file_path from the tool input JSON Claude Code passes via stdin.
# Handles both Edit (file_path) and Write (file_path) tool shapes.
FILE_PATH=$(cat | "$PYTHON" -c "
import sys, json
try:
    data = json.load(sys.stdin)
    ti = data.get('tool_input') or data
    print(ti.get('file_path') or ti.get('path') or '', end='')
except Exception:
    pass
" 2>/dev/null)

if [ -n "$FILE_PATH" ]; then
    # Fire-and-forget: don't block Claude's next action
    "$PYTHON" scripts/hook_runner.py log-edit "$FILE_PATH" 2>/dev/null &
    "$PYTHON" scripts/hook_runner.py update-file-summary "$FILE_PATH" 2>/dev/null &
fi

exit 0
