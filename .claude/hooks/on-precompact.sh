#!/bin/bash
cd "$(dirname "$0")/../.." || exit 0
PYTHON=".venv/bin/python"
[ ! -x "$PYTHON" ] && PYTHON="${HOME}/.promptcompactor/.venv/bin/python"
[ ! -x "$PYTHON" ] && PYTHON="python3"

MSG=$("$PYTHON" scripts/hook_runner.py precompact-summary 2>/dev/null)

if [ -n "$MSG" ]; then
    printf '{"systemMessage": "%s"}' "$(echo "$MSG" | sed 's/"/\\"/g' | tr '\n' ' ')"
else
    printf '{"continue": true}'
fi
exit 0