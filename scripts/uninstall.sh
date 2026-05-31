#!/usr/bin/env bash
# uninstall.sh — Remove PromptCompactor global installation.
#
# What this does:
#   1. Removes the MCP server entry from ~/.claude/settings.json
#   2. Removes global hook entries from ~/.claude/settings.json
#   3. Unloads and removes launchd plists
#   4. Optionally removes ~/.promptcompactor (prompts first)
#
# Usage:
#   ./scripts/uninstall.sh
#   COMPACTOR_HOME=/opt/apfel ./scripts/uninstall.sh

set -euo pipefail

COMPACTOR_HOME="${COMPACTOR_HOME:-$HOME/.promptcompactor}"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
CLAUDE_JSON="$HOME/.claude.json"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

info()    { echo "  [compactor] $*"; }
success() { echo "  ✓ $*"; }
warn()    { echo "  ⚠ $*" >&2; }

PYTHON="$COMPACTOR_HOME/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

# Remove a named key from a dict section in a JSON settings file.
# Usage: json_remove <target_path> <section> <name>
json_remove() {
    local target="$1" section="$2" name="$3"
    "$PYTHON" - <<PYEOF
import json, sys
from pathlib import Path

p = Path("$target")
if not p.exists():
    sys.exit(0)

try:
    s = json.loads(p.read_text())
except (json.JSONDecodeError, OSError):
    sys.exit(0)

sec = s.get("$section", {})
if isinstance(sec, dict) and "$name" in sec:
    del sec["$name"]
    s["$section"] = sec
    p.write_text(json.dumps(s, indent=2) + "\n")
    print("  ✓ Removed $section/$name from $target")
else:
    print("  (not found: $section/$name in $target — nothing to remove)")
PYEOF
}

# Remove all hook entries pointing to COMPACTOR_HOME from settings.json
remove_hooks() {
    "$PYTHON" - <<PYEOF
import json, sys
from pathlib import Path

p = Path("$CLAUDE_SETTINGS")
if not p.exists():
    sys.exit(0)

try:
    s = json.loads(p.read_text())
except (json.JSONDecodeError, OSError):
    sys.exit(0)

apfel_home = "$COMPACTOR_HOME"
hooks = s.get("hooks", {})
changed = False

for event, entries in list(hooks.items()):
    filtered = []
    for entry in entries:
        new_hooks = [
            h for h in entry.get("hooks", [])
            if apfel_home not in h.get("command", "")
        ]
        if new_hooks:
            filtered.append({**entry, "hooks": new_hooks})
        else:
            changed = True
    if filtered != entries:
        changed = True
    hooks[event] = filtered

# Remove empty event keys
s["hooks"] = {k: v for k, v in hooks.items() if v}

if changed:
    p.write_text(json.dumps(s, indent=2) + "\n")
    print("  ✓ Removed apfel hooks from $CLAUDE_SETTINGS")
else:
    print("  (no apfel hooks found — nothing to remove)")
PYEOF
}

# ── Remove MCP registration ───────────────────────────────────────────────────

info "Removing MCP server registration..."
json_remove "$CLAUDE_SETTINGS" "mcpServers" "prompt-compactor"
json_remove "$CLAUDE_JSON" "mcpServers" "prompt-compactor"

# ── Remove global hooks ───────────────────────────────────────────────────────

info "Removing global hook entries..."
remove_hooks

# ── Unload launchd plists ─────────────────────────────────────────────────────

info "Unloading launchd services..."
for plist in com.promptcompactor.server.plist com.promptcompactor.daemon.plist; do
    dest="$LAUNCHD_DIR/$plist"
    if [[ -f "$dest" ]]; then
        launchctl unload "$dest" 2>/dev/null || true
        rm -f "$dest"
        success "Removed $plist"
    fi
done

# ── Optionally remove COMPACTOR_HOME ──────────────────────────────────────────────

echo ""
read -r -p "  Remove $COMPACTOR_HOME? This deletes all state data. [y/N] " answer
if [[ "${answer,,}" == "y" ]]; then
    rm -rf "$COMPACTOR_HOME"
    success "Removed $COMPACTOR_HOME"
else
    info "Keeping $COMPACTOR_HOME (state data preserved)"
fi

echo ""
echo "  ✓ PromptCompactor uninstalled."
echo "  Restart Claude Code to apply changes."
