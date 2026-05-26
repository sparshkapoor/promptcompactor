"""Tests for scripts/hook_runner.py — dispatch, daemon, medium path, compress heuristic."""
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).parent.parent))
import scripts.hook_runner as hr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_daemon_thread(port: int) -> threading.Thread:
    """Start a daemon HTTP server on the given port in a background thread."""
    t = threading.Thread(target=hr.cmd_serve, args=(port,), daemon=True)
    t.start()
    time.sleep(0.15)  # wait for socket to bind
    return t


def _daemon_get(port: int, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=2) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


def _daemon_post(port: int, body: str) -> tuple[int, str]:
    data = body.encode("utf-8")
    req = urllib.request.Request(
        f"http://localhost:{port}/run",
        data=data,
        method="POST",
        headers={"Content-Length": str(len(data))},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


# ---------------------------------------------------------------------------
# _dispatch tests
# ---------------------------------------------------------------------------

def test_dispatch_log_progress_writes_to_state():
    """_dispatch('log-progress', [...]) appends to state file."""
    with patch("scripts.hook_runner._make_state") as mk:
        mock_state = MagicMock()
        mk.return_value = mock_state
        with patch("scripts.hook_runner.get_automation_config", return_value={"auto_progress_on_stop": True}):
            hr._dispatch("log-progress", ["hello world"])
    mock_state.append.assert_called_once_with("progress", "hello world")


def test_dispatch_unknown_command_does_not_raise():
    """_dispatch with an unrecognised command logs an error but never raises."""
    hr._dispatch("no-such-command", [])  # must not raise


def test_dispatch_log_edit_missing_arg_does_not_raise():
    """_dispatch('log-edit', []) logs an error but never raises."""
    hr._dispatch("log-edit", [])  # no args — should log error gracefully


def test_dispatch_update_file_summary_missing_arg_does_not_raise():
    hr._dispatch("update-file-summary", [])


def test_dispatch_log_progress_missing_arg_does_not_raise():
    hr._dispatch("log-progress", [])


# ---------------------------------------------------------------------------
# _run_command_captured tests
# ---------------------------------------------------------------------------

def test_run_command_captured_returns_stdout():
    """_run_command_captured captures what the command prints to stdout."""
    with patch("scripts.hook_runner._dispatch") as mock_dispatch:
        def _fake_dispatch(*_):
            print("captured output")
        mock_dispatch.side_effect = _fake_dispatch
        result = hr._run_command_captured("any-cmd", [])
    assert result.strip() == "captured output"


def test_run_command_captured_passes_stdin_data():
    """stdin_data is available as sys.stdin inside the captured command."""
    import sys as _sys
    captured_stdin = []

    with patch("scripts.hook_runner._dispatch") as mock_dispatch:
        def _fake_dispatch(*_):
            captured_stdin.append(_sys.stdin.read())
        mock_dispatch.side_effect = _fake_dispatch
        hr._run_command_captured("any-cmd", [], stdin_data="hello stdin")

    assert captured_stdin[0] == "hello stdin"


def test_run_command_captured_restores_stdout_on_exception():
    """sys.stdout is restored even if the dispatched command raises."""
    import sys as _sys
    real_stdout = _sys.stdout

    with patch("scripts.hook_runner._dispatch", side_effect=RuntimeError("boom")):
        hr._run_command_captured("any-cmd", [])

    assert _sys.stdout is real_stdout


def test_run_command_captured_empty_output_for_silent_command():
    with patch("scripts.hook_runner._dispatch"):  # does nothing → no print
        result = hr._run_command_captured("any-cmd", [])
    assert result == ""


# ---------------------------------------------------------------------------
# Daemon HTTP server tests
# ---------------------------------------------------------------------------

_TEST_PORT_BASE = 17370  # use high ports unlikely to be in use


def test_daemon_ping():
    """GET /ping returns 200 and body 'ok'."""
    port = _TEST_PORT_BASE
    _start_daemon_thread(port)
    status, body = _daemon_get(port, "/ping")
    assert status == 200
    assert body == "ok"


def test_daemon_unknown_get_returns_404():
    port = _TEST_PORT_BASE + 1
    _start_daemon_thread(port)
    status, _ = _daemon_get(port, "/nope")
    assert status == 404


def test_daemon_post_run_dispatches_command():
    """POST /run with 'log-progress hello' dispatches to cmd_log_progress."""
    port = _TEST_PORT_BASE + 2
    _start_daemon_thread(port)

    with patch("scripts.hook_runner._make_state") as mk, \
         patch("scripts.hook_runner.get_automation_config", return_value={"auto_progress_on_stop": True}):
        mock_state = MagicMock()
        mk.return_value = mock_state
        status, _ = _daemon_post(port, "log-progress hello from daemon\n")

    assert status == 200
    mock_state.append.assert_called_once_with("progress", "hello from daemon")


def test_daemon_post_returns_command_stdout():
    """POST /run output body is the command's stdout."""
    port = _TEST_PORT_BASE + 3
    _start_daemon_thread(port)

    with patch("scripts.hook_runner._dispatch") as mock_dispatch:
        def _echo(*_):
            print("echo response")
        mock_dispatch.side_effect = _echo
        status, body = _daemon_post(port, "any-cmd\n")

    assert status == 200
    assert "echo response" in body


def test_daemon_post_unknown_path_returns_404():
    port = _TEST_PORT_BASE + 4
    _start_daemon_thread(port)
    req = urllib.request.Request(
        f"http://localhost:{port}/wrong",
        data=b"x",
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2)
        assert False, "Expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_daemon_port_already_in_use_exits_silently():
    """cmd_serve on an already-bound port must exit without raising."""
    port = _TEST_PORT_BASE + 5
    _start_daemon_thread(port)
    time.sleep(0.1)
    # Second call should exit silently (OSError caught internally)
    original = hr._DAEMON_PORT
    hr._DAEMON_PORT = port
    try:
        hr.cmd_serve()  # must return without raising
    finally:
        hr._DAEMON_PORT = original


def test_daemon_concurrent_requests_dont_corrupt():
    """Two concurrent POST /run requests both complete with status 200."""
    port = _TEST_PORT_BASE + 6
    _start_daemon_thread(port)

    results = []

    def _post():
        # Send a known-harmless command; just verify the daemon responds 200
        status, _ = _daemon_post(port, "unknown-noop-command\n")
        results.append(status)

    t1 = threading.Thread(target=_post)
    t2 = threading.Thread(target=_post)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert all(s == 200 for s in results)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# cmd_generate_handoff medium path tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def patched_handoff():
    """Patch all external deps for cmd_generate_handoff, return (mock_client, mock_health)."""
    mock_client = MagicMock()
    mock_client.summarize.return_value = "summary text"
    mock_health = MagicMock(return_value=True)

    with patch("scripts.hook_runner._make_state", return_value=MagicMock(
        read_narrative=MagicMock(),
        read_codebase=MagicMock(return_value=""),
    )) as mk_state, \
         patch("scripts.hook_runner._make_client", return_value=mock_client), \
         patch("scripts.hook_runner._is_healthy", mock_health), \
         patch("scripts.hook_runner.get_automation_config", return_value={
             "auto_inject_context_on_start": True,
             "max_injection_tokens": 400,
         }):
        yield mk_state, mock_client, mock_health


def test_medium_path_skips_gemma_for_small_overage(patched_handoff, capsys):
    """Narrative at 2× budget triggers medium path — Gemma not called."""
    mk_state, mock_client, _ = patched_handoff
    # 800 tokens: over 400-token budget but within 3× budget (1200)
    narrative = "word " * 640  # 640 * 5 chars = 3200 chars ≈ 800 tokens (within 3× budget)
    mk_state.return_value.read_narrative.return_value = narrative

    hr.cmd_generate_handoff()

    mock_client.summarize.assert_not_called()
    captured = capsys.readouterr()
    assert len(captured.out) > 0


def test_fast_path_skips_gemma_when_under_budget(patched_handoff, capsys):
    """Narrative under token_budget (400 tokens) uses fast path — no Gemma."""
    mk_state, mock_client, _ = patched_handoff
    narrative = "word " * 100  # ~100 tokens — well under 400
    mk_state.return_value.read_narrative.return_value = narrative

    hr.cmd_generate_handoff()

    mock_client.summarize.assert_not_called()
    captured = capsys.readouterr()
    assert narrative in captured.out


def test_gemma_path_called_for_large_narrative(patched_handoff):
    """Narrative over 3× budget triggers Gemma summarization."""
    mk_state, mock_client, _ = patched_handoff
    # 5000 tokens — well over 1200-token medium-path threshold
    narrative = ("- [2026-01-01] some progress entry\n") * 600
    mk_state.return_value.read_narrative.return_value = narrative

    hr.cmd_generate_handoff()

    mock_client.summarize.assert_called_once()


def test_medium_path_takes_tail_of_narrative(patched_handoff, capsys):
    """Medium path keeps the tail (most recent entries), not the head."""
    mk_state, mock_client, _ = patched_handoff
    # Build narrative: old content first, then distinctive recent marker
    old_part = "old entry\n" * 200
    recent_marker = "RECENT_MARKER_XYZ " * 10
    narrative = old_part + recent_marker
    mk_state.return_value.read_narrative.return_value = narrative

    hr.cmd_generate_handoff()

    captured = capsys.readouterr()
    assert "RECENT_MARKER_XYZ" in captured.out


# ---------------------------------------------------------------------------
# _is_compressible heuristic tests (real-world prompt patterns)
# ---------------------------------------------------------------------------

def test_compressible_verbose_prose():
    text = (
        "I want to understand what the current architecture looks like and whether "
        "we need to refactor the state manager to support multiple concurrent writers "
        "before we can ship the next release. Can you walk me through the key design "
        "decisions and any outstanding issues that might block us?"
    )
    assert hr._is_compressible(text) is True


def test_not_compressible_short_message():
    assert hr._is_compressible("yes") is False
    assert hr._is_compressible("ok sounds good") is False


def test_not_compressible_code_block():
    text = "```python\ndef foo():\n    return 42\n```\n" * 10
    assert hr._is_compressible(text) is False


def test_not_compressible_python_source():
    text = "\n".join([
        "import sys",
        "from pathlib import Path",
        "def main():",
        "    pass",
        "class Foo:",
        "    def bar(self):",
        "        return 1",
    ] * 8)
    assert hr._is_compressible(text) is False


def test_not_compressible_numbered_list():
    text = "\n".join([f"{i}. Do the thing number {i} carefully" for i in range(1, 20)])
    assert hr._is_compressible(text) is False


def test_not_compressible_over_400_words():
    text = "this is a normal word " * 401
    assert hr._is_compressible(text) is False


def test_compressible_borderline_40_words():
    # 39 words → False; 41 words → True (assuming no code indicators)
    short = "word " * 39
    long_ = "word " * 41
    assert hr._is_compressible(short) is False
    assert hr._is_compressible(long_) is True


# ---------------------------------------------------------------------------
# cmd_log_turn_if_edited tests
# ---------------------------------------------------------------------------

def test_log_turn_if_edited_logs_when_flag_present(tmp_path):
    """Appends 'Turn completed' and removes the flag when .edit_this_turn exists."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    flag = state_dir / ".edit_this_turn"
    flag.touch()

    with patch("scripts.hook_runner.get_state_dir", return_value=state_dir), \
         patch("scripts.hook_runner.get_automation_config",
               return_value={"auto_progress_on_stop": True}):
        hr.cmd_log_turn_if_edited()

    assert not flag.exists()
    progress = (state_dir / "progress.md").read_text()
    assert "Turn completed" in progress


def test_log_turn_if_edited_silent_when_no_flag(tmp_path):
    """Does nothing when .edit_this_turn flag is absent."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with patch("scripts.hook_runner.get_state_dir", return_value=state_dir), \
         patch("scripts.hook_runner.get_automation_config",
               return_value={"auto_progress_on_stop": True}):
        hr.cmd_log_turn_if_edited()

    assert not (state_dir / "progress.md").exists()


def test_log_turn_if_edited_respects_automation_flag(tmp_path):
    """Skips logging when auto_progress_on_stop is False, even if flag is set."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / ".edit_this_turn").touch()

    with patch("scripts.hook_runner.get_state_dir", return_value=state_dir), \
         patch("scripts.hook_runner.get_automation_config",
               return_value={"auto_progress_on_stop": False}):
        hr.cmd_log_turn_if_edited()

    assert not (state_dir / "progress.md").exists()


def test_log_edit_sets_sidecar_flag(tmp_path):
    """cmd_log_edit creates .edit_this_turn in the state dir."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    src_file = tmp_path / "foo.py"
    src_file.write_text("x = 1", encoding="utf-8")

    with patch("scripts.hook_runner.get_state_dir", return_value=state_dir), \
         patch("scripts.hook_runner.get_automation_config",
               return_value={"auto_log_edits": True}), \
         patch("scripts.hook_runner._is_healthy", return_value=False):
        hr.cmd_log_edit(str(src_file))

    assert (state_dir / ".edit_this_turn").exists()


def test_dispatch_log_turn_if_edited():
    """_dispatch routes 'log-turn-if-edited' to cmd_log_turn_if_edited."""
    with patch("scripts.hook_runner.cmd_log_turn_if_edited") as mock:
        hr._dispatch("log-turn-if-edited", [])
    mock.assert_called_once()
