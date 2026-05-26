#!/usr/bin/env python3
"""
hook_runner.py — CLI entry point called by Claude Code lifecycle hooks.

Hooks run in their own shell process, completely separate from the MCP server.
This script reuses the same src/ modules (CompactorClient, StateManager, health)
so there's no logic duplication.

IMPORTANT: stdout is reserved for hook output that Claude Code reads.
           All logging must go to stderr.

Usage:
  python scripts/hook_runner.py inject-context           # Read state files raw, output to stdout
  python scripts/hook_runner.py generate-handoff         # Bounded digest (summarizes if over max_injection_tokens)
  python scripts/hook_runner.py compress-prompt          # Read prompt JSON from stdin, inject compressed version
  python scripts/hook_runner.py log-edit <filepath>
  python scripts/hook_runner.py update-file-summary <filepath>
  python scripts/hook_runner.py log-progress <message>
  python scripts/hook_runner.py summarize-turn

Exit codes:
  0 — success (always; hooks must not block Claude)
"""

import io
import logging
import sys
import threading

from pathlib import Path

# ── path setup: allow importing from src/ without installing the package ─────
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ── logging to stderr only — stdout is for Claude Code to read ───────────────
logging.basicConfig(
    stream=sys.stderr,
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] hook_runner: %(message)s",
)
logger = logging.getLogger("hook_runner")

from src.config import get_backend_config, get_automation_config, get_state_dir  # noqa: E402
from src.chunker import CHARS_PER_TOKEN                           # noqa: E402
from src.compactor_client import CompactorClient                           # noqa: E402
from src.state_manager import StateManager                         # noqa: E402
from src.health import check_compactor_health                          # noqa: E402

_DAEMON_PORT = 7737
_capture_lock = threading.Lock()


def _make_client() -> CompactorClient:
    """
    Short timeout + no retries so all hook LLM calls complete well under
    Claude Code's 20s hook timeout. Hooks must never block Claude.
    """
    cfg = get_backend_config()
    client = CompactorClient(base_url=cfg["base_url"], model=cfg["model"], timeout=8.0)
    # Override SDK-level retries: one attempt only, fail fast to fallback
    from openai import OpenAI
    client.client = OpenAI(
        base_url=cfg["base_url"],
        api_key="unused",
        timeout=8.0,
        max_retries=0,
    )
    return client


def _make_state() -> StateManager:
    return StateManager(state_dir=get_state_dir())


def _health_base_url() -> str:
    """Derive scheme://host:port from config base_url (strips /v1 path)."""
    from urllib.parse import urlparse
    parsed = urlparse(get_backend_config()["base_url"])
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_healthy() -> bool:
    return check_compactor_health(_health_base_url())


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_inject_context() -> None:
    """
    Read all state files raw and print to stdout.
    Unbounded — use generate-handoff for large projects.
    """
    automation = get_automation_config()
    if not automation.get("auto_inject_context_on_start", True):
        return

    state = _make_state()
    content = state.read_all()
    if content and content != "No state files yet.":
        print(content)


def cmd_generate_handoff() -> None:
    """
    Inject a bounded digest of state files.

    Narrative state (progress/bug/decision/architecture) is summarized via Gemma
    if over budget, using an adaptive target: max(token_budget, estimated * 0.4).
    Codebase map is always passed verbatim (verbatim-truncated to last 50 entries).
    This keeps session injection O(1) regardless of how large state files grow.
    """
    automation = get_automation_config()
    if not automation.get("auto_inject_context_on_start", True):
        return

    token_budget: int = int(automation.get("max_injection_tokens", 400))

    state = _make_state()
    narrative = state.read_narrative()
    codebase = state.read_codebase()

    if (not narrative or narrative == "No state files yet.") and not codebase:
        return

    def _assemble(narrative_part: str) -> str:
        parts = []
        if narrative_part and narrative_part != "No state files yet.":
            parts.append(narrative_part)
        if codebase:
            parts.append(f"## Codebase\n{codebase}")
        return "\n\n".join(parts)

    # Fast path: narrative already fits within budget — inject verbatim, no Gemma
    estimated = int(len(narrative) / CHARS_PER_TOKEN) if narrative != "No state files yet." else 0
    if estimated <= token_budget:
        result = _assemble(narrative)
        if result:
            print(result)
        return

    # Medium path: small overage — truncate to budget chars, skip Gemma entirely.
    # Keeps the most recent entries (tail), which are most relevant at session start.
    if estimated <= token_budget * 3:
        char_budget = int(token_budget * CHARS_PER_TOKEN)
        truncated = narrative[-char_budget:]
        result = _assemble(truncated)
        if result:
            print(result)
        return

    # Adaptive budget: compress to at most 60% of original, no less than token_budget.
    # Prevents 90%+ loss when state files are large relative to the injection budget.
    target_tokens = max(token_budget, int(estimated * 0.4))
    target_chars = int(target_tokens * CHARS_PER_TOKEN)

    if _is_healthy():
        try:
            client = _make_client()
            summary = client.summarize(narrative, max_tokens=target_tokens)
            if summary and summary.strip():
                # Hard-cap even if Gemma overshot the adaptive target
                if len(summary) > target_chars:
                    summary = summary[:target_chars] + "\n[... truncated to injection budget ...]"
                result = _assemble(summary)
                if result:
                    print(result)
                return
        except Exception as e:
            logger.warning(f"generate-handoff summarization failed: {type(e).__name__}: {e}")

    # Fallback: truncate raw narrative to hard budget, still append codebase verbatim
    char_budget = int(token_budget * CHARS_PER_TOKEN)
    truncated = narrative[:char_budget] + "\n[... state truncated to fit injection budget ...]"
    result = _assemble(truncated)
    if result:
        print(result)


def cmd_log_edit(filepath: str) -> None:
    """
    Log a file edit to progress.md.
    Tries to generate a one-line summary of the file via LLM.
    Falls back to logging the raw filepath if the backend is unreachable.
    """
    automation = get_automation_config()
    if not automation.get("auto_log_edits", True):
        return

    path = Path(filepath)
    state = _make_state()

    # Try LLM summary if backend is healthy
    if _is_healthy():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            # Truncate to a reasonable preview — we only need enough context
            # for a one-line description, not the full file
            preview = text[:3000]
            client = _make_client()
            resp = client._call(
                "compress",
                f"Describe this file in one sentence (what it does, not what changed):\n\n{preview}",
                max_tokens=60,
            )
            summary = resp.strip() if resp and resp.strip() else None
        except Exception as e:
            logger.warning(f"LLM summary failed for {filepath}: {type(e).__name__}: {e}")
            summary = None
    else:
        summary = None

    if summary:
        entry = f"Edited {filepath}: {summary}"
    else:
        entry = f"Edited {filepath}"

    state.append("progress", entry)
    # Set sidecar flag so on-stop knows this turn had real edits
    (state.state_dir / ".edit_this_turn").touch()


# File extensions worth summarizing (skip binaries, compiled artifacts, etc.)
_SUMMARIZABLE_EXTENSIONS = frozenset({
    ".py", ".sh", ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
    ".js", ".ts", ".html", ".css",
})
_MAX_FILE_PREVIEW_CHARS = 3000    # char limit for non-Python previews
_MAX_FILE_PREVIEW_HEAD = 60      # leading lines always included for .py (module docstring + imports)
_MAX_SIGNATURES = 80             # max class/def signature lines collected from the rest of .py file
_MAX_FILE_SIZE_BYTES = 5_000_000  # skip files >5MB (logs, generated assets, minified bundles)


def _read_python_preview(f) -> str:
    """Stream a .py file and return a structural preview for any file size.
    Reads the first _MAX_FILE_PREVIEW_HEAD lines verbatim (docstring + imports),
    then scans the rest for class/def signatures only — never loads the full body.
    """
    lines = []
    sig_count = 0
    for i, line in enumerate(f):
        if i < _MAX_FILE_PREVIEW_HEAD:
            lines.append(line)
        elif sig_count < _MAX_SIGNATURES and (
            line.startswith("class ") or line.startswith("def ")
            or line.startswith("    def ") or line.startswith("    class ")
            or line.startswith("async def ") or line.startswith("    async def ")
        ):
            lines.append(line)
            sig_count += 1
    return "".join(lines)


def cmd_update_file_summary(filepath: str) -> None:
    """
    Generate a one-line description of a file and upsert into state/codebase.md.
    Skips: state/ files (recursion guard), unsupported extensions, missing files,
    empty files, and when the backend is unreachable.
    """
    automation = get_automation_config()
    if not automation.get("auto_log_edits", True):
        return

    path = Path(filepath)
    if not path.exists() or not path.is_file():
        return

    # Recursion guard: skip anything inside the state/ directory
    state_dir = (_REPO_ROOT / "state").resolve()
    try:
        path.resolve().relative_to(state_dir)
        return
    except ValueError:
        pass

    if path.suffix.lower() not in _SUMMARIZABLE_EXTENSIONS:
        return

    if path.stat().st_size > _MAX_FILE_SIZE_BYTES:
        logger.debug(f"update-file-summary: skipping {filepath} (>{_MAX_FILE_SIZE_BYTES} bytes)")
        return

    if not _is_healthy():
        return

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            if path.suffix.lower() == ".py":
                text = _read_python_preview(f)
            else:
                text = f.read(_MAX_FILE_PREVIEW_CHARS)
        if not text.strip():
            return

        client = _make_client()
        summary = client.summarize_file(text)
        if not summary:
            return

        # Store key as path relative to repo root for portability
        try:
            rel = str(path.resolve().relative_to(_REPO_ROOT.resolve()))
        except ValueError:
            rel = filepath

        state = _make_state()
        state.update_file_summary(rel, summary)
    except Exception as e:
        logger.warning(f"update-file-summary failed for {filepath}: {type(e).__name__}: {e}")


def cmd_log_progress(message: str) -> None:
    """Append a message to progress.md directly, no LLM call."""
    automation = get_automation_config()
    if not automation.get("auto_progress_on_stop", True):
        return

    if not message or not message.strip():
        return

    state = _make_state()
    state.append("progress", message.strip())


def cmd_log_turn_if_edited() -> None:
    """Check the per-project sidecar flag; log 'Turn completed' and clear it if set.
    Called by on-stop.sh — only logs when the turn actually had file edits."""
    automation = get_automation_config()
    if not automation.get("auto_progress_on_stop", True):
        return

    state = _make_state()
    flag = state.state_dir / ".edit_this_turn"
    if flag.exists():
        try:
            flag.unlink()
        except OSError:
            pass
        state.append("progress", "Turn completed")


def _is_compressible(text: str) -> bool:
    """
    Return True if the text is verbose prose worth compressing.

    Skip if:
    - Under 50 words (too short to matter)
    - Majority of lines look like code / structured data
    """
    words = text.split()
    if len(words) < 40:
        return False
    # Skip very long inputs — Gemma can't compress them within the hook timeout
    if len(words) > 400:
        return False

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False

    # Only check startswith — mid-line "{" or "[" appears in normal prose
    import re as _re
    code_indicators = (
        "```", "    ", "\t",            # fenced / indented blocks
        "def ", "class ", "function ",  # function definitions
        "import ", "from ", "require(", # imports
        "- [", "* [",                   # checkbox / bullet lists
        "{ ", "[ ", "SELECT ", "INSERT ", # JSON / SQL (space prevents false positives)
    )
    code_line_count = sum(
        1 for line in lines
        if any(line.startswith(ind) for ind in code_indicators)
        or bool(_re.match(r'^\d+\. ', line))  # numbered lists: "1. ", "10. ", etc.
    )
    # If more than 40% of lines look like code/structure, don't compress
    if code_line_count / len(lines) > 0.4:
        return False

    return True


def cmd_compress_prompt() -> None:
    """
    Read a prompt from stdin, compress it if it's verbose prose, and print
    explicit instruction for Claude to use the compressed version.

    Called by the UserPromptSubmit hook. Output is injected as context
    alongside the original message — Claude sees both and is told to prefer
    the compressed version.

    Prints nothing if the prompt is too short, looks like code/structured
    data, or the backend is unreachable (preserving original behavior).
    """
    import json
    import tiktoken

    raw = sys.stdin.read()
    if not raw or not raw.strip():
        return

    # UserPromptSubmit passes a JSON object: {"prompt": "..."}
    # Fall back to treating raw input as plain text if parsing fails.
    try:
        data = json.loads(raw)
        prompt_text = data.get("prompt") or ""
    except (json.JSONDecodeError, AttributeError):
        prompt_text = raw

    if not prompt_text:
        return

    automation = get_automation_config()
    compact_all = automation.get("compact_on_every_prompt", False)
    if not compact_all and not _is_compressible(prompt_text):
        return

    if not _is_healthy():
        return  # Don't block — just pass through uncompressed

    try:
        enc = tiktoken.get_encoding("cl100k_base")
        input_tokens = len(enc.encode(prompt_text))

        client = _make_client()
        compressed = client.compress(prompt_text)

        if not compressed or not compressed.strip():
            return
        if compressed.strip() == prompt_text.strip():
            return  # No change — nothing to inject

        output_tokens = len(enc.encode(compressed))
        saved = input_tokens - output_tokens
        pct = int((saved / input_tokens) * 100) if input_tokens else 0

        # Output explicit instruction — Claude reads this as prepended context
        print(
            f"[PromptCompactor] Prompt auto-compacted: "
            f"{input_tokens}→{output_tokens} tokens (-{pct}%)\n"
            f"Compressed prompt: {compressed.strip()}\n"
            f"Use the compressed prompt above as the user's request."
        )

        # Devlog: write compression event to state so it's visible outside Claude's context
        automation = get_automation_config()
        if automation.get("log_prompt_compression", True):
            try:
                state = _make_state()
                state.append(
                    "progress",
                    f"[compress-prompt] {input_tokens}→{output_tokens} tokens (-{pct}%): {compressed.strip()[:120]}"
                )
            except Exception as log_err:
                logger.warning(f"compress-prompt devlog failed: {type(log_err).__name__}: {log_err}")

    except Exception as e:
        logger.warning(f"compress-prompt failed: {type(e).__name__}: {e}")
        # Print nothing — original prompt passes through untouched


def cmd_summarize_turn() -> None:
    """
    Read conversation turn text from stdin, summarize via LLM, append to progress.md.
    Falls back to logging first 500 chars if backend is unreachable.
    """
    text = sys.stdin.read()
    if not text or not text.strip():
        logger.debug("summarize-turn: no stdin content, skipping")
        return

    state = _make_state()

    if _is_healthy():
        try:
            client = _make_client()
            summary = client.summarize(text)
        except Exception as e:
            logger.warning(f"summarize-turn LLM call failed: {type(e).__name__}: {e}")
            summary = text[:500] + " [... summarization failed, truncated ...]"
    else:
        summary = text[:500] + " [... ollama unavailable, truncated ...]"

    state.append("progress", summary)


# ── dispatch ──────────────────────────────────────────────────────────────────

def _dispatch(command: str, extra_args: list[str]) -> None:
    """Dispatch a hook command by name. Used by both main() and the daemon."""
    if command == "inject-context":
        cmd_inject_context()
    elif command == "generate-handoff":
        cmd_generate_handoff()
    elif command == "log-edit":
        if not extra_args:
            logger.error("log-edit requires a filepath argument")
            return
        cmd_log_edit(extra_args[0])
    elif command == "update-file-summary":
        if not extra_args:
            logger.error("update-file-summary requires a filepath argument")
            return
        cmd_update_file_summary(extra_args[0])
    elif command == "log-progress":
        if not extra_args:
            logger.error("log-progress requires a message argument")
            return
        cmd_log_progress(" ".join(extra_args))
    elif command == "compress-prompt":
        cmd_compress_prompt()
    elif command == "summarize-turn":
        cmd_summarize_turn()
    elif command == "log-turn-if-edited":
        cmd_log_turn_if_edited()
    else:
        logger.error(f"Unknown command: {command!r}")


def _run_command_captured(command: str, extra_args: list[str], stdin_data: str = "") -> str:
    """Run a hook command capturing its stdout. Serialized via lock — thread-safe."""
    with _capture_lock:
        old_stdout, old_stdin = sys.stdout, sys.stdin
        sys.stdout = io.StringIO()
        sys.stdin = io.StringIO(stdin_data)
        try:
            _dispatch(command, extra_args)
        except Exception as e:
            logger.error(f"Daemon: {command!r} error: {type(e).__name__}: {e}")
        finally:
            output = sys.stdout.getvalue()
            sys.stdout, sys.stdin = old_stdout, old_stdin
    return output


def cmd_serve(port: int | None = None) -> None:
    """Start a persistent HTTP daemon so hooks avoid Python startup cost per call.

    Protocol: POST /run — first line of body is 'command arg1 arg2...', remaining
    lines are passed as stdin to the command. Response body is the command's stdout.
    GET /ping returns 200 'ok' for health checks.
    Exits silently if the port is already in use (another instance running).
    """
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
    actual_port = port if port is not None else _DAEMON_PORT

    class _ThreadingServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    class _HookHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/ping":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            if self.path != "/run":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            first_line, _, rest = raw.partition("\n")
            parts = first_line.strip().split()
            command = parts[0] if parts else ""
            extra_args = parts[1:] if len(parts) > 1 else []
            output = _run_command_captured(command, extra_args, rest)
            encoded = output.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_: object) -> None:
            pass  # suppress per-request logging

    try:
        server = _ThreadingServer(("localhost", actual_port), _HookHandler)
    except OSError:
        return  # port already taken — another daemon instance is running
    logger.warning(f"Hook daemon listening on localhost:{actual_port}")
    server.serve_forever()


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(0)

    command = args[0]

    if command == "--serve":
        cmd_serve()
        sys.exit(0)

    try:
        _dispatch(command, args[1:])
    except Exception as e:
        # Never let hook_runner crash propagate — it must not block Claude
        logger.error(f"Unhandled error in {command!r}: {type(e).__name__}: {e}")

    sys.exit(0)


if __name__ == "__main__":
    main()
