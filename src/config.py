"""
config.py — Load config.json from the project root.

Priority order for backend settings (highest wins):
  1. Environment variables (COMPACTOR_MODEL, COMPACTOR_BASE_URL)
  2. config.json values
  3. Hardcoded fallback defaults

State directory resolution order (highest wins):
  1. APFEL_STATE_DIR env var
  2. ~/.promptcompactor/projects/<sha256(cwd)[:16]>/state/

Callers should use get_backend_config(), get_token_budget(), and get_state_dir()
rather than reading config.json or constructing paths themselves.
"""

import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("prompt-compactor.config")

_PROJECT_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.json"

# Fallback defaults if config.json is missing or malformed
_DEFAULTS: dict = {
    "backend": {
        "base_url": "http://localhost:11434/v1",
        "model": "gemma4:e4b",
        "max_context_tokens": 128000,
    },
    "automation": {
        "auto_log_edits": True,
        "auto_progress_on_stop": True,
        "auto_inject_context_on_start": True,
        "compact_on_every_prompt": False,
        "max_injection_tokens": 400,
        "extractive_threshold": 500,   # tokens; pre-filter above this, skip below
        "quality_check": False,        # double-check compression with a verify call
    },
    "token_budget": {
        "system_prompt": 300,
        "response_reserve": 1000,
        "safety_margin": 300,
    },
}


def _load_raw() -> dict:
    """Load config.json once. Returns defaults on any error."""
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("config.json not found, using defaults")
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to parse config.json ({type(e).__name__}: {e}), using defaults")
        return {}


def _merge(base: dict, override: dict) -> dict:
    """Shallow-merge override into base (one level deep)."""
    result = {**base}
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            result[k] = {**base[k], **v}
        else:
            result[k] = v
    return result


def load_config() -> dict:
    """Return the merged config (defaults + config.json)."""
    return _merge(_DEFAULTS, _load_raw())


def get_backend_config() -> dict:
    """
    Return backend settings with env-var overrides applied.

    Returns dict with keys: base_url, model, max_context_tokens.
    Env vars COMPACTOR_BASE_URL and COMPACTOR_MODEL take highest priority.
    """
    cfg = load_config()["backend"]
    return {
        "base_url": os.environ.get("COMPACTOR_BASE_URL", cfg["base_url"]),
        "model": os.environ.get("COMPACTOR_MODEL", cfg["model"]),
        "max_context_tokens": int(cfg["max_context_tokens"]),
    }


def get_token_budget() -> dict:
    """Return token_budget section from config."""
    return load_config()["token_budget"]


def get_max_input_tokens() -> int:
    """
    Calculate max input tokens for a single LLM call.

    = max_context_tokens - system_prompt - response_reserve - safety_margin
    """
    backend = get_backend_config()
    budget = get_token_budget()
    result = (
        backend["max_context_tokens"]
        - budget["system_prompt"]
        - budget["response_reserve"]
        - budget["safety_margin"]
    )
    # Never return a nonsensical value if config is misconfigured
    return max(result, 500)


def get_automation_config() -> dict:
    """Return automation flags from config."""
    return load_config()["automation"]


def get_state_dir(cwd: Path | None = None) -> Path:
    """
    Return the state directory for the current project.

    Resolution order:
      1. APFEL_STATE_DIR env var (absolute path, used as-is)
      2. ~/.promptcompactor/projects/<sha256(cwd)[:16]>/state/

    The per-project hash ensures each repo gets its own isolated state
    without any per-project config or file placement.
    """
    env_override = os.environ.get("APFEL_STATE_DIR")
    if env_override:
        return Path(env_override).resolve()

    project_path = str((cwd or Path.cwd()).resolve())
    project_hash = hashlib.sha256(project_path.encode()).hexdigest()[:16]
    return Path.home() / ".apfel" / "projects" / project_hash / "state"
