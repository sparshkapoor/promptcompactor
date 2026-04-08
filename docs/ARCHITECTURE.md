# Architecture

## Why HTTP, Not CLI Pipes

The MCP server communicates with Claude Code over **stdio** (stdin/stdout) using JSON-RPC 2.0. If the MCP server also called apfel via subprocess stdin/stdout pipes, the two stdio streams would collide and corrupt the JSON-RPC protocol.

The solution: run apfel as a persistent HTTP daemon (`apfel --serve`) and call it via the OpenAI Python SDK over HTTP. These are completely separate transports with no interference.

## Token Budget Math

apfel has a 4,096-token context window shared by input and output:

```
4096 total
 - 300  system prompt
 - 1000 model response
 - 300  safety margin
= 2500 tokens available for user input
```

`chunk_text()` uses a conservative 3.5 chars/token estimate (slightly under 4) to stay within this budget. Input that would exceed the limit is split across multiple chunks, each summarized independently, and results concatenated.

## Fallback Strategies

Every tool has a graceful degradation path when apfel is unavailable:

| Tool | Fallback |
|------|----------|
| `compact_prompt` | Returns original text unchanged |
| `log_event(auto)` | Defaults event type to `progress` |
| `summarize_history` | Truncates to 2000 chars + marker |
| `generate_handoff` | Truncates to `token_budget * 4` chars + marker |

## State File Rotation

Each state file (`progress.md`, `bug.md`, `decision.md`, `architecture.md`) caps at 100 KB. When a file exceeds this limit, the oldest half of entries is discarded to prevent unbounded growth. This is a lossy operation — old entries are intentionally pruned. Use `generate_handoff` before rotation occurs to preserve important history.

## Health Check Caching

`check_apfel_health()` caches its result for 10 seconds (`CACHE_SECONDS`). This prevents hammering the `/health` endpoint on every tool invocation during a busy session. The cache is module-level and resets on process restart.

## Security Model

- State file types are validated against a strict allowlist (`progress`, `bug`, `decision`, `architecture`)
- Path traversal is blocked: resolved paths are verified to remain inside `state/`
- Null bytes are stripped from all written content
- Content is capped at 5,000 chars per entry
- All inference is on-device; no data leaves the machine
- No authentication on the MCP server (it runs as the local user's process)
