import logging
import time
import urllib.request
import urllib.error

logger = logging.getLogger("apfel-context.health")

_last_check: float = 0.0
_last_result: bool = False
CACHE_SECONDS = 10.0  # Don't check more often than every 10s


def check_apfel_health(base_url: str = "http://localhost:11434") -> bool:
    """Check if apfel server is running and healthy.
    Caches result for CACHE_SECONDS to avoid excessive requests."""
    global _last_check, _last_result

    now = time.monotonic()
    if now - _last_check < CACHE_SECONDS:
        return _last_result

    # Try /health first (apfel server), fall back to / (Ollama)
    for path in ["/health", "/"]:
        try:
            req = urllib.request.Request(f"{base_url}{path}", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    _last_result = True
                    _last_check = now
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            continue

    _last_result = False
    _last_check = now
    logger.warning("apfel health check failed — server may not be running")
    return False
