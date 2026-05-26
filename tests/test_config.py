"""Tests for src/config.py — state dir derivation, env var overrides, config layering."""
import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import get_state_dir, get_backend_config, get_automation_config, load_config


# ---------------------------------------------------------------------------
# get_state_dir — core isolation guarantee
# ---------------------------------------------------------------------------

def test_state_dir_default_is_under_apfel_home():
    """Default state dir lives under ~/.promptcompactor/projects/."""
    result = get_state_dir(cwd=Path("/some/project"))
    assert str(result).startswith(str(Path.home() / ".apfel" / "projects"))


def test_state_dir_ends_with_state():
    """State dir always ends with /state."""
    result = get_state_dir(cwd=Path("/some/project"))
    assert result.name == "state"


def test_state_dir_hash_is_16_hex_chars():
    """Project hash component is exactly 16 lowercase hex characters."""
    result = get_state_dir(cwd=Path("/some/project"))
    # path: ~/.promptcompactor/projects/<hash>/state
    project_hash = result.parent.name
    assert len(project_hash) == 16
    assert all(c in "0123456789abcdef" for c in project_hash)


def test_state_dir_deterministic():
    """Same cwd always produces same state dir."""
    cwd = Path("/home/user/myproject")
    assert get_state_dir(cwd=cwd) == get_state_dir(cwd=cwd)


def test_state_dir_different_cwds_produce_different_dirs():
    """Different project paths get different state dirs (no collision)."""
    a = get_state_dir(cwd=Path("/projects/alpha"))
    b = get_state_dir(cwd=Path("/projects/beta"))
    assert a != b


def test_state_dir_hash_matches_sha256():
    """Hash is the first 16 chars of sha256 of the resolved cwd string."""
    cwd = Path("/projects/myapp")
    expected_hash = hashlib.sha256(str(cwd.resolve()).encode()).hexdigest()[:16]
    result = get_state_dir(cwd=cwd)
    assert result.parent.name == expected_hash


def test_state_dir_uses_cwd_default_when_not_provided():
    """With no cwd arg, get_state_dir uses Path.cwd()."""
    result_explicit = get_state_dir(cwd=Path.cwd())
    result_default = get_state_dir()
    assert result_explicit == result_default


def test_state_dir_env_override(tmp_path):
    """APFEL_STATE_DIR env var overrides hash-based derivation."""
    with patch.dict(os.environ, {"APFEL_STATE_DIR": str(tmp_path)}):
        result = get_state_dir(cwd=Path("/irrelevant"))
    assert result == tmp_path.resolve()


def test_state_dir_env_override_ignores_cwd(tmp_path):
    """When APFEL_STATE_DIR is set, cwd argument has no effect."""
    with patch.dict(os.environ, {"APFEL_STATE_DIR": str(tmp_path)}):
        a = get_state_dir(cwd=Path("/project/a"))
        b = get_state_dir(cwd=Path("/project/b"))
    assert a == b == tmp_path.resolve()


def test_state_dir_env_override_resolves_path():
    """APFEL_STATE_DIR is resolved (symlinks expanded, made absolute)."""
    with patch.dict(os.environ, {"APFEL_STATE_DIR": "/tmp/../tmp/apfel-test"}):
        result = get_state_dir()
    assert ".." not in str(result)


# ---------------------------------------------------------------------------
# Config layering — env vars, config.json, defaults
# ---------------------------------------------------------------------------

def test_backend_config_uses_env_model():
    """COMPACTOR_MODEL env var overrides config.json model."""
    with patch.dict(os.environ, {"COMPACTOR_MODEL": "test-model"}):
        cfg = get_backend_config()
    assert cfg["model"] == "test-model"


def test_backend_config_uses_env_base_url():
    """COMPACTOR_BASE_URL env var overrides config.json base_url."""
    with patch.dict(os.environ, {"COMPACTOR_BASE_URL": "http://remote:11434/v1"}):
        cfg = get_backend_config()
    assert cfg["base_url"] == "http://remote:11434/v1"


def test_backend_config_defaults_to_gemma():
    """Without env overrides, default model is gemma4:e4b."""
    with patch.dict(os.environ, {}, clear=False):
        env_backup = {}
        for key in ("COMPACTOR_MODEL", "COMPACTOR_BASE_URL"):
            if key in os.environ:
                env_backup[key] = os.environ.pop(key)
        try:
            cfg = get_backend_config()
            assert cfg["model"] == "gemma4:e4b"
        finally:
            os.environ.update(env_backup)


def test_load_config_returns_all_sections():
    """load_config() always has backend, automation, token_budget sections."""
    cfg = load_config()
    assert "backend" in cfg
    assert "automation" in cfg
    assert "token_budget" in cfg


def test_automation_config_has_required_keys():
    """Automation config always contains the expected flags."""
    cfg = get_automation_config()
    for key in ("auto_log_edits", "auto_progress_on_stop", "auto_inject_context_on_start",
                "compact_on_every_prompt", "max_injection_tokens"):
        assert key in cfg, f"Missing key: {key}"


def test_load_config_tolerates_missing_config_file(tmp_path):
    """load_config falls back to defaults when config.json is missing."""
    import src.config as config_module
    original = config_module._CONFIG_PATH
    try:
        config_module._CONFIG_PATH = tmp_path / "nonexistent.json"
        cfg = config_module.load_config()
        assert cfg["backend"]["model"] == "gemma4:e4b"
    finally:
        config_module._CONFIG_PATH = original


def test_load_config_tolerates_malformed_json(tmp_path):
    """load_config falls back to defaults on malformed JSON."""
    import src.config as config_module
    bad_json = tmp_path / "config.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    original = config_module._CONFIG_PATH
    try:
        config_module._CONFIG_PATH = bad_json
        cfg = config_module.load_config()
        assert cfg["backend"]["model"] == "gemma4:e4b"
    finally:
        config_module._CONFIG_PATH = original
