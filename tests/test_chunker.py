"""Tests for src/chunker.py"""
import pytest
from src.chunker import chunk_text, estimate_tokens, CHARS_PER_TOKEN


def test_empty_input_returns_empty_list():
    assert chunk_text("") == []


def test_whitespace_only_returns_empty_list():
    assert chunk_text("   \n\t  ") == []


def test_none_like_empty_string():
    assert chunk_text("") == []


def test_short_text_stays_single_chunk():
    text = "This is a short text that should not be split."
    result = chunk_text(text)
    assert len(result) == 1
    assert result[0] == text


def test_long_text_splits_into_multiple_chunks():
    # Create text that exceeds 2500-token budget (2500 * 3.5 = 8750 chars)
    long_text = "word " * 5000  # ~25000 chars >> 8750
    result = chunk_text(long_text)
    assert len(result) > 1


def test_all_content_preserved_after_chunking():
    # Build text from deterministic words so we can verify content
    words = [f"word{i}" for i in range(3000)]
    text = " ".join(words)
    chunks = chunk_text(text, max_tokens=500)
    combined = " ".join(chunks)
    # Every word should appear in the concatenated chunks
    for word in words:
        assert word in combined


def test_each_chunk_within_token_limit():
    long_text = "paragraph " * 4000
    max_tokens = 200
    chunks = chunk_text(long_text, max_tokens=max_tokens)
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    for chunk in chunks:
        assert len(chunk) <= max_chars, f"Chunk too long: {len(chunk)} chars > {max_chars}"


def test_paragraph_boundaries_preferred():
    # Text with clear paragraph breaks
    paras = ["Paragraph one content here." * 10,
             "Paragraph two content here." * 10,
             "Paragraph three content here." * 10]
    text = "\n\n".join(paras)
    chunks = chunk_text(text, max_tokens=200)
    assert len(chunks) >= 2


def test_single_chunk_returned_for_just_under_limit():
    max_tokens = 100
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    text = "x" * (max_chars - 1)
    result = chunk_text(text, max_tokens=max_tokens)
    assert len(result) == 1


def test_estimate_tokens():
    text = "a" * 350
    assert estimate_tokens(text) == int(350 / CHARS_PER_TOKEN)


def test_single_line_no_spaces_hard_split():
    """Line with no spaces gets hard-split at char boundary (covers line 21)."""
    max_tokens = 10
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    # A solid block of characters with no spaces — forces hard cut
    no_space_line = "x" * (max_chars * 3)
    chunks = chunk_text(no_space_line, max_tokens=max_tokens)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= max_chars


def test_single_paragraph_exceeding_limit_split_on_lines():
    """One huge paragraph (no double-newlines) gets split on single newlines (covers lines 75-85)."""
    max_tokens = 50
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    # Build a big paragraph with single-newline separators
    line = "word " * 20  # ~100 chars per line
    big_para = "\n".join([line] * 20)  # single newlines, no double
    chunks = chunk_text(big_para, max_tokens=max_tokens)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= max_chars


def test_single_long_line_inside_paragraph_hard_splits():
    """A single oversized line inside a paragraph triggers _split_long_line (covers lines 75-76)."""
    max_tokens = 10
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    # One line with no spaces and length > max_chars, inside a paragraph
    huge_line = "a" * (max_chars * 4)
    para = f"short header\n{huge_line}"
    chunks = chunk_text(para, max_tokens=max_tokens)
    assert len(chunks) > 1


def test_ultimate_fallback_on_single_long_paragraph():
    """Ultimate fallback path (line 97) triggered when no chunks built from paragraphs."""
    max_tokens = 10
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    # Single paragraph exactly equal to max_chars — estimate_tokens > max_tokens
    # but paragraph fits in max_chars so current_chunk gets set but chunks stays empty
    # until the final flush... use a slightly-over-limit single paragraph with no \n\n
    text = "a " * (max_tokens + 5)  # spaces allow word-boundary splitting via fallback
    chunks = chunk_text(text, max_tokens=max_tokens)
    assert len(chunks) >= 1


def test_unicode_text_does_not_crash():
    """Unicode characters (emoji, CJK) don't cause errors."""
    unicode_text = "Hello 🌍 世界 こんにちは " * 100
    chunks = chunk_text(unicode_text)
    assert isinstance(chunks, list)


def test_large_text_reasonable_chunk_count():
    """100K+ character text produces a reasonable (non-zero) chunk count."""
    big_text = "The quick brown fox jumps over the lazy dog. " * 2500  # ~112500 chars
    chunks = chunk_text(big_text)
    assert len(chunks) >= 1
    assert len(chunks) < 1000  # sanity upper bound
