"""Tests for src/apfel_client.py"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
from src.apfel_client import ApfelClient, VALID_CATEGORIES, DEFAULT_CATEGORY


@pytest.fixture
def client(tmp_path):
    """ApfelClient with a real prompts directory."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    for name in ("compress", "classify", "summarize", "extract"):
        (prompts_dir / f"{name}.txt").write_text(f"System prompt for {name}.")

    c = ApfelClient()
    c.prompts_dir = prompts_dir
    return c


def _make_completion(content: str):
    """Build a mock openai ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_compress_returns_result_on_success(client):
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion("compressed text")):
        result = client.compress("this is the original long verbose text")
    assert result == "compressed text"


def test_compress_returns_original_on_failure(client):
    with patch.object(client.client.chat.completions, "create",
                      side_effect=Exception("network error")):
        original = "original text"
        result = client.compress(original)
    assert result == original


def test_compress_returns_original_on_empty_response(client):
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion("   ")):
        original = "original text"
        result = client.compress(original)
    assert result == original


def test_classify_returns_valid_category(client):
    for category in VALID_CATEGORIES:
        with patch.object(client.client.chat.completions, "create",
                          return_value=_make_completion(category)):
            result = client.classify("some event description")
        assert result == category


def test_classify_defaults_on_invalid_response(client):
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion("unknown_category")):
        result = client.classify("some event")
    assert result == DEFAULT_CATEGORY


def test_classify_defaults_on_none_response(client):
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion(None)):
        result = client.classify("some event")
    assert result == DEFAULT_CATEGORY


def test_classify_defaults_on_exception(client):
    with patch.object(client.client.chat.completions, "create",
                      side_effect=Exception("timeout")):
        result = client.classify("some event")
    assert result == DEFAULT_CATEGORY


def test_summarize_returns_summary(client):
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion("- bullet one\n- bullet two")):
        result = client.summarize("long text to summarize")
    assert result == "- bullet one\n- bullet two"


def test_summarize_fallback_on_failure(client):
    with patch.object(client.client.chat.completions, "create",
                      side_effect=Exception("error")):
        long_text = "x" * 1000
        result = client.summarize(long_text)
    assert "summarization failed" in result


def test_truncate_input_truncates_long_text(client):
    from src.apfel_client import MAX_INPUT_CHARS
    long_text = "a" * (MAX_INPUT_CHARS + 1000)
    truncated = client._truncate_input(long_text)
    assert len(truncated) <= MAX_INPUT_CHARS + 100  # account for suffix
    assert "truncated" in truncated


def test_truncate_input_leaves_short_text_unchanged(client):
    short = "hello world"
    assert client._truncate_input(short) == short


def test_load_prompt_raises_on_missing_file(client):
    with pytest.raises(FileNotFoundError):
        client._load_prompt("nonexistent_prompt")


def test_classify_strips_trailing_period(client):
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion("bug.")):
        result = client.classify("some bug description")
    assert result == "bug"


def test_prompts_directory_missing_raises_file_not_found(tmp_path):
    """If the prompts directory is missing, _load_prompt should raise FileNotFoundError."""
    client = ApfelClient()
    client.prompts_dir = tmp_path / "nonexistent_prompts"
    with pytest.raises(FileNotFoundError):
        client._load_prompt("compress")
