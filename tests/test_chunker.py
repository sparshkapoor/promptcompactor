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
