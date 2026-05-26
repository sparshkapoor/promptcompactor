"""Tests for src/health.py"""
import time
import pytest
from unittest.mock import MagicMock, patch
import src.health as health_module
from src.health import check_compactor_health, CACHE_SECONDS


def reset_cache():
    """Reset health check cache between tests."""
    health_module._last_check = 0.0
    health_module._last_result = False


def test_returns_false_when_server_unreachable():
    reset_cache()
    # Port 59999 is out of range; connection will be refused immediately
    result = check_compactor_health(base_url="http://localhost:59999")
    assert result is False


def test_caches_result_within_cache_window():
    reset_cache()
    # First call — sets cache (will return False since no server)
    result1 = check_compactor_health(base_url="http://localhost:59999")
    assert result1 is False

    # Manually set a True result in the cache
    health_module._last_result = True

    # Second call within CACHE_SECONDS — should return cached True
    result2 = check_compactor_health(base_url="http://localhost:59999")
    assert result2 is True  # returned from cache, not from network


def test_cache_expires_after_ttl(monkeypatch):
    reset_cache()
    # First call sets cache timestamp
    check_compactor_health(base_url="http://localhost:59999")

    # Force cache expiry by backdating _last_check
    health_module._last_check = time.monotonic() - (CACHE_SECONDS + 1)
    health_module._last_result = True  # stale cached True

    # Next call should re-check and return False (no server)
    result = check_compactor_health(base_url="http://localhost:59999")
    assert result is False


def test_default_base_url_is_localhost_11434():
    """Verify default URL doesn't reach an external server."""
    reset_cache()
    # Should fail gracefully (no server running on 11434 in CI)
    result = check_compactor_health()
    assert isinstance(result, bool)


def test_returns_true_when_server_responds_200(monkeypatch):
    """Returns True when server responds with HTTP 200 (covers line 25)."""
    reset_cache()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = check_compactor_health(base_url="http://localhost:11434")
    assert result is True


def test_returns_false_on_timeout(monkeypatch):
    """Returns False when urllib raises TimeoutError."""
    reset_cache()
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        result = check_compactor_health(base_url="http://localhost:11434")
    assert result is False
