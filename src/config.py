"""
config.py — Load config.json from the project root.

Priority order for backend settings (highest wins):
  1. Environment variables (APFEL_MODEL, APFEL_BASE_URL)
  2. config.json values
  3. Hardcoded fallback defaults

Callers should use get_backend_config() and get_token_budget() rather than
reading config.json themselves.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("apfel-context.config")

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
    Env vars APFEL_BASE_URL and APFEL_MODEL take highest priority.
    """
    cfg = load_config()["backend"]
    return {
        "base_url": os.environ.get("APFEL_BASE_URL", cfg["base_url"]),
        "model": os.environ.get("APFEL_MODEL", cfg["model"]),
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
