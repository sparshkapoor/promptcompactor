#!/bin/bash
# SessionStart hook: inject project state as context.
# Runs synchronously — Claude Code reads stdout before processing the first prompt.
# Output is prepended to Claude's context window for the session.

# Always run from project root regardless of where Claude Code was launched
cd "$(dirname "$0")/../.." || exit 0
PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi
# generate-handoff: summarizes via Gemma if state exceeds max_injection_tokens,
# otherwise passes it through verbatim. Always stays within the configured budget.
STATE_CONTENT=$("$PYTHON" scripts/hook_runner.py generate-handoff 2>/dev/null)
if [ -n "$STATE_CONTENT" ]; then
    echo "## Project State (auto-loaded by ApfelContext)"
    echo ""
    echo "$STATE_CONTENT"
fi
exit 0