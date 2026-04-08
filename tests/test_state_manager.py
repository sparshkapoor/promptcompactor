"""Tests for src/state_manager.py"""
import pytest
from pathlib import Path
from src.state_manager import StateManager, VALID_TYPES


def test_append_and_read(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "Implemented feature X")
    content = sm.read("progress")
    assert "Implemented feature X" in content


def test_timestamps_present(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "Check timestamp")
    content = sm.read("progress")
    # Timestamps are formatted as [YYYY-MM-DD HH:MM]
    import re
    assert re.search(r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]', content)


def test_read_all_formats_sections(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "Done task")
    sm.append("bug", "Found issue")
    result = sm.read_all()
    assert "## Progress" in result
    assert "## Bug" in result
    assert "Done task" in result
    assert "Found issue" in result


def test_path_traversal_defaults_to_progress(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    # Attempt path traversal — should be sanitized to "progress"
    sm.append("../../etc/passwd", "malicious content")
    # File should be written to progress.md, not traversed
    progress_file = tmp_path / "progress.md"
    assert progress_file.exists()
    # No file outside tmp_path should have been created
    etc_passwd = Path("/etc/passwd_test")
    assert not etc_passwd.exists()


def test_null_bytes_stripped(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "clean\x00content\x00here")
    content = sm.read("progress")
    assert "\x00" not in content
    assert "cleancontenthere" in content


def test_clear_removes_content(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "Something")
    sm.clear("progress")
    content = sm.read("progress")
    assert content == ""


def test_clear_all_removes_all(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    for t in VALID_TYPES:
        sm.append(t, f"Entry for {t}")
    sm.clear_all()
    for t in VALID_TYPES:
        assert sm.read(t) == ""


def test_content_over_5000_chars_truncated(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    long_content = "x" * 6000
    sm.append("progress", long_content)
    content = sm.read("progress")
    # The stored content must include the truncation marker
    assert "[... truncated ...]" in content
    # And must not contain more than 5000 + marker chars of our original content
    assert "x" * 5001 not in content


def test_nonexistent_file_returns_empty_string(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    result = sm.read("progress")
    assert result == ""


def test_read_all_no_files_returns_placeholder(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    result = sm.read_all()
    assert result == "No state files yet."


def test_invalid_type_defaults_to_progress(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    sm.append("invalid_type_xyz", "Should become progress")
    content = sm.read("progress")
    assert "Should become progress" in content


def test_append_multiple_entries(tmp_path):
    sm = StateManager(state_dir=tmp_path)
    sm.append("decision", "Chose PostgreSQL")
    sm.append("decision", "Chose FastAPI")
    content = sm.read("decision")
    assert "Chose PostgreSQL" in content
    assert "Chose FastAPI" in content


def test_read_returns_empty_for_non_utf8_file(tmp_path):
    """A state file with invalid UTF-8 bytes should return empty string, not raise."""
    sm = StateManager(state_dir=tmp_path)
    bad_file = tmp_path / "progress.md"
    bad_file.write_bytes(b"valid prefix \xff\xfe invalid bytes")
    result = sm.read("progress")
    assert result == ""
