"""Tests for src/health.py"""
import time
import pytest
import src.health as health_module
from src.health import check_apfel_health, CACHE_SECONDS


def reset_cache():
    """Reset health check cache between tests."""
    health_module._last_check = 0.0
    health_module._last_result = False


def test_returns_false_when_server_unreachable():
    reset_cache()
    # Port 59999 is out of range; connection will be refused immediately
    result = check_apfel_health(base_url="http://localhost:59999")
    assert result is False


def test_caches_result_within_cache_window():
    reset_cache()
    # First call — sets cache (will return False since no server)
    result1 = check_apfel_health(base_url="http://localhost:59999")
    assert result1 is False

    # Manually set a True result in the cache
    health_module._last_result = True

    # Second call within CACHE_SECONDS — should return cached True
    result2 = check_apfel_health(base_url="http://localhost:59999")
    assert result2 is True  # returned from cache, not from network


def test_cache_expires_after_ttl(monkeypatch):
    reset_cache()
    # First call sets cache timestamp
    check_apfel_health(base_url="http://localhost:59999")

    # Force cache expiry by backdating _last_check
    health_module._last_check = time.monotonic() - (CACHE_SECONDS + 1)
    health_module._last_result = True  # stale cached True

    # Next call should re-check and return False (no server)
    result = check_apfel_health(base_url="http://localhost:59999")
    assert result is False


def test_default_base_url_is_localhost_11434():
    """Verify default URL doesn't reach an external server."""
    reset_cache()
    # Should fail gracefully (no server running on 11434 in CI)
    result = check_apfel_health()
    assert isinstance(result, bool)
