"""Tests for src/server.py — MCP tool functions."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# Patch at module level before importing server to avoid real singleton init issues
@pytest.fixture(autouse=True)
def mock_singletons(tmp_path):
    """Replace module-level singletons with test doubles."""
    with patch("src.server._apfel") as mock_apfel, \
         patch("src.server._state") as mock_state, \
         patch("src.server.check_compactor_health") as mock_health:
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


def test_summarize_history_empty_returns_error(mock_singletons):
    from src.server import summarize_history
    result = summarize_history("")
    assert "Error" in result
    assert result != ""


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
    mock_state.read_narrative.return_value = "No state files yet."
    mock_state.read_codebase.return_value = ""
    result = generate_handoff()
    assert "No project state" in result


def test_generate_handoff_small_state_returned_as_is(mock_singletons):
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_state.read_narrative.return_value = "## Progress\n- did stuff\n"
    mock_state.read_codebase.return_value = ""
    result = generate_handoff(token_budget=2000)
    # Small state fits within budget — no summarization
    assert "## Progress" in result
    mock_apfel.summarize.assert_not_called()


def test_generate_handoff_large_state_summarized(mock_singletons):
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    # 2000 token budget = ~8000 chars; use 10000 chars to exceed it
    mock_state.read_narrative.return_value = "x" * 10000
    mock_state.read_codebase.return_value = ""
    mock_apfel.summarize.return_value = "compact summary"
    result = generate_handoff(token_budget=2000)
    mock_apfel.summarize.assert_called_once()
    assert "compact summary" in result


def test_generate_handoff_codebase_never_summarized(mock_singletons):
    """Codebase map passes through verbatim even when narrative is large."""
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_state.read_narrative.return_value = "x" * 10000
    mock_state.read_codebase.return_value = "# Codebase Map\n\n- `src/server.py`: MCP server."
    mock_apfel.summarize.return_value = "compact narrative"
    result = generate_handoff(token_budget=2000)
    # Narrative was summarized but codebase is verbatim in the output
    assert "src/server.py" in result
    assert "MCP server." in result
    # summarize was called exactly once (for narrative only)
    mock_apfel.summarize.assert_called_once()


def test_generate_handoff_adaptive_budget(mock_singletons):
    """target_tokens = max(token_budget, estimated * 0.4); prevents over-compression."""
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    # 5000 tokens estimated (20000 chars); token_budget=400
    # adaptive target = max(400, 5000*0.4) = max(400, 2000) = 2000
    narrative = "w " * 10000   # 10000 words ≈ 10000 tokens (rough)
    mock_state.read_narrative.return_value = narrative
    mock_state.read_codebase.return_value = ""
    mock_apfel.summarize.return_value = "summary"
    generate_handoff(token_budget=400)
    # summarize must have been called with max_tokens >= 400
    call_kwargs = mock_apfel.summarize.call_args
    used_max_tokens = call_kwargs[1].get("max_tokens") or call_kwargs[0][1]
    assert used_max_tokens >= 400


def test_generate_handoff_codebase_only(mock_singletons):
    """If there is no narrative but codebase exists, return codebase."""
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_state.read_narrative.return_value = "No state files yet."
    mock_state.read_codebase.return_value = "# Codebase Map\n\n- `src/foo.py`: foo."
    result = generate_handoff(token_budget=2000)
    assert "src/foo.py" in result
    mock_apfel.summarize.assert_not_called()


def test_get_context_reads_state(mock_singletons):
    from src.server import get_context
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_state.read_all.return_value = "## Progress\n- entry\n"
    result = get_context()
    mock_state.read_all.assert_called_once()
    assert "## Progress" in result


def test_summarize_history_falls_back_per_chunk_when_summarize_empty(mock_singletons):
    """When summarize() returns empty string, fallback appends chunk[:500] + ' [...]' (covers line 78)."""
    from src.server import summarize_history
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.summarize.return_value = ""
    result = summarize_history("Some conversation turns here.")
    assert "[...]" in result


def test_set_model_calls_reconfigure(mock_singletons):
    from src.server import set_model
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.model = "gemma4:e4b"
    mock_apfel._base_url = "http://localhost:11434/v1"
    result = set_model("apple-foundationmodel", "http://localhost:11434/v1")
    mock_apfel.reconfigure.assert_called_once_with("apple-foundationmodel", "http://localhost:11434/v1")
    assert "apple-foundationmodel" in result
    assert "gemma4:e4b" in result


def test_set_model_uses_current_url_when_omitted(mock_singletons):
    from src.server import set_model
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.model = "gemma4:e4b"
    mock_apfel._base_url = "http://localhost:11434/v1"
    set_model("apple-foundationmodel")
    # Empty base_url should fall back to current _base_url
    mock_apfel.reconfigure.assert_called_once_with("apple-foundationmodel", "http://localhost:11434/v1")


def test_get_info_returns_model_and_health(mock_singletons):
    from src.server import get_info
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.model = "gemma4:e4b"
    mock_health.return_value = True
    result = get_info()
    assert "gemma4:e4b" in result
    assert "True" in result


def test_get_info_reflects_unhealthy_backend(mock_singletons):
    from src.server import get_info
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.model = "gemma4:e4b"
    mock_health.return_value = False
    result = get_info()
    assert "False" in result


def test_generate_handoff_truncates_when_apfel_down_large_state(mock_singletons):
    """generate_handoff truncates narrative to char_budget when apfel is down and state is large."""
    from src.server import generate_handoff
    mock_apfel, mock_state, mock_health = mock_singletons
    token_budget = 100
    # 100 tokens * 4 chars = 400 chars; use 600 chars to exceed budget
    large_narrative = "y" * 600
    mock_state.read_narrative.return_value = large_narrative
    mock_state.read_codebase.return_value = ""
    mock_health.return_value = False
    result = generate_handoff(token_budget=token_budget)
    assert "truncated" in result
    char_budget = token_budget * 4
    assert result.startswith(large_narrative[:char_budget])


# --- read() tool tests ---

def test_read_missing_file_returns_error(mock_singletons):
    from src.server import read
    result = read("/nonexistent/path/to/file.txt")
    assert "Error" in result


def test_read_prose_short_passthrough(mock_singletons, tmp_path):
    """Short prose files pass through without compression."""
    from src.server import read
    mock_apfel, mock_state, mock_health = mock_singletons
    f = tmp_path / "note.txt"
    f.write_text("hello world")
    result = read(str(f))
    mock_apfel.compress.assert_not_called()
    assert result == "hello world"


def test_read_prose_long_compressed(mock_singletons, tmp_path):
    """Long prose files are compressed via apfel.compress."""
    from src.server import read
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.compress.return_value = "compressed prose"
    f = tmp_path / "note.txt"
    f.write_text("word " * 50)
    result = read(str(f))
    mock_apfel.compress.assert_called_once()
    assert result == "compressed prose"


def test_read_prose_falls_back_when_apfel_down(mock_singletons, tmp_path):
    """Falls back to original text when Ollama is unavailable."""
    from src.server import read
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_health.return_value = False
    original = "word " * 50
    f = tmp_path / "note.txt"
    f.write_text(original)
    result = read(str(f))
    mock_apfel.compress.assert_not_called()
    assert result == original


def test_read_code_file_extracts_skeleton(mock_singletons, tmp_path):
    """Python files go through skeleton extraction, not raw compression."""
    from src.server import read
    mock_apfel, mock_state, mock_health = mock_singletons
    f = tmp_path / "foo.py"
    f.write_text("def greet(name):\n    '''Say hello.'''\n    return f'Hello {name}'\n")
    result = read(str(f))
    # Skeleton extraction should have happened; compress should NOT be called for short skeletons
    mock_apfel.compress.assert_not_called()
    # Skeleton should contain the signature
    assert "greet" in result


def test_read_returns_original_when_compress_empty(mock_singletons, tmp_path):
    """Falls back to original if compress returns empty string."""
    from src.server import read
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.compress.return_value = ""
    f = tmp_path / "note.txt"
    original = "word " * 50
    f.write_text(original)
    result = read(str(f))
    assert result == original


# --- bash() tool tests ---

def test_bash_runs_command(mock_singletons):
    from src.server import bash
    result = bash("echo hello")
    assert "hello" in result


def test_bash_short_output_not_compressed(mock_singletons):
    """Output under 300 tokens is returned as-is without calling compress."""
    from src.server import bash
    mock_apfel, mock_state, mock_health = mock_singletons
    result = bash("echo hi")
    mock_apfel.compress.assert_not_called()
    assert "hi" in result


def test_bash_long_output_compressed(mock_singletons):
    """Output over 300 tokens is compressed when Ollama is available."""
    from src.server import bash
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.compress.return_value = "compressed output"
    # Generate a command that produces > 300 words of output
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="word " * 400,
            stderr="",
            returncode=0,
        )
        result = bash("fake-long-output-cmd")
    mock_apfel.compress.assert_called_once()
    assert result == "compressed output"


def test_bash_long_output_not_compressed_when_apfel_down(mock_singletons):
    """Long output is returned raw when Ollama is down."""
    from src.server import bash
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_health.return_value = False
    long_output = "word " * 400
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=long_output, stderr="", returncode=0)
        result = bash("fake-cmd")
    mock_apfel.compress.assert_not_called()
    assert result == long_output


def test_bash_invalid_command_syntax(mock_singletons):
    """Malformed shell syntax returns an error string."""
    from src.server import bash
    result = bash("echo 'unterminated")
    assert "Error" in result


def test_bash_nonexistent_command(mock_singletons):
    """Running a nonexistent binary returns an error string."""
    from src.server import bash
    result = bash("_nonexistent_binary_xyz_")
    assert "Error" in result


def test_bash_stderr_included_in_output(mock_singletons):
    """stderr is appended to stdout in the result."""
    from src.server import bash
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="out\n", stderr="err\n", returncode=1)
        result = bash("some-cmd")
    assert "out" in result
    assert "err" in result


def test_bash_falls_back_when_compress_empty(mock_singletons):
    """Falls back to raw output if compress returns empty string."""
    from src.server import bash
    mock_apfel, mock_state, mock_health = mock_singletons
    mock_apfel.compress.return_value = ""
    long_output = "word " * 400
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=long_output, stderr="", returncode=0)
        result = bash("fake-cmd")
    assert result == long_output
