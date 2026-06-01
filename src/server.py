import logging
import shlex
import subprocess
import sys
from pathlib import Path

# Configure logging to stderr ONLY — stdout is reserved for MCP protocol
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("prompt-compactor")

from fastmcp import FastMCP
from .compactor_client import CompactorClient, MAX_INPUT_TOKENS, DEFAULT_BASE_URL
from .state_manager import StateManager, VALID_TYPES
from .chunker import chunk_text, CHARS_PER_TOKEN
from .health import check_compactor_health
from .config import get_state_dir
from .code_extractor import extract_skeleton, language_for_path

_BASH_OUTPUT_TOKEN_THRESHOLD = 300

mcp = FastMCP("prompt-compactor")

# Initialize on import — these are module-level singletons
_apfel = CompactorClient()
_state = StateManager(state_dir=get_state_dir())


@mcp.tool
def compact_prompt(text: str) -> str:
    """Compress a prompt or message to reduce token usage.
    Removes filler words and redundancy while preserving all technical content.
    Use before sending verbose input to the main model.
    Returns compressed text, or original text if compression fails."""
    if not text or len(text.split()) < 15:
        return text
    if not check_compactor_health():
        logger.warning("ollama unavailable, returning original text")
        return text
    result = _apfel.compress(text)
    # Safety: never return empty string from compression
    return result if result and result.strip() else text


@mcp.tool
def log_event(event_type: str, content: str) -> str:
    """Log a development event to a project state file.
    event_type: one of 'progress', 'bug', 'decision', 'architecture', or 'auto' for classification.
    content: brief description of what happened.
    Returns confirmation message."""
    if not content or not content.strip():
        return "Error: empty content"
    if event_type == "auto":
        if check_compactor_health():
            event_type = _apfel.classify(content)
        else:
            event_type = "progress"
    if event_type not in VALID_TYPES:
        logger.warning(f"Invalid event_type '{event_type}', defaulting to 'progress'")
        event_type = "progress"
    _state.append(event_type, content.strip())
    return f"Logged to {event_type}.md"


@mcp.tool
def summarize_history(turns: str) -> str:
    """Summarize older conversation turns into compact format.
    Input: raw text of conversation turns to compress.
    Returns compressed summary preserving technical details.
    Falls back to truncation if apfel is unavailable."""
    if not turns or not turns.strip():
        return "Error: no conversation turns provided."
    if not check_compactor_health():
        logger.warning("ollama unavailable, truncating instead of summarizing")
        return turns[:2000] + "\n[... truncated, ollama unavailable ...]"  # 2000 chars ~500 tokens
    chunks = chunk_text(turns, max_tokens=MAX_INPUT_TOKENS)
    summaries = []
    for i, chunk in enumerate(chunks):
        logger.info(f"Summarizing chunk {i+1}/{len(chunks)}")
        summary = _apfel.summarize(chunk)
        if summary and summary.strip():
            summaries.append(summary.strip())
        else:
            # Fallback: keep first 500 chars of chunk
            summaries.append(chunk[:500] + " [...]")
    return "\n\n".join(summaries)


@mcp.tool
def generate_handoff(token_budget: int = 2000) -> str:
    """Generate a session handoff digest from current state files.
    Use when starting a new session to inject project context.
    token_budget: approximate max tokens for output (default 2000).
    Narrative state is compressed adaptively; codebase map is always verbatim.
    Returns formatted context digest."""
    narrative = _state.read_narrative()
    codebase = _state.read_codebase()

    if narrative == "No state files yet." and not codebase:
        return "No project state recorded yet."

    def _assemble(narrative_part: str) -> str:
        parts = []
        if narrative_part and narrative_part != "No state files yet.":
            parts.append(narrative_part)
        if codebase:
            parts.append(f"## Codebase\n{codebase}")
        return "\n\n".join(parts) if parts else "No project state recorded yet."

    estimated_narrative = int(len(narrative) / CHARS_PER_TOKEN) if narrative != "No state files yet." else 0

    if estimated_narrative <= token_budget:
        return _assemble(narrative)

    if not check_compactor_health():
        char_budget = int(token_budget * CHARS_PER_TOKEN)
        truncated = narrative[:char_budget] + "\n[... truncated, ollama unavailable ...]"
        return _assemble(truncated)

    # Adaptive budget: compress to at most 60% of original, no less than token_budget.
    # Prevents 90%+ loss when state files are large relative to the budget.
    target_tokens = max(token_budget, int(estimated_narrative * 0.4))
    summary = _apfel.summarize(narrative, max_tokens=target_tokens)
    return _assemble(summary)


@mcp.tool
def set_model(model: str, base_url: str = "") -> str:
    """Switch the active model and/or backend at runtime without restarting the server.
    model: model name (e.g. 'gemma4:e4b', 'apple-foundationmodel').
    base_url: optional OpenAI-compatible base URL (defaults to current URL if omitted).
    Returns confirmation with old and new values."""
    old_model = _apfel.model
    old_url = _apfel._base_url
    new_url = base_url or old_url
    _apfel.reconfigure(model, new_url)
    logger.info(f"Switched model: '{old_model}' → '{model}', base_url: '{old_url}' → '{new_url}'")
    return f"Model: {old_model} → {model}\nBase URL: {old_url} → {new_url}"


@mcp.tool
def get_info() -> str:
    """Return current server configuration: active model, base URL, and health status.
    Use this to verify which model (Gemma 4, apfel, etc.) is handling requests."""
    healthy = check_compactor_health()
    return (
        f"Model: {_apfel.model}\n"
        f"Base URL: {DEFAULT_BASE_URL}\n"
        f"Server healthy: {healthy}\n"
        f"(Override with APFEL_MODEL or APFEL_BASE_URL env vars)"
    )


@mcp.tool
def compact_code(text: str, language: str = "python") -> str:
    """Compress a code block using AST skeleton extraction, with optional NL outline.
    Extracts function/class signatures and docstrings, drops bodies — typically 70% token reduction.
    language: Tree-sitter language name (python, javascript, typescript, go, rust, java, c, cpp).
    Returns the skeleton or NL outline, or original text if extraction fails or backend is down."""
    if not text or not text.strip():
        return text
    skeleton = extract_skeleton(text, language)
    if skeleton is text:
        return text  # extraction didn't help
    if len(skeleton.split()) > 200:
        if not check_compactor_health():
            return skeleton
        result = _apfel.outline_code(skeleton)
        return result if result and result.strip() else skeleton
    return skeleton


@mcp.tool
def get_context() -> str:
    """Read all current project state files.
    Returns contents of progress.md, bug.md, decision.md, and architecture.md.
    No LLM call required."""
    return _state.read_all()


@mcp.tool
def read(path: str) -> str:
    """Read a file and return compressed content to save context tokens.
    Code files are skeleton-extracted (signatures + docstrings, bodies dropped).
    Prose files are Gemma-compressed if Ollama is available.
    Returns compressed content, or full content on failure.
    Prefer this over the built-in Read tool."""
    try:
        file_path = Path(path).resolve()
        if not file_path.exists():
            return f"Error: file not found: {path}"
        text = file_path.read_text(errors="replace")
    except OSError as exc:
        return f"Error reading {path}: {exc}"

    lang = language_for_path(path)
    if lang:
        skeleton = extract_skeleton(text, lang)
        if skeleton is not text:
            if len(skeleton.split()) > 200 and check_compactor_health():
                result = _apfel.outline_code(skeleton)
                return result if result and result.strip() else skeleton
            return skeleton

    if not text or len(text.split()) < 15:
        return text
    if not check_compactor_health():
        return text
    result = _apfel.compress(text)
    return result if result and result.strip() else text


@mcp.tool
def bash(cmd: str, timeout: int = 30) -> str:
    """Run a shell command and return compressed output to save context tokens.
    Output over 300 tokens is Gemma-compressed if Ollama is available.
    timeout: max seconds to wait (default 30).
    Returns command output (stdout + stderr), or error string on failure.
    Prefer this over the built-in Bash tool."""
    try:
        args = shlex.split(cmd)
    except ValueError as exc:
        return f"Error parsing command: {exc}"
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = proc.stdout
        if proc.stderr:
            output = output + proc.stderr if output else proc.stderr
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s: {cmd}"
    except OSError as exc:
        return f"Error running command: {exc}"

    if not output or not output.strip():
        return output or ""

    word_count = len(output.split())
    if word_count <= _BASH_OUTPUT_TOKEN_THRESHOLD or not check_compactor_health():
        return output
    result = _apfel.compress(output)
    return result if result and result.strip() else output


if __name__ == "__main__":
    mcp.run()
