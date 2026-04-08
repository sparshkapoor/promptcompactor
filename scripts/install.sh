#!/bin/bash
set -e

echo "=== ApfelContext Setup ==="

# 1. Check macOS version
SW_VER=$(sw_vers -productVersion | cut -d. -f1)
if [ "$SW_VER" -lt 26 ]; then
    echo "Error: macOS 26 (Tahoe) or later required. You have: $(sw_vers -productVersion)"
    exit 1
fi

# 2. Check Apple Silicon
ARCH=$(uname -m)
if [ "$ARCH" != "arm64" ]; then
    echo "Error: Apple Silicon (arm64) required. You have: $ARCH"
    exit 1
fi

# 3. Install apfel
if ! command -v apfel &> /dev/null; then
    echo "Installing apfel..."
    brew install Arthur-Ficial/tap/apfel
else
    echo "apfel already installed: $(apfel --version 2>/dev/null || echo 'unknown version')"
fi

# 4. Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# 5. Create state directory
mkdir -p state
touch state/.gitkeep

# 6. Start apfel
./scripts/start.sh

# 7. Register MCP server with Claude Code
echo "Registering MCP server with Claude Code..."
if command -v claude &> /dev/null; then
    claude mcp add --scope project apfel-context -- python -m src.server
    echo "MCP server registered. Restart Claude Code, then run /mcp to verify."
else
    echo "Warning: claude CLI not found. Register manually:"
    echo "  claude mcp add apfel-context -- python -m src.server"
fi

echo ""
echo "=== Setup complete ==="
echo "1. Restart Claude Code"
echo "2. Run /mcp to verify apfel-context is connected"
echo "3. Try: ask Claude Code to use compact_prompt on a verbose message"
