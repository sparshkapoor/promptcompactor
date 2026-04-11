# Progress Log

## 2026-04-11 (session 5 — continued: gemma4 warm-up pipeline)
- [DONE] Added `OLLAMA_KEEP_ALIVE=-1` to launchd plist — model stays in VRAM indefinitely after first load
- [DONE] Added fire-and-forget warm-up curl to `on-session-start.sh` — loads gemma in background in parallel with generate-handoff
- [DONE] Reloaded launchd plist, verified `OLLAMA_KEEP_ALIVE` active on Ollama process via `launchctl print`
- [NOTE] plist validated with `plutil -lint` before reload

## 2026-04-11 (session 5 — bench.py warmup + TTFT + gemma4 context fix)
- [DONE] Added `--warmup` flag to `tools/bench.py` — fires 1-token dummy call per model, reports cold-start ms separately from TTFT and pure generation ms
- [DONE] Switched bench.py to streaming completions — TTFT measured as wall-clock time to first content chunk
- [DONE] Fixed gemma4:e4b context window — Ollama was defaulting to 4096; recreated modelfile with `num_ctx 131072` (matches model's native 128K)
- [VERIFIED] Cold-start was the source of apparent slowness: gemma4:e4b is 86 tok/s warm (vs 45 for qwen2.5:1.5b)
- [DECIDED] gemma4:e4b only — qwen2.5:1.5b mangles structured data (converts ls/grep output to prose bullets), disqualifying it as a context compressor
- [NOTE] bench.py now imports openai directly for streaming; ApfelClient still used for non-streaming paths

## 2026-04-11 (session 4 — hook hardening + UserPromptSubmit)
- [DONE] Fixed `.mcp.json` — `"python3 "` trailing space was preventing MCP server from starting
- [DONE] Updated `.mcp.json` command to absolute `.venv/bin/python` path (env-independent)
- [DONE] Added `UserPromptSubmit` hook: `on-prompt.sh` → `compress-prompt` in hook_runner.py
- [DONE] `compress-prompt`: reads prompt JSON from stdin, skips code/structured data, outputs compressed version + instruction for Claude
- [DONE] `_is_compressible()`: 50-word threshold + code-line ratio heuristic (>40% = skip)
- [DONE] Added `max_injection_tokens: 400` to config.json + src/config.py defaults
- [DONE] Added `generate-handoff` command to hook_runner.py — bounded injection, summarizes via Gemma if over budget
- [DONE] Switched `on-session-start.sh` from `inject-context` to `generate-handoff` — O(1) context cost regardless of state file size
- [DONE] Updated CLAUDE.md — compaction rule with explicit do-not-compact list (code blocks, structured data, numbered lists)
- [FIXED] `compress-prompt` empty-prompt bug: `data.get("prompt","") or raw` → early return if prompt key missing/empty
- [FIXED] `_is_compressible` false positives: `"{"` / `"["` matched mid-sentence prose → startswith-only with `"{ "` / `"[ "`
- [FIXED] `check_apfel_health()` called without URL in all hook_runner commands → `_is_healthy()` helper derives `scheme://host:port` from config
- [FIXED] `on-edit.sh` hardcoded `python3` for JSON parsing → uses `$PYTHON` (.venv) consistently
- [VERIFIED] `compress-prompt` smoke-tested: 62→29 tokens (-53%) on verbose prose, correctly skips code blocks
- [VERIFIED] Session injection: 471 tokens (was 599 raw) with `generate-handoff`
- [VERIFIED] 79/79 tests passing throughout
- [PENDING] Implement `ApfelClient.extract()` or delete `extract.txt`

## 2026-04-11 (session 3 — automation pipeline)
- [DONE] Created `config.json` at project root — backend, automation flags, token budget all configurable
- [DONE] Created `src/config.py` — shared config loader with env-var override priority (APFEL_MODEL, APFEL_BASE_URL)
- [DONE] Updated `src/apfel_client.py` — DEFAULT_MODEL, DEFAULT_BASE_URL, MAX_INPUT_TOKENS now driven by config
- [DONE] Updated `src/chunker.py` — chunk_text() default max_tokens now from get_max_input_tokens() (currently 126400 for Gemma 4 E4B)
- [DONE] Created `scripts/hook_runner.py` — CLI called by hooks; reuses src/ modules; inject-context, log-edit, log-progress, summarize-turn commands
- [DONE] Created `.claude/hooks/on-session-start.sh` — synchronous; injects state into Claude context on session open
- [DONE] Created `.claude/hooks/on-edit.sh` — async; logs file edits to progress.md (with LLM summary when healthy)
- [DONE] Created `.claude/hooks/on-stop.sh` — async; logs "Turn completed" marker to progress.md
- [DONE] Created `.claude/settings.json` — registers all three hooks with correct sync/async settings
- [DONE] Created `scripts/com.apfel-context.server.plist` — launchd plist for auto-starting Ollama on login
- [DONE] Updated `scripts/install.sh` — added chmod hook scripts + optional launchd install steps
- [DONE] Fixed 2 tests that had hardcoded old token values; all 79/79 passing
- [DONE] Added tiktoken to requirements.txt + pyproject.toml (from session 2 tool work)
- [DONE] Created `tools/bench.py` — token count + compression benchmark with latency and tok/s table
- [VERIFIED] All hooks smoke-tested: on-session-start injects state, on-edit logs filepath+LLM summary, on-stop logs turn marker
- [NOTE] on-edit LLM summary falls back gracefully to bare filepath when backend is slow/unreachable (async, never blocks Claude)
- [NOTE] Race condition on concurrent state file writes: append-mode OS atomicity safe for entries under PIPE_BUF (~4096 bytes on macOS)

## 2026-04-08 (session 2)
- [DONE] Swapped backend from apfel (apple-foundationmodel, 4K ctx) to Gemma 4 E4B via Ollama (gemma4:e4b, 128K ctx)
- [DONE] Made model configurable via ApfelClient(model=...) — DEFAULT_MODEL = "gemma4:e4b", fallback "apple-foundationmodel"
- [DONE] Updated MAX_INPUT_TOKENS 2500→100_000, RESPONSE_BUDGET 1000→2000, MAX_INPUT_CHARS now 400_000
- [DONE] Extracted named constants: DEFAULT_TEMPERATURE, DEFAULT_MAX_RETRIES, SUMMARY_FALLBACK_CHARS
- [DONE] Fixed summarize_history returning "" on blank input — now returns error string (IAC violation fixed)
- [DONE] Added regression tests: DEFAULT_MODEL, MAX_INPUT_TOKENS, model param flows to API, fallback model
- [DONE] Fixed test asserting old "" return from summarize_history
- [DONE] 79/79 tests passing
- [RESOLVED] extract.txt unused — still unimplemented, tracked below
- [PENDING] Implement ApfelClient.extract() or delete extract.txt
- [PENDING] generate_handoff ignores token_budget param when model is available (design bug, not crash)

## 2026-04-08 (session 1)
- [INIT] Repository scaffolded by GitHub Copilot coding agent
- [INIT] Core files: server.py, apfel_client.py, state_manager.py, chunker.py, health.py
- [INIT] System prompts created: compress.txt, classify.txt, summarize.txt, extract.txt
- [INIT] Install and start scripts created
- [INIT] .claude/ folder created with plan, instructions, and progress files
- [AUDIT] Code audit of Copilot-generated files complete — see Known Copilot-Generated Issues in plan.md
- [PENDING] Comprehensive test suite not yet written (existing tests cover happy paths and some edge cases)
- [PENDING] Real-world testing with apfel + Claude Code not yet done
- [PENDING] extract.txt prompt has no corresponding ApfelClient.extract() method — unused
- [PENDING] generate_handoff does not chunk large state before passing to apfel — potential silent truncation
- [PENDING] get_context() docstring says "bugs.md, decisions.md" — should be "bug.md", "decision.md"
