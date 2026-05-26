PYTHON := .venv/bin/python
PYTEST  := $(PYTHON) -m pytest

.PHONY: all check test test-unit test-integration lint install uninstall clean help

all: check

# ── CI gate ──────────────────────────────────────────────────────────────────

check: lint test-unit
	@echo "✓ All checks passed"

# ── Tests ─────────────────────────────────────────────────────────────────────

test: test-unit test-integration

test-unit:
	$(PYTEST) -m "not integration" --tb=short -q

test-integration:
	$(PYTEST) -m integration --tb=short -q

# ── Lint ──────────────────────────────────────────────────────────────────────

lint:
	$(PYTHON) -m py_compile src/*.py scripts/hook_runner.py
	@echo "✓ Syntax OK"

# ── Install / Uninstall ───────────────────────────────────────────────────────

install:
	@bash scripts/install.sh

uninstall:
	@bash scripts/uninstall.sh

# ── Housekeeping ──────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

help:
	@echo "make check          — lint + unit tests (CI gate)"
	@echo "make test           — unit + integration tests"
	@echo "make test-unit      — unit tests only (no Ollama needed)"
	@echo "make test-integration — integration tests (requires Ollama)"
	@echo "make lint           — syntax check"
	@echo "make install        — run scripts/install.sh"
	@echo "make uninstall      — run scripts/uninstall.sh"
	@echo "make clean          — remove __pycache__ and .pytest_cache"
