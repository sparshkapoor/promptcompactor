# Progress Log

## 2026-05-30 (session — global install + compaction experiments)
- [DONE] Fixed `json_merge` bug in install.sh (`'PYEOF'` → `PYEOF` so `$CLAUDE_SETTINGS` expands); ran installer — prompt-compactor now registered globally in `~/.claude/settings.json` with all 4 hooks
- [DONE] Fixed health cache poisoning in `test_integration.py::test_health_check_passes_with_ollama_running` — reset `_last_check/result` before the assertion; 168/168 tests passing
- [DONE] Experiment A: `src/extractor.py` — pure-Python TF-IDF extractive pre-filter (`pre_filter()`, `is_prose()`); no new dependencies
- [DONE] Experiment B: `prompts/verify.txt` + `CompactorClient.verify()` — Gemma-as-judge quality check; opt-in via `quality_check: true` in config.json; fail-open (returns True on LLM error)
- [DONE] Experiment C: tiered compression in `CompactorClient.compress()` — short prose (<300 tok) → extractive-only (no LLM); large prose (>500 tok) → TF-IDF pre-filter → Gemma; medium → Gemma only
- [DONE] Added `extractive_threshold: 500` and `quality_check: false` to config.json and config.py defaults
- [NOTE] Tiered extractive-only path requires ≥4 sentences to compress; falls through to Gemma otherwise (single-sentence inputs always go to Gemma)

## 2026-05-30 (session — README rewrite)
- [DONE] Rewrote README.md — added benchmark table, Why This Exists section, State Files table, expanded hooks and architecture sections, switching models, known limitations

## 2026-05-26 (session — blog post + benchmark)
- [DONE] Wrote `blog-post.html` for PromptCompactor — ~6 min read, structured as: TL;DR problems/fixes, The Problem, The Solution, The Tech, Does It Work?, What's Next
- [DONE] TL;DR section: 6 real build problems documented (stdout/MCP corruption, blocking hooks, daemon startup race, Gemma 2K context default, state file rotation, deleted-file injection)
- [DONE] Ran live compaction benchmark via Ollama API (gemma4:e4b) across 4 sample types; real results: session recap −32% (23.9s), bug context −26% (4.1s), code review −15% (11.9s), file changes −2% (5.1s); avg ~19%
- [DONE] Updated bar chart SVG with real measured token counts and per-group reduction labels; rescaled Y-axis to 200-token range
- [DONE] Updated line chart slope to reflect ~19% measured average (was incorrectly optimistic at ~68%)
- [DONE] Renamed all mentions of PromptCompactor → PromptCompactor throughout blog-post.html (title, h1, chart legend, chart title, repo URL)
- [NOTE] Token counting uses len//4 approximation — not tiktoken; numbers are soft ±20%
- [NOTE] Key benchmark finding: file change logs barely compress (structured data); session recap latency 24s suggests cold model — pre-warm at daemon startup would help
- [NOTE] Improvements identified: (1) tiktoken for accurate counts, (2) structured-data skip gate for file-change events, (3) model pre-warm to cut cold-start latency, (4) rerun benchmark on 1000+ token inputs

## 2026-04-15 (session 7 — audit + plan.md hardening)
- [DONE] Full codebase audit against real-world usability: 6 open issues identified and documented in plan.md
- [DONE] plan.md: corrected tool count (5→7), architecture diagram (apfel→Ollama), status (79→105 tests), added detailed Known Issues with fix guidance
- [NOTE] Top 3 issues by impact: (1) on-stop.sh Turn completed noise 32% of progress.md, (2) codebase.md has no rotation, (3) no integration test for the MCP path
- [NOTE] Model loading: Ollama lazy-loads on first call; OLLAMA_KEEP_ALIVE=-1 keeps resident; session-start warm-up curl makes it eager-warm in practice

## 2026-04-15 (session 6 — codebase map + algorithm/concurrency fixes)
- [DONE] `prompts/file_summary.txt` + `CompactorClient.summarize_file()` — one-line file description
- [DONE] `StateManager.update_file_summary(path, summary)` — upserts into state/codebase.md
- [DONE] `hook_runner.py update-file-summary` command + on-edit.sh second async call
- [DONE] Python file preview: first 60 lines + all class/def signatures (streaming, no full load); 5MB size gate
- [DONE] File locking: `StateManager._locked()` using fcntl.flock + sidecar .lock file — covers append(), update_file_summary(), and _rotate() TOCTOU
- [DONE] Token estimate consistency: `CHARS_PER_TOKEN = 4` now single source of truth in chunker.py, imported by server.py and hook_runner.py (was inconsistent 3.5 vs 4)
- [DONE] Wired `compact_on_every_prompt` config key in cmd_compress_prompt() — true = skip _is_compressible() heuristic, compress everything
- [DONE] compress-prompt devlog: logs compression events to state/progress.md when `log_prompt_compression: true`
- [DONE] Fixed set_model()/get_info() — removed redundant local DEFAULT_BASE_URL imports; added 4 tests; 94/94 passing
- [DONE] generate_handoff: `StateManager.read_narrative()` / `read_codebase(max_entries=50)` — codebase map is now verbatim-truncated (never summarized); narrative is summarized separately
- [DONE] Adaptive compression budget: `target_tokens = max(token_budget, int(estimated * 0.4))` — prevents 90%+ loss on large state files; applied in both server.py and hook_runner.py
- [DONE] `CompactorClient.summarize(max_tokens=RESPONSE_BUDGET)` — added optional param so callers can set the LLM response cap per-call
- [DONE] 105/105 tests passing (added 11 new tests: 3 read_narrative, 6 read_codebase, 3 generate_handoff)
- [NOTE] state/progress.md is 3966 tokens vs 400-token injection budget — generate_handoff always triggers Gemma summarization at session start

## 2026-04-15 (session 6 — per-file codebase summaries)
- [DONE] Deleted `prompts/extract.txt` — decided not to implement extract(); use case covered by compress() and Claude's natural log conciseness
- [DONE] Added `prompts/file_summary.txt` — one-sentence file description prompt
- [DONE] Added `CompactorClient.summarize_file(content)` — calls file_summary prompt, returns first line or empty string on failure
- [DONE] Added `StateManager.update_file_summary(path, summary)` — upserts `- \`path\`: summary` line in state/codebase.md
- [DONE] Updated `StateManager.read_all()` — includes codebase.md section in output
- [DONE] Added `hook_runner.py update-file-summary <filepath>` command — reads file, calls summarize_file, upserts into codebase map; skips state/, binaries, empty files, unhealthy backend
- [DONE] Updated `.claude/hooks/on-edit.sh` — second fire-and-forget call to update-file-summary alongside existing log-edit
- [DONE] Fixed test_compactor_client.py fixture: replaced extract with file_summary in prompt file setup
- [DONE] Added 11 new tests (4 for summarize_file, 7 for update_file_summary/read_all) — 90/90 passing

## 2026-04-15 (session 6 — extract.txt cleanup)
- [DONE] Deleted `prompts/extract.txt` — decided not to implement `CompactorClient.extract()`; use case covered by `compress()` + Claude's natural log conciseness; no MCP tool added
- [DONE] Updated plan.md: removed extract from Known Issues and Planned Enhancements, updated prompt file list to 3 files

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
- [NOTE] bench.py now imports openai directly for streaming; CompactorClient still used for non-streaming paths

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
- [FIXED] `check_compactor_health()` called without URL in all hook_runner commands → `_is_healthy()` helper derives `scheme://host:port` from config
- [FIXED] `on-edit.sh` hardcoded `python3` for JSON parsing → uses `$PYTHON` (.venv) consistently
- [VERIFIED] `compress-prompt` smoke-tested: 62→29 tokens (-53%) on verbose prose, correctly skips code blocks
- [VERIFIED] Session injection: 471 tokens (was 599 raw) with `generate-handoff`
- [VERIFIED] 79/79 tests passing throughout
- [PENDING] Implement `CompactorClient.extract()` or delete `extract.txt`

## 2026-04-11 (session 3 — automation pipeline)
- [DONE] Created `config.json` at project root — backend, automation flags, token budget all configurable
- [DONE] Created `src/config.py` — shared config loader with env-var override priority (APFEL_MODEL, APFEL_BASE_URL)
- [DONE] Updated `src/compactor_client.py` — DEFAULT_MODEL, DEFAULT_BASE_URL, MAX_INPUT_TOKENS now driven by config
- [DONE] Updated `src/chunker.py` — chunk_text() default max_tokens now from get_max_input_tokens() (currently 126400 for Gemma 4 E4B)
- [DONE] Created `scripts/hook_runner.py` — CLI called by hooks; reuses src/ modules; inject-context, log-edit, log-progress, summarize-turn commands
- [DONE] Created `.claude/hooks/on-session-start.sh` — synchronous; injects state into Claude context on session open
- [DONE] Created `.claude/hooks/on-edit.sh` — async; logs file edits to progress.md (with LLM summary when healthy)
- [DONE] Created `.claude/hooks/on-stop.sh` — async; logs "Turn completed" marker to progress.md
- [DONE] Created `.claude/settings.json` — registers all three hooks with correct sync/async settings
- [DONE] Created `scripts/com.promptcompactor.server.plist` — launchd plist for auto-starting Ollama on login
- [DONE] Updated `scripts/install.sh` — added chmod hook scripts + optional launchd install steps
- [DONE] Fixed 2 tests that had hardcoded old token values; all 79/79 passing
- [DONE] Added tiktoken to requirements.txt + pyproject.toml (from session 2 tool work)
- [DONE] Created `tools/bench.py` — token count + compression benchmark with latency and tok/s table
- [VERIFIED] All hooks smoke-tested: on-session-start injects state, on-edit logs filepath+LLM summary, on-stop logs turn marker
- [NOTE] on-edit LLM summary falls back gracefully to bare filepath when backend is slow/unreachable (async, never blocks Claude)
- [NOTE] Race condition on concurrent state file writes: append-mode OS atomicity safe for entries under PIPE_BUF (~4096 bytes on macOS)

## 2026-04-08 (session 2)
- [DONE] Swapped backend from apfel (apple-foundationmodel, 4K ctx) to Gemma 4 E4B via Ollama (gemma4:e4b, 128K ctx)
- [DONE] Made model configurable via CompactorClient(model=...) — DEFAULT_MODEL = "gemma4:e4b", fallback "apple-foundationmodel"
- [DONE] Updated MAX_INPUT_TOKENS 2500→100_000, RESPONSE_BUDGET 1000→2000, MAX_INPUT_CHARS now 400_000
- [DONE] Extracted named constants: DEFAULT_TEMPERATURE, DEFAULT_MAX_RETRIES, SUMMARY_FALLBACK_CHARS
- [DONE] Fixed summarize_history returning "" on blank input — now returns error string (IAC violation fixed)
- [DONE] Added regression tests: DEFAULT_MODEL, MAX_INPUT_TOKENS, model param flows to API, fallback model
- [DONE] Fixed test asserting old "" return from summarize_history
- [DONE] 79/79 tests passing
- [RESOLVED] extract.txt unused — still unimplemented, tracked below
- [PENDING] Implement CompactorClient.extract() or delete extract.txt
- [PENDING] generate_handoff ignores token_budget param when model is available (design bug, not crash)

## 2026-04-08 (session 1)
- [INIT] Repository scaffolded by GitHub Copilot coding agent
- [INIT] Core files: server.py, compactor_client.py, state_manager.py, chunker.py, health.py
- [INIT] System prompts created: compress.txt, classify.txt, summarize.txt, extract.txt
- [INIT] Install and start scripts created
- [INIT] .claude/ folder created with plan, instructions, and progress files
- [AUDIT] Code audit of Copilot-generated files complete — see Known Copilot-Generated Issues in plan.md
- [PENDING] Comprehensive test suite not yet written (existing tests cover happy paths and some edge cases)
- [PENDING] Real-world testing with apfel + Claude Code not yet done
- [PENDING] extract.txt prompt has no corresponding CompactorClient.extract() method — unused
- [PENDING] generate_handoff does not chunk large state before passing to apfel — potential silent truncation
- [PENDING] get_context() docstring says "bugs.md, decisions.md" — should be "bug.md", "decision.md"
