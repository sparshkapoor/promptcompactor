"""Tests for src/apfel_client.py"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
from src.apfel_client import (
    ApfelClient, VALID_CATEGORIES, DEFAULT_CATEGORY,
    DEFAULT_MODEL, MAX_INPUT_TOKENS,
)


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


def test_call_propagates_file_not_found(client):
    """_call re-raises FileNotFoundError when prompt file is missing (covers line 65)."""
    # Remove the compress.txt prompt so _load_prompt raises FileNotFoundError
    (client.prompts_dir / "compress.txt").unlink()
    with pytest.raises(FileNotFoundError):
        client._call("compress", "some input")


def test_compress_returns_original_on_none_response(client):
    """compress() returns original when API returns None content."""
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion(None)):
        original = "original text that should come back"
        result = client.compress(original)
    assert result == original


def test_load_prompt_reads_correct_content(client):
    """_load_prompt returns file content stripped of whitespace."""
    (client.prompts_dir / "compress.txt").write_text("  my prompt content  ")
    result = client._load_prompt("compress")
    assert result == "my prompt content"


def test_summarize_returns_truncated_original_when_api_returns_none(client):
    """summarize() falls back to truncation when API returns None."""
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion(None)):
        long_text = "a" * 1000
        result = client.summarize(long_text)
    assert "summarization failed" in result
    assert result.startswith(long_text[:500])


def test_classify_normalizes_to_lowercase(client):
    """classify() normalizes response to lowercase before comparing."""
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion("BUG")):
        result = client.classify("some bug")
    assert result == "bug"


def test_default_model_is_gemma4():
    """DEFAULT_MODEL must be gemma4:e4b — regression guard against silent reverts."""
    assert DEFAULT_MODEL == "gemma4:e4b"


def test_max_input_tokens_from_config():
    """MAX_INPUT_TOKENS must be positive and derived from config (not a stale hardcode)."""
    from src.config import get_max_input_tokens
    assert MAX_INPUT_TOKENS > 0
    assert MAX_INPUT_TOKENS == get_max_input_tokens()


def test_custom_model_passed_to_api(tmp_path):
    """model= param in __init__ must flow through to the API call."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "compress.txt").write_text("compress prompt")

    c = ApfelClient(model="apple-foundationmodel")
    c.prompts_dir = prompts_dir

    with patch.object(c.client.chat.completions, "create",
                      return_value=_make_completion("result")) as mock_create:
        c.compress("some text to compress here with enough words")
    call_kwargs = mock_create.call_args
    assert call_kwargs.kwargs["model"] == "apple-foundationmodel"


def test_default_model_used_in_api_call(client):
    """ApfelClient() with no model arg must call the API with DEFAULT_MODEL."""
    with patch.object(client.client.chat.completions, "create",
                      return_value=_make_completion("result")) as mock_create:
        client.compress("some text to compress here with enough words")
    assert mock_create.call_args.kwargs["model"] == DEFAULT_MODEL
