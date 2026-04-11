# Instructions for LLMs Working on This Project

## Code Standards

### Session Hygiene
- Always update `.claude/progress.md` with a session log entry **before** any `git commit` or `git push`. Never commit without it.

### DO
- Log all errors to stderr using the `logging` module, never print()
- Return the original input as fallback when apfel calls fail — never return empty strings or None from public tool functions. **Exception:** `summarize_history` intentionally truncates to 2000 chars (+ marker) when apfel is unavailable, because returning a potentially massive history verbatim isn't useful.
- Validate all user-supplied strings before using them in file paths
- Keep system prompt files (prompts/*.txt) under 80 words — they eat into the 4,096 token budget
- Use type hints on all function signatures
- Write docstrings that accurately describe what the function actually does, including failure modes
- Test edge cases: empty input, None, extremely long input, Unicode, concurrent access
- Check apfel health before making LLM calls — use the cached health check, don't hit the endpoint directly

### DO NOT
- Never use print() or sys.stdout.write() anywhere in src/ — stdout is reserved for MCP JSON-RPC protocol. This will corrupt communication with Claude Code.
- Never catch broad exceptions silently. If you catch Exception, you must log it with the exception type and message.
- Never construct file paths from unsanitized user input. Always go through StateManager._validate_type() and _get_path().
- Never hardcode the apfel URL outside of ApfelClient.__init__. It should be configurable from one place.
- Never make real HTTP calls in tests. Mock the OpenAI client.
- Never assume apfel is running. Every tool function must handle the apfel-down case gracefully.
- Never import from the prompts/ files at module level. Load them at call time so missing files are caught per-call, not at server startup.
- Never add dependencies without updating both requirements.txt and pyproject.toml.
- Never write to files outside the state/ directory from any code path.

### Security Rules
- Path traversal: event_type is sanitized via regex to [a-z] only, then checked against VALID_TYPES frozenset, then the resolved path is verified to be inside state_dir. All three checks must remain.
- Null bytes: stripped from content before any file write.
- Content length: capped at 5,000 chars per state file entry.
- File size: state files rotate at 100KB, keeping the newest half.
- No authentication on the MCP server — it runs locally as the user's process. Do not add auth unless the architecture changes.

### Testing Rules
- All tests must pass without apfel running (mock all HTTP calls)
- Use pytest with fixtures, not unittest
- Use tmp_path fixture for any test that touches the filesystem
- Reset health check cache before health-related tests by setting **both** `src.health._last_check = 0.0` and `src.health._last_result = False` (the existing `reset_cache()` helper in test_health.py does this correctly)
- Security test cases (path traversal, null bytes, oversized content) are mandatory — do not delete them

### Architecture Rules
- The MCP server communicates with Claude Code via stdio and with apfel via HTTP. These are separate transports. Do not attempt to call apfel CLI via subprocess stdin/stdout from within the MCP server — it will corrupt the JSON-RPC protocol.
- ApfelClient is the single point of contact for apfel. All LLM calls go through it. Do not create additional OpenAI client instances elsewhere.
- StateManager is the single point of contact for filesystem state. All file reads/writes go through it. Do not use open() directly for state files elsewhere.
- The health check module caches results for 10 seconds. Do not bypass the cache or add per-call health checks.

### When Reviewing Copilot-Generated Code
This repo was initially built by GitHub Copilot's coding agent. Watch for these patterns (some already confirmed present):
- **Known issue:** `get_context()` docstring (server.py) says "bugs.md, decisions.md" — actual files are `bug.md` and `decision.md`. Runtime is correct; docstring is wrong.
- **Known issue:** `extract.txt` prompt file exists with no corresponding `ApfelClient.extract()` method — unused dead code.
- **Known issue:** `generate_handoff` does not chunk large state before calling `_apfel.summarize()` — for very large state, apfel will silently truncate internally rather than summarize all of it.
- Imports that reference nonexistent modules or methods
- Functions defined but never called
- Docstrings that don't match the implementation
- Return type hints that miss edge case return values (e.g., says str but can return None)
- Nearly-identical code blocks with subtle inconsistencies
- Hardcoded values that look reasonable but aren't validated against actual constraints
