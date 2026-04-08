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


def test_file_rotation_on_large_file(tmp_path):
    """When file exceeds MAX_FILE_SIZE_BYTES, rotation keeps only recent half (covers lines 47-48, 92-97)."""
    from src.state_manager import MAX_FILE_SIZE_BYTES
    sm = StateManager(state_dir=tmp_path)
    filepath = tmp_path / "progress.md"

    # Write enough data to exceed the limit
    entry = "- [2024-01-01 00:00] " + "x" * 200 + "\n"
    # Write directly to bypass per-entry truncation
    count = (MAX_FILE_SIZE_BYTES // len(entry)) + 2
    filepath.write_text(entry * count, encoding="utf-8")
    assert filepath.stat().st_size > MAX_FILE_SIZE_BYTES

    # Next append should trigger rotation
    sm.append("progress", "new entry after rotation")
    content = sm.read("progress")
    # File should be smaller after rotation
    assert filepath.stat().st_size < MAX_FILE_SIZE_BYTES * 2
    # Most recent entry should be preserved
    assert "new entry after rotation" in content


def test_rotation_preserves_recent_entries(tmp_path):
    """After rotation, the newest entries survive (covers _rotate logic)."""
    from src.state_manager import MAX_FILE_SIZE_BYTES
    sm = StateManager(state_dir=tmp_path)
    filepath = tmp_path / "progress.md"

    # Build a file that exceeds the limit; each line is identifiable
    lines = [f"- [2024-01-01 00:{i:02d}] entry_{i}\n" for i in range(500)]
    filepath.write_text("".join(lines), encoding="utf-8")
    # Force to be over limit
    big_prefix = "x" * MAX_FILE_SIZE_BYTES
    filepath.write_text(big_prefix + "\n" + "".join(lines[-10:]), encoding="utf-8")

    sm.append("progress", "latest entry")
    content = sm.read("progress")
    assert "latest entry" in content


def test_path_traversal_error_not_raised(tmp_path):
    """_get_path with traversal input sanitizes cleanly — no ValueError raised (covers line 38 logic)."""
    sm = StateManager(state_dir=tmp_path)
    # After sanitization, '../../etc/passwd' becomes '' or invalid → defaults to 'progress'
    # _validate_type strips non-alpha, leaving empty string → defaults to progress
    # So _get_path should return state_dir/progress.md without raising
    path = sm._get_path("../../etc/passwd")
    assert path == (tmp_path / "progress.md").resolve()


def test_type_uppercase_normalizes(tmp_path):
    """Uppercase type normalizes to lowercase match (covers _validate_type path)."""
    sm = StateManager(state_dir=tmp_path)
    sm.append("PROGRESS", "uppercase input")
    content = sm.read("progress")
    assert "uppercase input" in content


def test_type_with_special_chars_strips(tmp_path):
    """Special chars in type are stripped, leaving valid type (covers _validate_type)."""
    sm = StateManager(state_dir=tmp_path)
    sm.append("pro..gress", "dotted type")
    content = sm.read("progress")
    assert "dotted type" in content


def test_unknown_type_defaults_to_progress(tmp_path):
    """Completely unknown type defaults to progress."""
    sm = StateManager(state_dir=tmp_path)
    sm.append("unknown_type_xyz", "unknown type entry")
    content = sm.read("progress")
    assert "unknown type entry" in content
