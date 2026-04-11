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

# Fire-and-forget warm-up: loads gemma4:e4b into VRAM in the background.
# Runs in parallel with generate-handoff so the model is hot by the time
# the user types their first prompt. No-ops silently if Ollama is down.
curl -sf -X POST http://localhost:11434/api/generate \
    -d '{"model":"gemma4:e4b","prompt":"","keep_alive":-1}' \
    > /dev/null 2>&1 &

# generate-handoff: summarizes via Gemma if state exceeds max_injection_tokens,
# otherwise passes it through verbatim. Always stays within the configured budget.
STATE_CONTENT=$("$PYTHON" scripts/hook_runner.py generate-handoff 2>/dev/null)
if [ -n "$STATE_CONTENT" ]; then
    echo "## Project State (auto-loaded by ApfelContext)"
    echo ""
    echo "$STATE_CONTENT"
fi
exit 0