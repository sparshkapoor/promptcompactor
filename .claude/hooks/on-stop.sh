#!/bin/bash
# Stop hook: log a progress entry when Claude finishes a response turn.
# Runs async (non-blocking).
# Note: the turn content is not available in Stop hooks — we log a timestamp
# marker so progress.md has a record of when each turn completed.

cd "$(dirname "$0")/../.." || exit 0

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

"$PYTHON" scripts/hook_runner.py log-progress "Turn completed" 2>/dev/null &

exit 0
