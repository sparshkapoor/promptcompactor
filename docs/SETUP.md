# Setup Guide

Step-by-step instructions to get PromptCompactor running on a fresh Mac.

## Prerequisites

1. **Apple Silicon Mac** (M1, M2, M3, or M4)
2. **macOS 26 Tahoe or newer** — check with `sw_vers -productVersion`
3. **Apple Intelligence enabled** — System Settings → Apple Intelligence & Siri → enable
4. **Python 3.10+** — check with `python3 --version`; install via `brew install python` if needed
5. **Homebrew** — install from [brew.sh](https://brew.sh) if missing
6. **Claude Code** — install from [claude.ai/code](https://claude.ai/code)

## Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/prompt-compactor
   cd prompt-compactor
   ```

2. **Install apfel**
   ```bash
   brew install Arthur-Ficial/tap/apfel
   ```

3. **Verify apfel works**
   ```bash
   apfel --version
   ```

4. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Create the state directory**
   ```bash
   mkdir -p state && touch state/.gitkeep
   ```

6. **Start the apfel server**
   ```bash
   apfel --serve &
   ```

7. **Verify apfel health**
   ```bash
   curl http://localhost:11434/health
   # Expected: HTTP 200
   ```

8. **Register the MCP server with Claude Code**
   ```bash
   claude mcp add --scope project prompt-compactor -- python -m src.server
   ```

9. **Restart Claude Code** to load the new MCP server.

10. **Verify the connection**
    In Claude Code, type `/mcp` — you should see `prompt-compactor` listed as connected with 5 tools.

## Keeping apfel Running

To have apfel start automatically at login:

```bash
# Add to ~/.zshrc or ~/.bash_profile
apfel --serve &> /dev/null &
```

Or use the provided start script which handles "already running" gracefully:

```bash
./scripts/start.sh
```

## Troubleshooting

- **`apfel: command not found`** — re-run `brew install Arthur-Ficial/tap/apfel`
- **Health check returns 503** — Apple Intelligence may not be fully initialised; wait 30 seconds and retry
- **MCP server not appearing in `/mcp`** — ensure you restarted Claude Code after running `claude mcp add`
- **Content filter blocks** — apfel's content filter is non-configurable; retry with slightly rephrased input
