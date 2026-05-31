# PromptCompactor — Project Plan

## What This Is
An MCP server that gives Claude Code a free, local context compaction layer. Instead of using expensive cloud models (Claude, Gemini, GPT) to compress context when the window fills up, this routes compaction tasks through Apple's on-device 3B LLM via apfel. Every call is free, instant, and fully local.

## Core Problem
Every AI coding agent wastes tokens on verbose prompts, stale tool outputs, and redundant conversation history. When context fills up, compaction currently requires cloud API calls that cost money. Nobody is doing this locally for free.

## System Requirements
- macOS 26 (Tahoe) or later — required by apfel
- Apple Silicon (arm64) — required for the Apple Neural Engine
- Python ≥ 3.10

## Architecture
```
Claude Code (200K context) → stdio → MCP Server (Python/FastMCP) → HTTP → Ollama (localhost:11434) → Gemma 4 E4B
```

Transport rule: MCP server uses stdio for Claude Code, HTTP for Ollama. Never mix them.

## The 7 Tools
1. **compact_prompt(text)** — compress verbose user text, ~70% token reduction
2. **log_event(type, content)** — classify and append to state files (progress/bug/decision/architecture)
3. **summarize_history(turns)** — compress old conversation turns, chunked for 128K window
4. **generate_handoff(token_budget)** — create session digest from state files; narrative is summarized adaptively, codebase map always verbatim
5. **get_context()** — read all state files, no LLM call
6. **set_model(model, base_url)** — switch model/backend at runtime without server restart
7. **get_info()** — return active model, base URL, and health status

## Key Constraints
- apfel context window: 4,096 tokens total (input + output + system prompt)
- Token budget per call: ~2,500 input tokens (after reserving for system prompt and response)
- System prompts must be under 80 words each
- apfel may silently block content via Apple's content filter — always have a fallback
- State files rotate at 100KB to prevent unbounded growth, keeping the newest half
- All inference on-device, $0 cost, no network calls except localhost

## Backend
**Only model: Gemma 4 E4B** via Ollama (`gemma4:e4b`, 128K context window, ~4–6 GB RAM on Apple Silicon).
- Ollama modelfile updated with `num_ctx 131072` — previously defaulted to 4096
- qwen2.5:1.5b evaluated and rejected: mangles structured data (rewrites ls/grep output to prose), disqualifying it as a context compressor
- Fallback: **apfel** (`apple-foundationmodel`, 4K context, requires macOS 26 Tahoe) — available but not actively used
- Switch via: `CompactorClient(model="apple-foundationmodel")` in `server.py` line 21

## Prompt Files (prompts/)
Four system prompt .txt files: `compress.txt`, `classify.txt`, `summarize.txt`, `file_summary.txt`, `verify.txt`.

## Current Status
- v0.4 — global install, tiered compression pipeline, extractive pre-filter, quality scoring
- Backend: Gemma 4 E4B via Ollama (128K ctx), configured via config.json
- Tests: 168/168 passing
- Installed globally: `~/.claude/settings.json` has `prompt-compactor` in mcpServers + all 4 hooks; launchd plists loaded
- Compaction pipeline: short prose (<300 tok) → extractive-only (no LLM); large prose (>500 tok) → TF-IDF pre-filter → Gemma; medium → Gemma only
- Quality check: `verify.txt` + `CompactorClient.verify()` — opt-in via `quality_check: true` in config.json
- bench.py: `--warmup` separates cold-start from TTFT from generation; streaming measures TTFT directly
- See .claude/progress.md for full log

## Known Issues (open)

**High priority:**
- `on-stop.sh` / Stop hook generates noise: every response turn logs "Turn completed" to progress.md; 47 of 148 entries are this string (32% noise). Dilutes injection quality and wastes Gemma's summarization budget. Fix: remove the Stop hook or make it conditional on meaningful state having changed.
- `state/progress.md` is at 19KB (~4877 tokens) well above the 400-token injection budget; `generate_handoff` always triggers Gemma on every session start. Removing Turn completed entries would halve the file.
- `update_file_summary()` has no rotation: `codebase.md` grows unboundedly (unlike progress/bug/etc which rotate at 100KB). Fix: after the write, check `codebase_file.stat().st_size > MAX_FILE_SIZE_BYTES` and drop the oldest entries.

**Medium priority:**
- Absolute paths in progress.md: `on-edit.sh` logs full absolute paths (e.g. `/Users/sparshkapoor/...`). Strip the repo-root prefix before storing so entries are portable across machines. Fix: in `cmd_log_edit()`, compute `path.resolve().relative_to(_REPO_ROOT)` before passing to `state.append()`.
- `_is_compressible()` 400-word ceiling skips the most valuable prompts. At 86 tok/s warm, a 400-word prompt compresses in ~2-3s well inside the 20s hook timeout. Raise to 1000 words or remove entirely.
- Python startup cost on every prompt: `on-prompt.sh` invokes Python unconditionally; for short prompts (~"yes", "ok") this adds ~0.3-0.5s per turn with no benefit. Add a shell-side word count pre-check: `[ "$(echo "$PROMPT" | wc -w)" -lt 40 ] && exit 0` before invoking Python.

**Low priority / hardening:**
- No integration test: all 105 tests mock the OpenAI client; the path FastMCP → CompactorClient → Ollama → response has never been exercised by a test. Add one integration test (skipped when Ollama is unreachable) that starts the server and calls a tool end-to-end.
- `health.py` uses module-level globals (`_last_check`, `_last_result`) for cache; this bleeds state between test modules if tests don't reload the module. Low risk but could cause intermittent failures.

## Known Issues (resolved)
- ~~`get_context()` docstring says "bugs.md, decisions.md"~~ — fixed in server.py
- ~~`generate_handoff` ignored token_budget when model healthy~~ — fixed in hook_runner.py `generate-handoff` command
- ~~Hardcoded token limits in CompactorClient and chunker~~ — now driven by config.json
- ~~generate_handoff lossy-summarized codebase.md together with narrative~~ — codebase now always verbatim via `read_codebase(max_entries=50)`
- ~~Hard 400-token compression floor caused 90% loss on large state files~~ — adaptive: `max(token_budget, estimated * 0.4)`
- ~~"5 Tools" in plan.md~~ — updated to 7 (set_model, get_info added in session 5)
- ~~Architecture diagram referenced `apfel --serve`~~ — corrected to Ollama
- ~~MCP server only registered per-project~~ — install.sh now does global registration
- ~~No integration test for health check cache ordering~~ — fixed test_integration.py cache reset
- ~~No tests for src/server.py MCP tools~~ — test_server.py covers all 7 tools (30 tests)

## Planned Enhancements
- Multi-project state isolation (already works via SHA256 hash in get_state_dir)
- Benchmark extractive pre-filter: run `tools/bench.py` before/after to quantify quality+speed gain
- Tune extractive `keep_ratio` (currently 0.6) based on benchmarks — may want 0.5 for longer inputs
- Enable `quality_check: true` in config.json and measure false-positive rate (how often verify wrongly rejects good compressions)
