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


# ── update_file_summary tests ─────────────────────────────────────────────────

def test_update_file_summary_creates_entry(tmp_path):
    """update_file_summary creates codebase.md with the given entry."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("src/server.py", "MCP server exposing 6 tools.")
    content = (tmp_path / "codebase.md").read_text()
    assert "- `src/server.py`: MCP server exposing 6 tools." in content


def test_update_file_summary_upserts_existing_entry(tmp_path):
    """update_file_summary replaces an existing entry rather than appending."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("src/server.py", "Old description.")
    sm.update_file_summary("src/server.py", "New description.")
    content = (tmp_path / "codebase.md").read_text()
    assert "New description." in content
    assert "Old description." not in content
    assert content.count("src/server.py") == 1


def test_update_file_summary_preserves_other_entries(tmp_path):
    """update_file_summary does not touch entries for other files."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("src/server.py", "Server description.")
    sm.update_file_summary("src/health.py", "Health check module.")
    sm.update_file_summary("src/server.py", "Updated server description.")
    content = (tmp_path / "codebase.md").read_text()
    assert "Updated server description." in content
    assert "Health check module." in content


def test_update_file_summary_strips_null_bytes(tmp_path):
    """update_file_summary sanitizes null bytes from both path and summary."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("src/\x00server.py", "desc\x00ription")
    content = (tmp_path / "codebase.md").read_text()
    assert "\x00" not in content


def test_update_file_summary_skips_empty_inputs(tmp_path):
    """update_file_summary is a no-op when path or summary is empty."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("", "some summary")
    sm.update_file_summary("src/foo.py", "")
    assert not (tmp_path / "codebase.md").exists()


def test_read_all_includes_codebase(tmp_path):
    """read_all includes codebase.md content when it exists."""
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "did something")
    sm.update_file_summary("src/server.py", "The MCP server.")
    result = sm.read_all()
    assert "Codebase" in result
    assert "src/server.py" in result


def test_read_all_without_codebase(tmp_path):
    """read_all works normally when codebase.md doesn't exist."""
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "did something")
    result = sm.read_all()
    assert "did something" in result
    assert "Codebase" not in result


# ── read_narrative tests ──────────────────────────────────────────────────────

def test_read_narrative_excludes_codebase(tmp_path):
    """read_narrative returns VALID_TYPES sections but never includes codebase.md."""
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "narrative entry")
    sm.update_file_summary("src/server.py", "The MCP server.")
    result = sm.read_narrative()
    assert "narrative entry" in result
    assert "src/server.py" not in result
    assert "Codebase" not in result


def test_read_narrative_no_files_returns_placeholder(tmp_path):
    """read_narrative returns the placeholder string when no state files exist."""
    sm = StateManager(state_dir=tmp_path)
    result = sm.read_narrative()
    assert result == "No state files yet."


def test_read_narrative_includes_all_valid_types(tmp_path):
    """read_narrative includes all VALID_TYPES that have content."""
    sm = StateManager(state_dir=tmp_path)
    sm.append("progress", "progress entry")
    sm.append("bug", "bug entry")
    result = sm.read_narrative()
    assert "progress entry" in result
    assert "bug entry" in result


# ── read_codebase tests ───────────────────────────────────────────────────────

def test_read_codebase_returns_empty_when_no_file(tmp_path):
    """read_codebase returns empty string when codebase.md does not exist."""
    sm = StateManager(state_dir=tmp_path)
    assert sm.read_codebase() == ""


def test_read_codebase_returns_entries_verbatim(tmp_path):
    """read_codebase returns file entries exactly as stored."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("src/server.py", "MCP server.")
    sm.update_file_summary("src/health.py", "Health check.")
    result = sm.read_codebase()
    assert "src/server.py" in result
    assert "src/health.py" in result
    assert "MCP server." in result


def test_read_codebase_truncates_to_max_entries(tmp_path):
    """read_codebase returns only the last max_entries entries when the file is large."""
    sm = StateManager(state_dir=tmp_path)
    for i in range(10):
        sm.update_file_summary(f"src/file_{i}.py", f"description {i}")
    result = sm.read_codebase(max_entries=3)
    # Should only have the 3 most recent entries
    entry_lines = [line for line in result.splitlines() if line.startswith("- ")]
    assert len(entry_lines) == 3
    assert "showing last 3 of 10" in result


def test_read_codebase_no_truncation_note_when_within_limit(tmp_path):
    """read_codebase adds no truncation note when entries fit within max_entries."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("src/server.py", "MCP server.")
    result = sm.read_codebase(max_entries=50)
    assert "showing last" not in result


def test_read_codebase_preserves_header(tmp_path):
    """read_codebase always includes the # Codebase Map header line."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("src/server.py", "MCP server.")
    result = sm.read_codebase()
    assert "# Codebase Map" in result


# ---------------------------------------------------------------------------
# _rotate_codebase tests
# ---------------------------------------------------------------------------

def test_rotate_codebase_removes_dead_entries(tmp_path):
    """Entries for paths that no longer exist on disk are pruned."""
    sm = StateManager(state_dir=tmp_path)
    codebase_file = tmp_path / "codebase.md"
    codebase_file.write_text(
        "# Codebase Map\n"
        "- `dead/gone.py`: old summary\n"
        "- `also/missing.py`: another old one\n",
        encoding="utf-8",
    )
    sm._rotate_codebase(codebase_file, root=tmp_path)
    result = codebase_file.read_text(encoding="utf-8")
    assert "dead/gone.py" not in result
    assert "also/missing.py" not in result


def test_rotate_codebase_preserves_live_entries(tmp_path):
    """Entries for files that exist on disk are kept after rotation."""
    sm = StateManager(state_dir=tmp_path)
    live = tmp_path / "src" / "server.py"
    live.parent.mkdir()
    live.write_text("# real file", encoding="utf-8")

    codebase_file = tmp_path / "codebase.md"
    codebase_file.write_text(
        "# Codebase Map\n"
        f"- `src/server.py`: MCP server.\n"
        "- `deleted.py`: gone\n",
        encoding="utf-8",
    )
    sm._rotate_codebase(codebase_file, root=tmp_path)
    result = codebase_file.read_text(encoding="utf-8")
    assert "src/server.py" in result
    assert "deleted.py" not in result


def test_rotate_codebase_preserves_header(tmp_path):
    """# Codebase Map header line survives rotation."""
    sm = StateManager(state_dir=tmp_path)
    codebase_file = tmp_path / "codebase.md"
    codebase_file.write_text(
        "# Codebase Map\n\n- `gone.py`: stale\n",
        encoding="utf-8",
    )
    sm._rotate_codebase(codebase_file, root=tmp_path)
    assert "# Codebase Map" in codebase_file.read_text(encoding="utf-8")


def test_rotate_codebase_fallback_half_keep_when_still_over(tmp_path):
    """Falls back to newest-half when file is still over limit after dead-entry pruning."""
    from src.state_manager import MAX_FILE_SIZE_BYTES
    sm = StateManager(state_dir=tmp_path)

    # Create many real files so dead-entry pruning keeps them all
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    num_files = 300
    for i in range(num_files):
        (src_dir / f"f{i}.py").write_text("x", encoding="utf-8")

    long_summary = "x" * 400
    entries = [f"- `src/f{i}.py`: {long_summary}" for i in range(num_files)]
    content = "# Codebase Map\n" + "\n".join(entries) + "\n"
    codebase_file = tmp_path / "codebase.md"
    codebase_file.write_text(content, encoding="utf-8")
    assert codebase_file.stat().st_size > MAX_FILE_SIZE_BYTES

    sm._rotate_codebase(codebase_file, root=tmp_path)
    result = codebase_file.read_text(encoding="utf-8")
    kept = [l for l in result.splitlines() if l.startswith("- ")]
    assert len(kept) < num_files


def test_no_rotation_under_threshold(tmp_path):
    """update_file_summary does not rotate when file is under 100KB."""
    sm = StateManager(state_dir=tmp_path)
    sm.update_file_summary("src/small.py", "tiny summary")
    codebase_file = tmp_path / "codebase.md"
    assert codebase_file.stat().st_size < 100_000
    result = codebase_file.read_text(encoding="utf-8")
    assert "src/small.py" in result


def test_rotate_codebase_mixed_dead_and_live(tmp_path):
    """Only live-file entries survive; dead entries are removed without touching live ones."""
    sm = StateManager(state_dir=tmp_path)
    live = tmp_path / "keep.py"
    live.write_text("real", encoding="utf-8")

    codebase_file = tmp_path / "codebase.md"
    codebase_file.write_text(
        "# Codebase Map\n"
        "- `keep.py`: live file\n"
        "- `dead1.py`: gone\n"
        "- `dead2.py`: also gone\n",
        encoding="utf-8",
    )
    sm._rotate_codebase(codebase_file, root=tmp_path)
    result = codebase_file.read_text(encoding="utf-8")
    assert "keep.py" in result
    assert "dead1.py" not in result
    assert "dead2.py" not in result
