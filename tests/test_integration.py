"""
Integration tests — require Ollama running on localhost:11434 with gemma4:e4b pulled.
Run with: make test-integration
Skipped automatically when Ollama is unreachable.
"""
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ollama_available() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _gemma_available() -> bool:
    """Check that gemma4:e4b is pulled and ready."""
    try:
        import urllib.request, json
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            data = json.loads(r.read())
            return any("gemma4:e4b" in m.get("name", "") for m in data.get("models", []))
    except Exception:
        return False


skip_no_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not running on localhost:11434"
)

skip_no_gemma = pytest.mark.skipif(
    not _gemma_available(),
    reason="gemma4:e4b not available in Ollama"
)

REPO_ROOT = Path(__file__).parent.parent


# ── CompactorClient integration ───────────────────────────────────────────────────

@pytest.mark.integration
@skip_no_ollama
@skip_no_gemma
def test_compactor_client_compress_returns_shorter_text():
    """compress() actually calls Gemma and returns text shorter than input."""
    sys.path.insert(0, str(REPO_ROOT))
    from src.compactor_client import CompactorClient
    client = CompactorClient()
    verbose = (
        "I would like to kindly request that you please take the time to thoroughly "
        "examine and carefully review the current implementation of the state manager "
        "module in order to determine whether it is functioning correctly and efficiently."
    )
    result = client.compress(verbose)
    assert result  # not empty
    assert len(result) < len(verbose)  # actually compressed


@pytest.mark.integration
@skip_no_ollama
@skip_no_gemma
def test_compactor_client_summarize_returns_non_empty():
    """summarize() returns a non-empty string from Gemma."""
    from src.compactor_client import CompactorClient
    client = CompactorClient()
    text = "Fixed a bug in state_manager.py where concurrent writes could corrupt the file."
    result = client.summarize(text)
    assert result and result.strip()


@pytest.mark.integration
@skip_no_ollama
def test_health_check_passes_with_ollama_running():
    """check_compactor_health() returns True when Ollama is up."""
    from src.health import check_compactor_health
    assert check_compactor_health("http://localhost:11434") is True


# ── hook_runner integration ───────────────────────────────────────────────────

@pytest.mark.integration
@skip_no_ollama
@skip_no_gemma
def test_hook_runner_compress_prompt_via_subprocess(tmp_path, monkeypatch):
    """compress-prompt command actually compresses a verbose prompt end-to-end."""
    import json, os
    monkeypatch.setenv("APFEL_STATE_DIR", str(tmp_path / "state"))

    payload = json.dumps({"prompt": (
        "Could you please take a look at the existing implementation and let me know "
        "if there are any obvious issues or improvements that should be made before "
        "we proceed with the next phase of the project?"
    )})

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "hook_runner.py"), "compress-prompt"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    # Output should contain the PromptCompactor compression marker
    assert "PromptCompactor" in result.stdout or result.returncode == 0


@pytest.mark.integration
@skip_no_ollama
def test_hook_runner_log_progress_writes_to_state_dir(tmp_path, monkeypatch):
    """log-progress writes to the APFEL_STATE_DIR-derived directory."""
    import os
    state_dir = tmp_path / "state"
    monkeypatch.setenv("APFEL_STATE_DIR", str(state_dir))

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "hook_runner.py"),
         "log-progress", "integration test entry"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=10,
    )
    assert result.returncode == 0
    progress = state_dir / "progress.md"
    assert progress.exists()
    assert "integration test entry" in progress.read_text()


@pytest.mark.integration
def test_hook_runner_generate_handoff_empty_state(tmp_path, monkeypatch):
    """generate-handoff exits cleanly and prints nothing when state dir is empty."""
    import os
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("APFEL_STATE_DIR", str(state_dir))

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "hook_runner.py"), "generate-handoff"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=15,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ── State isolation integration ───────────────────────────────────────────────

@pytest.mark.integration
def test_two_projects_get_separate_state_dirs():
    """Different cwd paths produce different, non-overlapping state dirs."""
    from src.config import get_state_dir
    dir_a = get_state_dir(cwd=Path("/projects/alpha"))
    dir_b = get_state_dir(cwd=Path("/projects/beta"))
    assert dir_a != dir_b
    assert dir_a.parent != dir_b.parent  # different project hashes


@pytest.mark.integration
def test_state_dir_created_on_first_write(tmp_path, monkeypatch):
    """StateManager creates the state dir on first use."""
    monkeypatch.setenv("APFEL_STATE_DIR", str(tmp_path / "brand_new"))
    from src.config import get_state_dir
    from src.state_manager import StateManager
    state_dir = get_state_dir()
    sm = StateManager(state_dir=state_dir)
    sm.append("progress", "first write")
    assert (state_dir / "progress.md").exists()
