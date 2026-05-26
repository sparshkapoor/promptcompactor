#!/usr/bin/env bash
# install.sh — Idempotent global installer for PromptCompactor.
#
# What this does:
#   1. Copies the repo to COMPACTOR_HOME (default: ~/.promptcompactor)
#   2. Creates a virtualenv and installs Python deps
#   3. Registers the MCP server globally in ~/.claude/settings.json
#   4. Registers global hooks in ~/.claude/settings.json
#   5. Installs launchd plists for Ollama auto-start and hook daemon
#
# Usage:
#   ./scripts/install.sh                         # installs to ~/.promptcompactor
#   COMPACTOR_HOME=/opt/apfel ./scripts/install.sh   # custom install root
#
# Safe to re-run — all operations are idempotent.

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

COMPACTOR_HOME="${COMPACTOR_HOME:-$HOME/.promptcompactor}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

# ── Helpers ───────────────────────────────────────────────────────────────────

info()    { echo "  [compactor] $*"; }
success() { echo "  ✓ $*"; }
warn()    { echo "  ⚠ $*" >&2; }
die()     { echo "  ✗ $*" >&2; exit 1; }

require_cmd() { command -v "$1" &>/dev/null || die "Required command not found: $1"; }

# Merge a JSON object into ~/.claude/settings.json under a given top-level key.
# Uses Python for safe JSON manipulation — no jq dependency.
json_merge() {
    local key="$1"
    local value="$2"
    "$COMPACTOR_HOME/.venv/bin/python" - "$key" "$value" <<'PYEOF'
import json, sys
from pathlib import Path

settings_path = Path(sys.argv[1] if len(sys.argv) > 1 else "") if False else Path("$CLAUDE_SETTINGS")
settings_path = Path("$CLAUDE_SETTINGS")
settings_path.parent.mkdir(parents=True, exist_ok=True)

key = sys.argv[1]
value = json.loads(sys.argv[2])

try:
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
except (json.JSONDecodeError, OSError):
    settings = {}

if isinstance(value, dict):
    existing = settings.get(key, {})
    settings[key] = {**existing, **value} if isinstance(existing, dict) else value
elif isinstance(value, list):
    existing = settings.get(key, [])
    settings[key] = existing + value if isinstance(existing, list) else value
else:
    settings[key] = value

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print(f"  ✓ Updated {settings_path} [{key}]")
PYEOF
}

# ── Step 1: System checks ─────────────────────────────────────────────────────

info "Checking system requirements..."

[[ "$(uname -s)" == "Darwin" ]] || die "PromptCompactor requires macOS."
require_cmd python3
require_cmd curl

python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" \
    || die "Python >= 3.10 required (found $(python3 --version))"

command -v ollama &>/dev/null \
    || warn "Ollama not found — install from https://ollama.ai before using PromptCompactor"

success "System checks passed"

# ── Step 2: Copy repo to COMPACTOR_HOME ──────────────────────────────────────────

info "Installing to $COMPACTOR_HOME..."

if [[ "$REPO_ROOT" == "$COMPACTOR_HOME" ]]; then
    info "Running from install root — skipping copy"
else
    require_cmd rsync
    mkdir -p "$COMPACTOR_HOME"
    rsync -a --delete \
        --exclude='.venv' \
        --exclude='state/' \
        --exclude='__pycache__' \
        --exclude='.git' \
        --exclude='*.pyc' \
        "$REPO_ROOT/" "$COMPACTOR_HOME/"
fi

mkdir -p "$COMPACTOR_HOME/state"
success "Repo at $COMPACTOR_HOME"

# ── Step 3: Virtualenv + deps ─────────────────────────────────────────────────

VENV="$COMPACTOR_HOME/.venv"
info "Setting up virtualenv..."

[[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$COMPACTOR_HOME/requirements.txt"
success "Virtualenv ready ($("$VENV/bin/python" --version))"

# ── Step 4: Make scripts executable ──────────────────────────────────────────

chmod +x "$COMPACTOR_HOME/scripts/"*.sh 2>/dev/null || true
chmod +x "$COMPACTOR_HOME/.claude/hooks/"*.sh 2>/dev/null || true

# Copy hooks to a top-level scripts/hooks/ for global registration
HOOKS_DIR="$COMPACTOR_HOME/scripts/hooks"
mkdir -p "$HOOKS_DIR"
cp "$COMPACTOR_HOME/.claude/hooks/"*.sh "$HOOKS_DIR/"
chmod +x "$HOOKS_DIR/"*.sh
success "Hook scripts installed at $HOOKS_DIR"

# ── Step 5: Global MCP server registration ───────────────────────────────────

info "Registering global MCP server..."

json_merge "mcpServers" "$(cat <<JSON
{
  "prompt-compactor": {
    "command": "$VENV/bin/python",
    "args": ["-m", "src.server"],
    "cwd": "$COMPACTOR_HOME",
    "env": {
      "COMPACTOR_MODEL": "gemma4:e4b",
      "COMPACTOR_BASE_URL": "http://127.0.0.1:11434/v1"
    }
  }
}
JSON
)"

# ── Step 6: Global hooks registration ────────────────────────────────────────

info "Registering global hooks..."

# Hooks entry: each event gets one entry pointing to the global hook script.
# Claude Code merges hooks additively, so this is safe to re-run.
for EVENT_HOOK in \
    "SessionStart:$HOOKS_DIR/on-session-start.sh:false" \
    "UserPromptSubmit:$HOOKS_DIR/on-prompt.sh:false" \
    "PostToolUse:$HOOKS_DIR/on-edit.sh:true" \
    "Stop:$HOOKS_DIR/on-stop.sh:true"
do
    EVENT="${EVENT_HOOK%%:*}"
    REST="${EVENT_HOOK#*:}"
    SCRIPT="${REST%%:*}"
    ASYNC="${REST##*:}"

    MATCHER=""
    [[ "$EVENT" == "PostToolUse" ]] && MATCHER="Edit|MultiEdit|Write"

    ENTRY="[{\"matcher\": \"$MATCHER\", \"hooks\": [{\"type\": \"command\", \"command\": \"$SCRIPT\", \"async\": $ASYNC}]}]"
    json_merge "hooks" "{\"$EVENT\": $ENTRY}"
done

success "Hooks registered in $CLAUDE_SETTINGS"

# ── Step 7: launchd plists ────────────────────────────────────────────────────

install_plist() {
    local src="$1" label="$2"
    local dest="$LAUNCHD_DIR/$(basename "$src")"
    mkdir -p "$LAUNCHD_DIR"
    cp "$src" "$dest"
    launchctl unload "$dest" 2>/dev/null || true
    launchctl load "$dest"
    success "launchd: $label loaded"
}

info "Installing launchd services..."

OLLAMA_PLIST="$COMPACTOR_HOME/scripts/com.promptcompactor.server.plist"
DAEMON_PLIST="$COMPACTOR_HOME/scripts/com.promptcompactor.daemon.plist"

# Substitute placeholders in daemon plist with real paths
if [[ -f "$DAEMON_PLIST" ]]; then
    sed -i '' \
        -e "s|APFEL_VENV_PYTHON|$VENV/bin/python|g" \
        -e "s|COMPACTOR_HOME_PATH|$COMPACTOR_HOME|g" \
        "$DAEMON_PLIST"
fi

[[ -f "$OLLAMA_PLIST" ]] && install_plist "$OLLAMA_PLIST" "Ollama auto-start" \
    || warn "Ollama plist not found — skipping"

[[ -f "$DAEMON_PLIST" ]] && install_plist "$DAEMON_PLIST" "Hook daemon" \
    || warn "Daemon plist not found — skipping (daemon starts on first session)"

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "  ✓ PromptCompactor installed successfully!"
echo ""
echo "  Install root : $COMPACTOR_HOME"
echo "  MCP server   : registered globally in $CLAUDE_SETTINGS"
echo "  Hooks        : registered globally in $CLAUDE_SETTINGS"
echo "  State        : ~/.promptcompactor/projects/<hash>/state/  (isolated per project)"
echo ""
echo "  Next steps:"
echo "    1. ollama serve && ollama pull gemma4:e4b"
echo "    2. Restart Claude Code — PromptCompactor loads automatically in every project"
echo ""
echo "  To uninstall: $COMPACTOR_HOME/scripts/uninstall.sh"
