#!/bin/bash
# Stop hook: log a progress entry when Claude finishes a response turn.
# Runs async (non-blocking).
# Only logs when the turn had real edits (flag set by log-edit in hook_runner.py).

cd "$(dirname "$0")/../.." || exit 0

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

# log-turn-if-edited checks the per-project sidecar flag, logs if set, clears it.
# Flag lives in get_state_dir()/.edit_this_turn — no shell-level path knowledge needed.
printf 'log-turn-if-edited\n' | \
    curl -sf --connect-timeout 0.5 --max-time 8 \
    -X POST http://localhost:7737/run --data-binary @- 2>/dev/null \
    || "$PYTHON" scripts/hook_runner.py log-turn-if-edited 2>/dev/null &

exit 0
