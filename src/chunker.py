import logging
from .config import get_max_input_tokens

logger = logging.getLogger("prompt-compactor.chunker")

# Single source of truth for token estimation used across the whole codebase.
# 4 chars/token matches the estimate used in server.py and hook_runner.py.
# Slightly overestimates token count, which is the safe direction for budgeting.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count from character length. Conservative (overestimates slightly)."""
    return int(len(text) / CHARS_PER_TOKEN)


def _split_long_line(line: str, max_chars: int) -> list[str]:
    """Split a single oversized line into pieces, preferring word boundaries."""
    pieces: list[str] = []
    while len(line) > max_chars:
        # Find last space at or before max_chars to avoid cutting mid-word
        cut = line.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars  # No space found; hard cut
        piece = line[:cut].strip()
        if piece:
            pieces.append(piece)
        line = line[cut:].lstrip()
    if line.strip():
        pieces.append(line.strip())
    return pieces


def chunk_text(text: str, max_tokens: int | None = None) -> list[str]:
    """Split text into chunks that fit within the model's context window.

    Args:
        text: Input text to split.
        max_tokens: Max tokens per chunk. Defaults to get_max_input_tokens()
            which is calculated from config.json as:
            max_context_tokens - system_prompt - response_reserve - safety_margin

    Returns:
        List of text chunks, each within the token budget.
    """
    if max_tokens is None:
        max_tokens = get_max_input_tokens()

    if not text or not text.strip():
        return []

    if estimate_tokens(text) <= max_tokens:
        return [text]

    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    chunks: list[str] = []

    # Try to split on paragraph boundaries first
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        candidate = f"{current_chunk}\n\n{para}" if current_chunk else para

        if len(candidate) > max_chars:
            # Save current chunk if non-empty
            if current_chunk.strip():
                chunks.append(current_chunk.strip())

            # If single paragraph exceeds limit, force-split on newlines then chars
            if len(para) > max_chars:
                lines = para.split("\n")
                sub_chunk = ""
                for line in lines:
                    # If a single line is too long, split at word boundaries
                    if len(line) > max_chars:
                        if sub_chunk.strip():
                            chunks.append(sub_chunk.strip())
                            sub_chunk = ""
                        chunks.extend(_split_long_line(line, max_chars))
                        continue
                    sub_candidate = f"{sub_chunk}\n{line}" if sub_chunk else line
                    if len(sub_candidate) > max_chars:
                        if sub_chunk.strip():
                            chunks.append(sub_chunk.strip())
                        sub_chunk = line
                    else:
                        sub_chunk = sub_candidate
                current_chunk = sub_chunk
            else:
                current_chunk = para
        else:
            current_chunk = candidate

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    if not chunks:
        # Ultimate fallback: split at word boundaries
        chunks.extend(_split_long_line(text, max_chars))

    logger.info(f"Split {len(text)} chars into {len(chunks)} chunks")
    return chunks
