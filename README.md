# ApfelContext

> Free, local context compaction for Claude Code using Apple's on-device LLM

ApfelContext is an MCP server that routes context compaction through Apple's on-device 3B LLM via the open-source **apfel** tool. It compresses verbose prompts, summarizes conversation history, classifies and logs development events to state files, and generates session handoff digests. All LLM inference runs locally on Apple Silicon's Neural Engine at zero cost — no API keys, no cloud calls, no telemetry.

## Requirements

- Apple Silicon Mac (M1 or later)
- macOS 26 Tahoe or newer
- Apple Intelligence enabled (System Settings → Apple Intelligence & Siri)
- Python 3.10+
- Claude Code with MCP support
- apfel: `brew install Arthur-Ficial/tap/apfel`

## Quick Install

```bash
./scripts/install.sh
```

## Manual Install

```bash
pip install -r requirements.txt
apfel --serve &
claude mcp add apfel-context -- python -m src.server
```

## Verify

In Claude Code, run `/mcp` — you should see `apfel-context` listed as connected.

## Tools

| Tool | Description |
|------|-------------|
| `compact_prompt` | Compress a verbose prompt to reduce token usage before sending to Claude. |
| `log_event` | Log a development event (progress, bug, decision, architecture) to a state file. |
| `summarize_history` | Summarize older conversation turns into a compact format. |
| `generate_handoff` | Generate a session digest from all state files for use at the start of a new session. |
| `get_context` | Read all current project state files (no LLM call). |

## Architecture

```
Claude Code (200K context)
    │
    │ stdio (JSON-RPC 2.0, MCP protocol)
    ▼
MCP Server (Python, FastMCP)
    │
    │ HTTP (OpenAI-compatible REST API)
    ▼
apfel --serve (localhost:11434)
    │
    │ Apple FoundationModels.framework
    ▼
Apple Neural Engine (on-device 3B LLM)
```

## Known Limitations

1. **4,096 token hard limit** per apfel call (input + output combined)
2. **Content filter** occasionally blocks benign technical content (opaque, non-configurable)
3. **English-centric** — struggles with non-English and mixed-language content
4. **macOS 26+ only** — won't work on Sequoia or earlier
5. **No fine-tuning** — model is locked, you get what Apple ships
6. **Single model** — always `apple-foundationmodel`, no alternatives
7. **Token estimation is approximate** — uses 3.5 chars/token heuristic, not Apple's actual tokenizer

## License

MIT
