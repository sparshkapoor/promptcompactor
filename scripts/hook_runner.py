#!/usr/bin/env python3
"""
hook_runner.py — CLI entry point called by Claude Code lifecycle hooks.

Hooks run in their own shell process, completely separate from the MCP server.
This script reuses the same src/ modules (ApfelClient, StateManager, health)
so there's no logic duplication.

IMPORTANT: stdout is reserved for hook output that Claude Code reads.
           All logging must go to stderr.

Usage:
  python scripts/hook_runner.py inject-context      # Read state files raw, output to stdout
  python scripts/hook_runner.py generate-handoff    # Bounded digest (summarizes if over max_injection_tokens)
  python scripts/hook_runner.py compress-prompt     # Read prompt JSON from stdin, inject compressed version
  python scripts/hook_runner.py log-edit <filepath>
  python scripts/hook_runner.py log-progress <message>
  python scripts/hook_runner.py summarize-turn

Exit codes:
  0 — success (always; hooks must not block Claude)
"""

import logging
import sys

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

from src.config import get_backend_config, get_automation_config  # noqa: E402
from src.apfel_client import ApfelClient                           # noqa: E402
from src.state_manager import StateManager                         # noqa: E402
from src.health import check_apfel_health                          # noqa: E402


def _make_client() -> ApfelClient:
    """
    Short timeout + no retries so all hook LLM calls complete well under
    Claude Code's 20s hook timeout. Hooks must never block Claude.
    """
    cfg = get_backend_config()
    client = ApfelClient(base_url=cfg["base_url"], model=cfg["model"], timeout=8.0)
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
    return StateManager(state_dir=_REPO_ROOT / "state")


def _health_base_url() -> str:
    """Derive scheme://host:port from config base_url (strips /v1 path)."""
    from urllib.parse import urlparse
    parsed = urlparse(get_backend_config()["base_url"])
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_healthy() -> bool:
    return check_apfel_health(_health_base_url())


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

    If state fits within max_injection_tokens, print it verbatim.
    Otherwise summarize via Gemma first, then hard-cap at the budget.
    This keeps session injection O(1) regardless of how large state files grow.
    """
    automation = get_automation_config()
    if not automation.get("auto_inject_context_on_start", True):
        return

    token_budget: int = int(automation.get("max_injection_tokens", 400))
    char_budget = token_budget * 4  # conservative 4 chars/token

    state = _make_state()
    raw = state.read_all()

    if not raw or raw == "No state files yet.":
        return

    # Fast path: already small enough
    estimated = len(raw) // 4
    if estimated <= token_budget:
        print(raw)
        return

    # State is too large — summarize it
    if _is_healthy():
        try:
            client = _make_client()
            # Pass budget hint in the content so Gemma knows to be concise
            hint = f"Summarize the following project state in under {token_budget} tokens:\n\n{raw}"
            summary = client._call("summarize", hint)
            if summary and summary.strip():
                # Hard-cap even if Gemma overshot
                if len(summary) > char_budget:
                    summary = summary[:char_budget] + "\n[... truncated to injection budget ...]"
                print(summary)
                return
        except Exception as e:
            logger.warning(f"generate-handoff summarization failed: {type(e).__name__}: {e}")

    # Fallback: truncate raw state to budget
    print(raw[:char_budget] + "\n[... state truncated to fit injection budget ...]")


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


def cmd_log_progress(message: str) -> None:
    """Append a message to progress.md directly, no LLM call."""
    automation = get_automation_config()
    if not automation.get("auto_progress_on_stop", True):
        return

    if not message or not message.strip():
        return

    state = _make_state()
    state.append("progress", message.strip())


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
    code_indicators = (
        "```", "    ", "\t",            # fenced / indented blocks
        "def ", "class ", "function ",  # function definitions
        "import ", "from ", "require(", # imports
        "- [", "* [", "1. ", "2. ",     # structured lists
        "{ ", "[ ", "SELECT ", "INSERT ", # JSON / SQL (space prevents false positives)
    )
    code_line_count = sum(
        1 for line in lines
        if any(line.startswith(ind) for ind in code_indicators)
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

    if not _is_compressible(prompt_text):
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
            f"[ApfelContext] Prompt auto-compacted: "
            f"{input_tokens}→{output_tokens} tokens (-{pct}%)\n"
            f"Compressed prompt: {compressed.strip()}\n"
            f"Use the compressed prompt above as the user's request."
        )
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
        summary = text[:500] + " [... apfel unavailable, truncated ...]"

    state.append("progress", summary)


# ── dispatch ──────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(0)

    command = args[0]

    try:
        if command == "inject-context":
            cmd_inject_context()

        elif command == "generate-handoff":
            cmd_generate_handoff()

        elif command == "log-edit":
            if len(args) < 2:
                logger.error("log-edit requires a filepath argument")
                sys.exit(0)  # Never block Claude
            cmd_log_edit(args[1])

        elif command == "log-progress":
            if len(args) < 2:
                logger.error("log-progress requires a message argument")
                sys.exit(0)
            cmd_log_progress(" ".join(args[1:]))

        elif command == "compress-prompt":
            cmd_compress_prompt()

        elif command == "summarize-turn":
            cmd_summarize_turn()

        else:
            logger.error(f"Unknown command: {command!r}")

    except Exception as e:
        # Never let hook_runner crash propagate — it must not block Claude
        logger.error(f"Unhandled error in {command!r}: {type(e).__name__}: {e}")

    sys.exit(0)


if __name__ == "__main__":
    main()
