# PromptCompactor

> Free, local context compaction for Claude Code — no API costs, no cloud calls, no telemetry

PromptCompactor is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that intercepts Claude Code's context management and routes summarization, compression, and event logging through a **local LLM** running on your machine. Instead of burning expensive Claude API tokens every time the context window fills up, PromptCompactor offloads that work to Gemma 4 E4B via Ollama — running entirely on-device at 86 tok/s on Apple Silicon.

---

## Why This Exists

Claude Code's built-in compaction calls the Claude API — costing tokens every time the context window fills up. For long coding sessions with large codebases, compaction can happen dozens of times. PromptCompactor replaces that with a free, local alternative that also attacks the other side of the problem: **what Claude reads**.

File reads land as 2500-token walls of code. Bash output lands as 1000-token walls of text. PromptCompactor adds `read` and `bash` wrapper tools that compress output before Claude ever sees it — skeleton-extracting code files and Gemma-compressing verbose command output automatically.

**Measured compaction results** (real benchmark, `gemma4:e4b`, `len//4` token estimate):

| Input type | Reduction | Latency |
|---|---|---|
| Session recap | −32% | 23.9s (cold) |
| Bug context | −26% | 4.1s (warm) |
| Code review | −15% | 11.9s (warm) |
| File-change logs | −2% | 5.1s (warm) |
| **Average** | **~19%** | |

> Cold-start latency is a one-time cost per session. The session-start hook pre-warms the model so subsequent calls are fast.

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) with `gemma4:e4b` pulled
- Claude Code (CLI or VSCode extension) with MCP support

> The benchmark numbers above are from Apple Silicon (M-series). Ollama runs on macOS, Linux, and Windows — performance varies by hardware. The launchd auto-start feature is macOS-only but optional.

---

## Quick Install

```bash
./scripts/install.sh
```

This is idempotent — safe to re-run after updates. It:

- Copies the repo to `~/.promptcompactor` and sets up a virtualenv
- Registers the MCP server globally in `~/.claude/settings.json` (CLI) and `~/.claude.json` (VSCode extension) using a shell wrapper that avoids `sys.path` conflicts with projects that have their own `src/` directory
- Registers all lifecycle hooks globally
- Patches `gemma4:e4b`'s context window to 131072 (Ollama defaults to 4096, which truncates compaction input silently)
- Optionally installs a launchd service to keep Ollama running in the background (macOS only)

## Manual Install

```bash
# Pull the model
ollama pull gemma4:e4b

# Patch the context window (critical — Ollama default is 4096)
ollama show gemma4:e4b --modelfile > /tmp/gemma4.modelfile
echo "PARAMETER num_ctx 131072" >> /tmp/gemma4.modelfile
ollama create gemma4:e4b -f /tmp/gemma4.modelfile

# Install dependencies
pip install -r requirements.txt

# Register with Claude Code (use shell wrapper to avoid src/ path conflicts)
claude mcp add prompt-compactor -- /bin/bash -c "cd ~/.promptcompactor && exec .venv/bin/python -m src.server"
```

## Verify

- **CLI:** run `/mcp` in a Claude Code terminal session — `prompt-compactor` should appear connected
- **VSCode extension:** open the MCP panel — `prompt-compactor` should appear alongside any claude.ai servers

Run `get_info` to confirm the backend is healthy and the correct model is active.

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `read(path)` | Read a file with automatic compression — code files are skeleton-extracted (signatures + docstrings, bodies dropped), prose files are Gemma-compressed. **Prefer over built-in Read.** |
| `bash(cmd)` | Run a shell command with automatic output compression — output over 300 tokens is Gemma-compressed. **Prefer over built-in Bash.** |
| `compact_prompt` | Compress a verbose prompt before sending to Claude. Skips code blocks, structured data, and anything under 15 words. |
| `log_event` | Append a development event (progress, bug, decision, architecture) to a rotating state file. |
| `summarize_history` | Chunk and summarize old conversation turns into a compact digest. |
| `generate_handoff` | Produce a session digest from all state files — used at session start to inject context without blowing the token budget. |
| `get_context` | Read all current state files verbatim (no LLM call). |
| `get_info` | Show the active model, base URL, and backend health status. |
| `set_model` | Hot-swap the active model at runtime without restarting the server. |

---

## Lifecycle Hooks

PromptCompactor ships five Claude Code lifecycle hooks that run automatically:

| Hook | Trigger | What it does |
|------|---------|--------------|
| `on-session-start.sh` | Session open | Pre-warms Gemma, generates a bounded handoff digest, injects it into the session context |
| `on-prompt.sh` | Every user message | Compresses verbose prose (>50 words, <40% code lines) before Claude sees it |
| `on-edit.sh` | Every file edit | Logs the changed path to `state/progress.md` and upserts a one-line Gemma summary into `state/codebase.md` |
| `on-stop.sh` | End of each turn | Records a progress marker — only on turns where files were actually edited |
| `on-precompact.sh` | Context hits `autoCompactWindow` | Replaces Claude's built-in compaction with a free local Gemma call via `generate_handoff`; falls back silently if Ollama is unavailable |

`autoCompactWindow` is set to 100,000 tokens (50% fill) so compaction fires more frequently with less to lose each pass, rather than at 95% as a last resort.

All hooks except `on-precompact.sh` are asynchronous and fire-and-forget — they never block Claude's response.

---

## Architecture

```
Claude Code (200K context)
    │
    │ stdio (JSON-RPC 2.0, MCP protocol)
    ▼
MCP Server  src/server.py  (Python, FastMCP)
    │
    ├── src/compactor_client.py   — all LLM calls, single HTTP client
    ├── src/state_manager.py      — all file I/O, rotating state files
    ├── src/code_extractor.py     — tree-sitter AST skeleton extraction
    ├── src/chunker.py            — splits large text into 128K-safe chunks
    ├── src/health.py             — cached backend health check (10s TTL)
    └── src/config.py             — config loader, env-var overrides
    │
    │ HTTP (OpenAI-compatible REST API)
    ▼
Ollama  localhost:11434
    │
    │ llama.cpp runtime
    ▼
Gemma 4 E4B  (128K context window patched, on-device)
```

State files live in `state/` and rotate at 100KB (newest half kept). The MCP server communicates with Claude Code on stdout (JSON-RPC only — `print()` anywhere in `src/` corrupts the protocol). All logging goes to stderr.

---

## Switching Models

Set environment variables before starting the MCP server:

```bash
# Default — 128K context, 86 tok/s on Apple Silicon
COMPACTOR_MODEL=gemma4:e4b

# Larger MoE variant — better quality, needs ~16GB RAM
COMPACTOR_MODEL=gemma4:26b

# Remote Ollama instance on another machine
COMPACTOR_BASE_URL=http://192.168.x.x:11434/v1

# Legacy fallback — macOS 26+ only, hard 4K context limit, not recommended
COMPACTOR_MODEL=apple-foundationmodel
```

Or use the `set_model` MCP tool to switch at runtime without restarting.

---

## State Files

| File | Contents |
|------|----------|
| `state/progress.md` | Timestamped log of edits, decisions, and session markers |
| `state/codebase.md` | One-line Gemma-generated summary per file, updated on every edit |
| `state/bug.md` | Bug reports logged via `log_event` |
| `state/decision.md` | Architecture decisions logged via `log_event` |

These files are the source of truth for session handoffs. `generate_handoff` reads them all and produces a token-bounded digest for injection at session start.

---

## Known Limitations

1. **Ollama required** — must be running locally (or remotely via `COMPACTOR_BASE_URL`)
2. **Context window must be patched** — `install.sh` handles this, but manual installs must run the `ollama create` step or compaction input will be silently truncated at 4096 tokens
3. **Token estimation is approximate** — uses `len // 4` heuristic, not the model's actual tokenizer (±20%)
4. **Structured data compresses poorly** — file-change logs and command output see ~2% reduction; the hook skips these automatically
5. **Cold-start latency** — first Gemma call after a cold Ollama takes ~24s; the session-start hook pre-warms it so subsequent calls are fast (~86 tok/s on M-series)
6. **Content filter** — Gemma occasionally refuses benign technical content; all tools return the original input as a fallback rather than failing
7. **English-centric** — struggles with non-English and mixed-language content

---

## License

MIT
