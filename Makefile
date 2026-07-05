.PHONY: help venv install install-dev clean test test-unit test-integration test-e2e test-all typecheck run

# ---- Configuration ---------------------------------------------------------

PYTHON       ?= python3
VENV         ?= .venv
VENV_PYTHON  := $(VENV)/bin/python
VENV_PIP     := $(VENV)/bin/pip

# ---- Targets ---------------------------------------------------------------

help:  ## Show this help
	@echo "arxiv-research-agent — common targets"
	@echo ""
	@echo "  make venv              Create a fresh $(VENV) (destroys existing)"
	@echo "  make install           Create venv + install runtime deps (editable)"
	@echo "  make install-dev       Create venv + install runtime and dev deps"
	@echo ""
	@echo "  make test              Run the unit tier (default per-PR check)"
	@echo "  make test-unit         Run unit tests (pytest -m unit)"
	@echo "  make test-integration  Run integration tests (pytest -m integration)"
	@echo "  make test-e2e          Run e2e tests (pytest -m e2e)"
	@echo "  make test-all          Run every tier (unit + integration + e2e)"
	@echo "  make typecheck         Run mypy on src/"
	@echo ""
	@echo "  make run QUERY='...'   Run the agent on QUERY"
	@echo "  make clean             Remove venv, caches, build artifacts"

venv:  ## Create a fresh venv (destroys existing)
	rm -rf $(VENV)
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip

install: venv  ## venv + runtime deps
	$(VENV_PIP) install -e .

install-dev: venv  ## venv + runtime deps + dev deps (pytest, mypy)
	$(VENV_PIP) install -e ".[dev]"

test: test-unit  ## Default: run unit tier

test-unit:  ## Unit tier: pure functions, no I/O
	$(VENV_PYTHON) -m pytest -m unit tests/ -v

test-integration:  ## Integration tier: external libs on fixtures
	$(VENV_PYTHON) -m pytest -m integration tests/ -v

test-e2e:  ## E2E tier: full workflow with cassettes
	$(VENV_PYTHON) -m pytest -m e2e tests/ -v

test-all:  ## Every tier
	$(VENV_PYTHON) -m pytest tests/ -v

typecheck:  ## Run mypy on the src tree
	$(VENV_PYTHON) -m mypy src/

run:  ## Run the agent: make run QUERY='your question'
	@if [ -z "$(QUERY)" ]; then \
		echo "Usage: make run QUERY='your research question'"; exit 2; \
	fi
	$(VENV_PYTHON) -m src.main "$(QUERY)"

clean:  ## Remove venv, caches, build artifacts
	rm -rf $(VENV) .mypy_cache .pytest_cache .cache build dist *.egg-info
	find . -type d -name __pycache__ -not -path './$(VENV)/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -not -path './$(VENV)/*' -delete
