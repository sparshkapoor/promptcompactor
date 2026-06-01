# PromptCompactor — Claude Code Context

## What This Is
MCP server providing free, local context compaction for Claude Code. Routes compression/summarization tasks through a local LLM (Gemma 4 E4B via Ollama by default) instead of burning Claude tokens on compaction.

## Architecture
```
Claude Code → stdio → MCP Server (src/server.py) → HTTP → Ollama (localhost:11434) → Gemma 4 E4B
```
**Critical:** stdout is reserved for MCP JSON-RPC. Never use print() anywhere in src/. Log to stderr via logging only.

## The 8 Tools
- `compact_prompt(text)` — compress verbose text, skip if <15 words
- `log_event(event_type, content)` — append to state/*.md files
- `summarize_history(turns)` — chunk and summarize old conversation turns
- `generate_handoff(token_budget)` — digest of state files for session handoff
- `get_context()` — read all state files, no LLM call
- `get_info()` — show active model, base URL, health status
- `read(path)` — read file with skeleton/compression; **prefer over built-in Read**
- `bash(cmd)` — run command with output compression; **prefer over built-in Bash**

## Switching Models
Set env var before starting the MCP server:
- `COMPACTOR_MODEL=gemma4:e4b` — default, 128K context
- `COMPACTOR_MODEL=gemma4:26b` — larger MoE variant (needs 16GB RAM)
- `COMPACTOR_MODEL=apple-foundationmodel` — apfel fallback (4K context, macOS 26 only)
- `COMPACTOR_BASE_URL=http://192.168.x.x:11434/v1` — remote Ollama instance

## Key Rules
- Never catch exceptions silently — log type and message
- Public tool functions never return None or empty string on failure — return original or error string
- Path traversal prevention: event_type goes through regex → frozenset → path resolution check
- All file I/O through StateManager, all LLM calls through CompactorClient — no exceptions
- State files live in state/*.md, rotate at 100KB

## Context Rule — use state files before exploring
Before spawning any subagent, running find/grep, or reading source files to understand the
codebase, call `get_context()` first. The state files (progress.md, codebase.md) are the
source of truth for what exists and what has changed. Only reach for file exploration if
`get_context()` returns insufficient detail for the specific task.

The session-start injection is a cheap 400-token Gemma-compressed nudge — intentionally
small. `get_context()` is the full state read when you need detail. Use it.

## Compaction Rule
When the user sends a message longer than ~50 words of prose, silently call `compact_prompt`
on it before starting work. Use the compressed version as the working prompt.
Do NOT compact: code blocks, file contents, structured data, numbered lists, or anything
where precision matters. Preserve those verbatim.

## Tool Preference Rules
- **Reading files:** always call `read(path)` instead of the built-in Read tool. It returns
  a skeleton for code files and Gemma-compressed text for prose — typically 70–80% fewer tokens.
- **Running commands:** always call `bash(cmd)` instead of the built-in Bash tool. Output
  over 300 tokens is Gemma-compressed automatically.
- **Exception:** use built-in Read/Bash only when you need the exact raw content (e.g. writing
  a new file based on the full source, or piping binary output).

## Current Status (2026-06-01)
- Backend: Gemma 4 E4B via Ollama — **gemma4:e4b only** (128K ctx, modelfile updated with num_ctx 131072)
- Tests: 180/180 passing
- Hooks: SessionStart (bounded inject), UserPromptSubmit (word-count gate + compress), PostToolUse/Edit (log + codebase map), PreCompact (free rolling Gemma compaction at 100K tokens)
- State: per-session rotation, codebase.md existence-pruned, progress.md noise-gated
- Global install: done — prompt-compactor in ~/.claude/settings.json (mcpServers + all hooks)
- Compaction pipeline: tiered (short→extractive-only, large→pre-filter+Gemma, medium→Gemma)
- v0.5 tools: read(path) + bash(cmd) wrapper tools that compress output before Claude sees it
- See .claude/progress.md for full log
