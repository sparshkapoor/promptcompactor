# ApfelContext — Claude Code Context

## What This Is
MCP server providing free, local context compaction for Claude Code. Routes compression/summarization tasks through a local LLM (Gemma 4 E4B via Ollama by default) instead of burning Claude tokens on compaction.

## Architecture
```
Claude Code → stdio → MCP Server (src/server.py) → HTTP → Ollama (localhost:11434) → Gemma 4 E4B
```
**Critical:** stdout is reserved for MCP JSON-RPC. Never use print() anywhere in src/. Log to stderr via logging only.

## The 6 Tools
- `compact_prompt(text)` — compress verbose text, skip if <15 words
- `log_event(event_type, content)` — append to state/*.md files
- `summarize_history(turns)` — chunk and summarize old conversation turns
- `generate_handoff(token_budget)` — digest of state files for session handoff
- `get_context()` — read all state files, no LLM call
- `get_info()` — show active model, base URL, health status

## Switching Models
Set env var before starting the MCP server:
- `APFEL_MODEL=gemma4:e4b` — default, 128K context
- `APFEL_MODEL=gemma4:26b` — larger MoE variant (needs 16GB RAM)
- `APFEL_MODEL=apple-foundationmodel` — apfel fallback (4K context, macOS 26 only)
- `APFEL_BASE_URL=http://192.168.x.x:11434/v1` — remote Ollama instance

## Key Rules
- Never catch exceptions silently — log type and message
- Public tool functions never return None or empty string on failure — return original or error string
- Path traversal prevention: event_type goes through regex → frozenset → path resolution check
- All file I/O through StateManager, all LLM calls through ApfelClient — no exceptions
- State files live in state/*.md, rotate at 100KB

## Compaction Rule
When the user sends a message longer than ~50 words of prose, silently call `compact_prompt`
on it before starting work. Use the compressed version as the working prompt.
Do NOT compact: code blocks, file contents, structured data, numbered lists, or anything
where precision matters. Preserve those verbatim.

## Current Status (2026-04-11)
- Backend: Gemma 4 E4B via Ollama — **gemma4:e4b only** (128K ctx, modelfile updated with num_ctx 131072)
- qwen2.5:1.5b evaluated and rejected: mangles structured data, unacceptable for context compaction
- Tests: 79/79 passing
- Hooks active: SessionStart injects bounded state digest, PostToolUse logs edits, Stop logs turn marker
- bench.py: `--warmup` flag separates cold-start / TTFT / generation; uses streaming for TTFT measurement
- Pending: implement ApfelClient.extract() or delete extract.txt
- See .claude/progress.md for full log
