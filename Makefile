.PHONY: help venv install install-dev clean clean-all test test-unit test-integration test-e2e test-all typecheck run eval admin-migrate

# ---- Configuration ---------------------------------------------------------

PYTHON       ?= python3
VENV         ?= .venv
VENV_PYTHON  := $(VENV)/bin/python
VENV_PIP     := $(VENV)/bin/pip

# Native-library thread hygiene for the test tiers (ADR 0052).
#
# Second layer, not the fix. Three separate copies of `libomp.dylib`
# ship in this venv — torch, faiss, and scikit-learn each vendor one —
# and torch defaults to one OpenMP thread per core; concurrent MiniLM
# encodes then abort the interpreter in the OpenMP barrier (exit 139,
# no traceback, a macOS crash-reporter dialog). The actual containment
# is `torch.set_num_threads(1)` inside `src/tools/embeddings.py`,
# because it also covers the callers that never touch this file: a
# bare `pytest` in CI, `uvicorn` in the container, `python -m
# src.main` typed by hand. What this variable adds is faiss's and
# scikit-learn's own libomp copies, which initialize at import — long
# before any Python code of ours runs.
#
# TOKENIZERS_PARALLELISM=false is unrelated to the crash (measured: it
# does not prevent it). It silences the HuggingFace fast-tokenizer
# fork warning, which the library prints as a paragraph into every
# test log before disabling the pool itself.
TEST_ENV := OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false

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
	@echo "  make eval              Run full benchmark eval (QUERIES=id1,id2 to filter)"
	@echo "  make admin-migrate     Report/repair legacy NULL-owner rows (ARGS='...')"
	@echo "  make clean             Remove venv, caches, build artifacts"
	@echo "                         (keeps .cache/checkpoints.sqlite — graph state)"
	@echo "  make clean-all         clean + delete graph checkpoints (unresumable)"

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
	$(TEST_ENV) $(VENV_PYTHON) -m pytest -m unit tests/ -v

test-integration:  ## Integration tier: external libs on fixtures
	$(TEST_ENV) $(VENV_PYTHON) -m pytest -m integration tests/ -v

test-e2e:  ## E2E tier: full workflow with cassettes
	$(TEST_ENV) $(VENV_PYTHON) -m pytest -m e2e tests/ -v

test-all:  ## Every tier
	$(TEST_ENV) $(VENV_PYTHON) -m pytest tests/ -v

typecheck:  ## Run mypy on the src tree
	$(VENV_PYTHON) -m mypy src/

run:  ## Run the agent: make run QUERY='your question'
	@if [ -z "$(QUERY)" ]; then \
		echo "Usage: make run QUERY='your research question'"; exit 2; \
	fi
	$(VENV_PYTHON) -m src.main "$(QUERY)"

eval:  ## Batch-run the benchmark; make eval QUERIES=id1,id2 to filter
	$(VENV_PYTHON) -m src.eval.runner $(if $(QUERIES),--queries $(QUERIES),)

admin-migrate:  ## Admin: report/repair legacy NULL-owner rows (ARGS='report --store all')
	$(VENV_PYTHON) -m src.api.admin_migrate $(ARGS)

# `.cache/` holds two different things and only one of them is a
# cache. `.cache/pdfs/` is re-derivable from arxiv.org; `.cache/
# checkpoints.sqlite` is LangGraph's durable graph state — the
# workflow's resume point, including any run paused at the HITL
# breakpoint (ADR 0052). Deleting the latter under a target named
# "clean" is destroying job state, so `clean` now leaves it alone and
# `clean-all` is the target that says out loud that it removes it.
clean:  ## Remove venv, caches, build artifacts (keeps graph checkpoints)
	rm -rf $(VENV) .mypy_cache .pytest_cache .cache/pdfs build dist *.egg-info
	find . -type d -name __pycache__ -not -path './$(VENV)/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -not -path './$(VENV)/*' -delete

clean-all: clean  ## clean + delete LangGraph checkpoints (unresumable after this)
	rm -rf .cache
