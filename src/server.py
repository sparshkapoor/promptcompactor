import logging
import sys

# Configure logging to stderr ONLY — stdout is reserved for MCP protocol
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("apfel-context")

from fastmcp import FastMCP
from .apfel_client import ApfelClient, MAX_INPUT_TOKENS
from .state_manager import StateManager, VALID_TYPES
from .chunker import chunk_text
from .health import check_apfel_health

mcp = FastMCP("apfel-context")

# Initialize on import — these are module-level singletons
_apfel = ApfelClient()
_state = StateManager()


@mcp.tool
def compact_prompt(text: str) -> str:
    """Compress a prompt or message to reduce token usage.
    Removes filler words and redundancy while preserving all technical content.
    Use before sending verbose input to the main model.
    Returns compressed text, or original text if compression fails."""
    if not text or len(text.split()) < 15:
        return text
    if not check_apfel_health():
        logger.warning("apfel unavailable, returning original text")
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
        if check_apfel_health():
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
    if not check_apfel_health():
        logger.warning("apfel unavailable, truncating instead of summarizing")
        return turns[:2000] + "\n[... truncated, apfel unavailable ...]"  # 2000 chars ~500 tokens
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
    Returns formatted context digest."""
    raw_state = _state.read_all()
    if not raw_state or raw_state == "No state files yet.":
        return "No project state recorded yet."
    # Rough check: if state is small enough, return as-is
    estimated_tokens = len(raw_state) // 4  # ~4 chars per token
    if estimated_tokens <= token_budget:
        return raw_state
    if not check_apfel_health():
        # Truncate to approximate budget
        char_budget = token_budget * 4
        return raw_state[:char_budget] + "\n[... truncated, apfel unavailable ...]"
    return _apfel.summarize(raw_state)


@mcp.tool
def set_model(model: str, base_url: str = "") -> str:
    """Switch the active model and/or backend at runtime without restarting the server.
    model: model name (e.g. 'gemma4:e4b', 'apple-foundationmodel').
    base_url: optional OpenAI-compatible base URL (defaults to current URL if omitted).
    Returns confirmation with old and new values."""
    from .apfel_client import DEFAULT_BASE_URL
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
    from .apfel_client import DEFAULT_BASE_URL
    healthy = check_apfel_health()
    return (
        f"Model: {_apfel.model}\n"
        f"Base URL: {DEFAULT_BASE_URL}\n"
        f"Server healthy: {healthy}\n"
        f"(Override with APFEL_MODEL or APFEL_BASE_URL env vars)"
    )


@mcp.tool
def get_context() -> str:
    """Read all current project state files.
    Returns contents of progress.md, bug.md, decision.md, and architecture.md.
    No LLM call required."""
    return _state.read_all()


if __name__ == "__main__":
    mcp.run()
