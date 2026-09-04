.PHONY: help venv install install-dev clean clean-all test test-unit test-integration test-e2e test-all test-cov test-cov-diff test-security test-property test-fault typecheck run eval simulate-learner record-learning-fixtures admin-migrate

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
#
# PYTHONHASHSEED pins the parent interpreter's hash randomization.
# `tests/conftest.py` exports it too, but CPython reads it once at
# startup, so setting it from inside the process only reaches the
# subprocesses the suite spawns — the parent has to be pinned here
# (ADR 0065).
TEST_ENV := OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONHASHSEED=0

# Every gate that spends nothing says so out loud. `local-preview-disabled`
# is an invalid key by construction, and `tests/conftest.py` denies the
# Anthropic client constructor on top of it — belt and braces, because
# this repository has already shipped a test suite that reached
# api.anthropic.com on every run without anyone noticing (ADR 0065).
ZERO_SPEND := ANTHROPIC_API_KEY=local-preview-disabled

# ---- Coverage floors (ADR 0065) --------------------------------------------
#
# Measured, not aspirational: each number is the value observed when the
# gate was adopted, rounded down to the whole percent. The rule is
# **ratchet up only** — raising one is a normal PR, lowering one needs
# the reason written in the PR body (docs/testing.md, "Coverage policy").
#
# The project floor lives in pyproject.toml because coverage.py's
# `fail_under` is global; these four are per-package because a project
# number can stay flat while the package that matters rots underneath it.
COV_API      := 86
COV_AGENTS   := 92
COV_SECURITY := 97
COV_EVAL     := 91

# Patch coverage — the lines a branch adds or changes, not the project.
# Higher than any floor above on purpose: new code has no legacy excuse,
# and Google's published finding is that project coverage improves
# logarithmically while patch coverage is where the gain actually lives.
COV_DIFF     := 90

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
	@echo "  make test-e2e          Run e2e tests, zero spend (pytest -m e2e)"
	@echo "  make test-all          Run every tier (unit + integration + e2e)"
	@echo "  make test-cov          Coverage over src/, project + per-package floors"
	@echo "  make test-cov-diff     Patch coverage for this branch vs origin/main"
	@echo "  make test-security     Tests that assert a security boundary"
	@echo "  make test-property     Hypothesis invariant tests (empty until WO-A05)"
	@echo "  make test-fault        Tests that assert behaviour under failure"
	@echo "  make typecheck         Run mypy on src/"
	@echo ""
	@echo "  make run QUERY='...'   Run the agent on QUERY"
	@echo "  make eval              Run full benchmark eval (QUERIES=id1,id2 to filter)"
	@echo "  make simulate-learner  Scripted learner-simulation benchmark (free, mock mode)"
	@echo "  make record-learning-fixtures  Re-record the mock-session fixtures (free)"
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

# Mock mode and the disabled-key sentinel are pinned here for the same
# reason `simulate-learner` pins them below: this target advertises zero
# spend, so the environment that makes it true belongs at the call site
# rather than in whatever `.env` the caller happens to have.
#
# Both pins are a second layer, not the mechanism, and which is which
# matters. `tests/conftest.py` scrubs every variable `Settings` reads
# before collection and rebuilds the singleton, so USE_MOCK_DATA set
# here never reaches a test — the tier sets mock mode on its own
# `Settings` copy (`tests/e2e/conftest.py`). That same conftest
# re-declares ANTHROPIC_API_KEY to this exact sentinel and denies
# `src.llm._get_client` on top of it. What the pins add is a target
# that stays correct against a harness that has not loaded, and a line
# a reader can check without opening a conftest.
test-e2e:  ## E2E tier: whole workflows end to end, at zero spend
	$(TEST_ENV) USE_MOCK_DATA=true $(ZERO_SPEND) \
	$(VENV_PYTHON) -m pytest -m e2e tests/ -v

test-all:  ## Every tier
	$(TEST_ENV) $(VENV_PYTHON) -m pytest tests/ -v

# Coverage runs the CI gate's own selection (`-m "not e2e"`), because a
# floor measured against a different set of tests than the one that
# gates is a number about nothing. `--cov-context=test` records which
# test executed each line; `coverage html --show-contexts` then answers
# "who covers this?", which is how code that is executed but never
# asserted on becomes visible.
#
# The project floor comes from pyproject.toml. The four per-package
# reports below re-read the same data file, so they cost nothing extra
# and each fails on its own — `make test-cov` reports the first floor
# that breaks rather than one aggregate number that hides which package
# rotted.
#
# COVERAGE_CORE=ctrace is what makes the line above run at all on this
# project's pinned Python. coverage defaults to the `sys.monitoring`
# core from 3.14 (`env.SYSMON_DEFAULT`), that core does not support
# context switching, and pytest-cov's `--cov-context=test` switches a
# context per test — so coverage warns `no-sysmon-context` on every
# switch, and this suite turns warnings into errors. Measured on CI
# (run 33922073486, before this line existed): 3,208 tests, 6,414
# errors, zero of them about the code under test. It went unnoticed
# because a 3.13 desk venv defaults to the C tracer already and sees
# none of it, which is the second reason to pin it here rather than in
# the workflow: the target has to be correct on the interpreter
# `.python-version` names, not only on the one that happens to be
# installed. `ctrace` supports contexts and is the fast tracer;
# `pytrace` would also work and is several times slower.
test-cov:  ## Coverage over src/ with the project and per-package floors
	$(TEST_ENV) $(ZERO_SPEND) COVERAGE_CORE=ctrace \
	$(VENV_PYTHON) -m pytest -m "not e2e" tests/ \
		--cov=src --cov-context=test --cov-report=term-missing:skip-covered
	@echo ""
	@echo "Per-package floors (ratchet up only):"
	@printf '  src/api       floor %s%%, actual ' '$(COV_API)'
	@$(VENV_PYTHON) -m coverage report --include='src/api/*' \
		--fail-under=$(COV_API) --format=total
	@printf '  src/agents    floor %s%%, actual ' '$(COV_AGENTS)'
	@$(VENV_PYTHON) -m coverage report --include='src/agents/*' \
		--fail-under=$(COV_AGENTS) --format=total
	@printf '  src/security  floor %s%%, actual ' '$(COV_SECURITY)'
	@$(VENV_PYTHON) -m coverage report --include='src/security/*' \
		--fail-under=$(COV_SECURITY) --format=total
	@printf '  src/eval      floor %s%%, actual ' '$(COV_EVAL)'
	@$(VENV_PYTHON) -m coverage report --include='src/eval/*' \
		--fail-under=$(COV_EVAL) --format=total

# Patch coverage. The floors above are the ratchet; this is the question
# a reviewer actually wants answered — are the lines *this branch* added
# covered? Project coverage moves logarithmically and a large diff can
# be entirely untested while the total barely twitches. Runs entirely
# locally against `git merge-base`; no service, no account, no token.
test-cov-diff:  ## Patch coverage for this branch against origin/main
	$(TEST_ENV) $(ZERO_SPEND) $(VENV_PYTHON) -m pytest -m "not e2e" tests/ \
		--cov=src --cov-report=xml:build/coverage.xml -q
	$(VENV_PYTHON) -m diff_cover.diff_cover_tool build/coverage.xml \
		--compare-branch=origin/main --fail-under=$(COV_DIFF)

# ---- Purpose selectors (ADR 0065) ------------------------------------------
#
# The second marker axis. Tier answers "how expensive is this test";
# purpose answers "what does it protect", and until these existed the
# tenancy, injection and SSRF boundaries could not be run on their own.
# `-m security` crosses tiers on purpose: a boundary is not a speed.
test-security:  ## Every test that asserts a security boundary
	$(TEST_ENV) $(ZERO_SPEND) $(VENV_PYTHON) -m pytest -m "security and not e2e" tests/ -v

# Exit 5 is pytest's "collected nothing", which is the *expected* state
# of this tier until WO-A05 lands the first property test. Tolerated
# here and nowhere else: every other exit code still fails the target,
# so a broken property test is red the day one exists.
test-property:  ## Hypothesis-driven invariant tests (empty until WO-A05)
	@$(TEST_ENV) $(ZERO_SPEND) $(VENV_PYTHON) -m pytest -m "property and not e2e" tests/ -v \
		|| [ $$? -eq 5 ]

test-fault:  ## Behaviour when a dependency fails
	$(TEST_ENV) $(ZERO_SPEND) $(VENV_PYTHON) -m pytest -m "fault and not e2e" tests/ -v

typecheck:  ## Run mypy on the src tree
	$(VENV_PYTHON) -m mypy src/

run:  ## Run the agent: make run QUERY='your question'
	@if [ -z "$(QUERY)" ]; then \
		echo "Usage: make run QUERY='your research question'"; exit 2; \
	fi
	$(VENV_PYTHON) -m src.main "$(QUERY)"

eval:  ## Batch-run the benchmark; make eval QUERIES=id1,id2 to filter
	$(VENV_PYTHON) -m src.eval.runner $(if $(QUERIES),--queries $(QUERIES),)

# The scripted tier only. Mock mode and the disabled-key sentinel are
# pinned here rather than left to the caller's .env because this target
# advertises zero spend, and `simulate_learner` refuses to start if the
# environment contradicts that. The funded tier is deliberately absent:
# it costs money and is gated on W-OD-1 (docs/eval.md).
simulate-learner:  ## Replay learning scenarios against the session graph (free)
	USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled \
	ENABLE_CHECKPOINTING=true \
	$(VENV_PYTHON) -m src.eval.simulate_learner \
		$(if $(SCENARIOS),--scenarios $(SCENARIOS),) $(ARGS)

# Re-record tests/fixtures/learning/recorded_mock_sessions/ from the
# current session graph. Run it after any change to the graph or to
# tutor copy: the recordings are baselines, and
# tests/test_record_learning_fixtures.py fails when they stop matching
# what the graph produces. Same zero-spend pinning as the target above.
record-learning-fixtures:  ## Re-record the mock-session transcript fixtures (free)
	USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled \
	ENABLE_CHECKPOINTING=true \
	$(VENV_PYTHON) -m src.eval.record_learning_fixtures $(ARGS)

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
