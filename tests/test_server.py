"""Tests for src/server.py — MCP tool functions."""
import pytest
from unittest.mock import patch, MagicMock


# Patch at module level before importing server to avoid real singleton init issues
@pytest.fixture(autouse=True)
def mock_singletons(tmp_path):
    """Replace module-level singletons with test doubles."""
    with patch("src.server._apfel") as mock_apfel, \
         patch("src.server._state") as mock_state, \
         patch("src.server.check_apfel_health") as mock_health:
        mock_health.return_value = True
        yield mock_apfel, mock_state, mock_health


def test_compact_prompt_short_text_passthrough(mock_singletons):
    from src.server import compact_prompt
    mock_apfel, mock_state, mock_health = mock_singletons
    # Short text (< 15 words) should not call apfel
    result = compact_prompt("short text")
    mock_apfel.compress.assert_not_called()
    assert result == "short text"


def test_compact_prompt_calls_compress_for_long_text(mock_singletons):
    from src.server import compact_prompt
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.compress.return_value = "compressed"
    long_text = "word " * 20
    result = compact_prompt(long_text)
    mock_apfel.compress.assert_called_once_with(long_text)
    assert result == "compressed"


def test_compact_prompt_falls_back_when_apfel_down(mock_singletons):
    from src.server import compact_prompt
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_health.return_value = False
    long_text = "word " * 20
    result = compact_prompt(long_text)
    mock_apfel.compress.assert_not_called()
    assert result == long_text


def test_compact_prompt_returns_original_on_empty_compression(mock_singletons):
    from src.server import compact_prompt
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.compress.return_value = ""
    long_text = "word " * 20
    result = compact_prompt(long_text)
    assert result == long_text


def test_log_event_empty_content_returns_error(mock_singletons):
    from src.server import log_event
    mock_apfel, mock_state, mock_health = mock_singletons
    result = log_event("progress", "")
    assert "Error" in result
    mock_state.append.assert_not_called()


def test_log_event_explicit_type(mock_singletons):
    from src.server import log_event
    mock_apfel, mock_state, mock_health = mock_singletons
    result = log_event("bug", "Found a null pointer exception")
    mock_state.append.assert_called_once_with("bug", "Found a null pointer exception")
    assert "bug.md" in result


def test_log_event_auto_classifies(mock_singletons):
    from src.server import log_event
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.classify.return_value = "decision"
    result = log_event("auto", "Chose React over Vue")
    mock_apfel.classify.assert_called_once()
    mock_state.append.assert_called_once()
    assert "decision.md" in result


def test_log_event_auto_falls_back_when_apfel_down(mock_singletons):
    from src.server import log_event
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_health.return_value = False
    result = log_event("auto", "Did something")
    mock_state.append.assert_called_once_with("progress", "Did something")
    assert "progress.md" in result


def test_summarize_history_empty_returns_empty(mock_singletons):
    from src.server import summarize_history
    result = summarize_history("")
    assert result == ""


def test_summarize_history_truncates_when_apfel_down(mock_singletons):
    from src.server import summarize_history
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_health.return_value = False
    long_turns = "turn " * 1000
    result = summarize_history(long_turns)
    assert "truncated" in result
    assert len(result) <= 2100  # 2000 + marker


def test_summarize_history_calls_summarize_per_chunk(mock_singletons):
    from src.server import summarize_history
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.summarize.return_value = "summary"
    result = summarize_history("Some conversation turns here.")
    mock_apfel.summarize.assert_called()


def test_generate_handoff_no_state(mock_singletons):
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_state.read_all.return_value = "No state files yet."
    result = generate_handoff()
    assert "No project state" in result


def test_generate_handoff_small_state_returned_as_is(mock_singletons):
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_state.read_all.return_value = "## Progress\n- did stuff\n"
    result = generate_handoff(token_budget=2000)
    # Small state fits within budget
    assert "## Progress" in result
    mock_apfel.summarize.assert_not_called()


def test_generate_handoff_large_state_summarized(mock_singletons):
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    # 2000 token budget = ~8000 chars; use 10000 chars to exceed it
    mock_state.read_all.return_value = "x" * 10000
    mock_apfel.summarize.return_value = "compact summary"
    result = generate_handoff(token_budget=2000)
    # Large state is chunked; summarize is called once per chunk
    mock_apfel.summarize.assert_called()
    assert "compact summary" in result


def test_get_context_reads_state(mock_singletons):
    from src.server import get_context
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_state.read_all.return_value = "## Progress\n- entry\n"
    result = get_context()
    mock_state.read_all.assert_called_once()
    assert "## Progress" in result
