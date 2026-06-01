#!/bin/bash
# PreCompact hook: replace Claude's built-in context compaction with a free local Gemma call.
# Claude Code fires this hook when context hits autoCompactWindow tokens.
# Output on stdout becomes the compacted context that replaces the full window.
# Falls back silently if Gemma/Ollama is unavailable — Claude's built-in compaction then runs.

cd "$(dirname "$0")/../.." || exit 0
PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="${HOME}/.promptcompactor/.venv/bin/python"
fi
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

HANDOFF=$("$PYTHON" scripts/hook_runner.py generate-handoff 2>/dev/null)
if [ -n "$HANDOFF" ]; then
    echo "$HANDOFF"
fi
exit 0
