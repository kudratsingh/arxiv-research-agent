# Testing strategy

Every piece of code merged into `main` has tests. Untested code doesn't
merge. This page describes the suite **as it exists** — the layout on
disk, the markers that select tiers, and what CI actually runs — plus
one explicitly-labelled section for the e2e tier that is planned but
not built. Earlier versions of this page described an aspirational
directory layout; that drift is exactly how gaps hide, so the rule now
is: this page documents reality, and planned work is labelled as such.

## Layout — flat, marker-selected

All tests live **flat** in `tests/test_*.py` — there are no
`tests/unit/`, `tests/integration/`, or `tests/e2e/` directories. One
test module per source module (`tests/test_chunker.py` ↔
`src/tools/chunker.py`), named so the mapping is obvious. Fixtures
live in the test modules that use them.

Tier membership is expressed with pytest markers, registered in
`pyproject.toml` under `[tool.pytest.ini_options].markers`:

- `unit` — pure functions, no I/O, no network, no LLM calls. Fast,
  deterministic.
- `integration` — external libraries against local fixtures: fakeredis
  for Redis, `pytest-postgresql` for Postgres, canned XML for arXiv,
  a checked-in sample PDF for PyMuPDF. Still no live network.
- `e2e` — reserved for the full-workflow cassette tier. **Zero tests
  carry this marker today** (see "Planned, not built" below).

State of the suite on `main` at the time of writing: ~800 tests
collected, of which ~55 carry an explicit `unit` marker and ~49 carry
`integration`. **The majority of tests carry no marker at all.** That
matters for selection:

> An unmarked test is *conceptually* unit-tier, but `pytest -m unit`
> only selects tests that literally carry the marker. A marker-filtered
> run is therefore a small subset of the suite, not "the fast tier".
> The only filter that runs the whole suite is the exclusion filter
> `-m "not e2e"` — which is what CI uses.

## What actually gates a merge

The per-PR CI workflow (`.github/workflows/ci.yml`, design in ADR
[0024](decisions/0024-pr-ci-lint-mypy-tests.md)) runs five parallel
jobs on every PR and every push to `main`:

1. `ruff check .`
2. `mypy --strict src/`
3. `pytest -m "not e2e" -q` — **the entire Python suite** (the filter
   only exists to keep the door closed on a future e2e tier)
4. Docker image build + compose-file validation
5. `web/`: TypeScript typecheck + ESLint + Vitest + Next.js build

The nightly eval workflow (`.github/workflows/eval-nightly.yml`, ADR
[0010](decisions/0010-nightly-eval-ci.md)) is the only job that spends
Anthropic credits: it runs the LLM-judged benchmark and diffs against
the stored baseline.

Local equivalent of the CI gate:

```bash
.venv/bin/python -m pytest tests/ -q -m "not e2e"
make typecheck
.venv/bin/python -m ruff check src/ tests/
```

**Known trap**: `make test` currently expands to `pytest -m unit`,
which runs only the explicitly-marked subset (~55 tests) — a green
`make test` is **not** the merge gate. Until the Makefile is aligned
with CI, use the commands above (or `make test-all`) before opening a
PR. For the same reason, ADR 0024's follow-up — "add a merge-to-main
variant that runs `pytest -m 'unit or integration'`" — must **not**
be closed as written: with most tests unmarked, that filter would
silently drop the bulk of the suite (including the auth, scoping, and
cross-worker tests) from the gate while reporting a plausible-looking
pass count. Either auto-apply the `unit` marker to unmarked tests in
a `conftest.py` collection hook first, or keep `-m "not e2e"` as the
single selection knob.

## Selective execution

The durable selection mechanism is the marker filter; `-m "not e2e"`
is the only filter in production use. Path-based selection (running
only the test modules that mirror a PR's changed source paths) was
considered in ADR 0024 and deliberately deferred: at the suite's
current wall clock (~tens of seconds), selection logic costs more to
maintain than it saves. Revisit when a full run crosses ~2 minutes.

## Test writing standards

- One test module per source module, named `tests/test_<module>.py`.
- Module-level `pytestmark = pytest.mark.unit` (or `integration`) on
  new modules so tier membership is explicit rather than implied.
- Prefer parametrized tests (`@pytest.mark.parametrize`) over
  copy-paste.
- Never hit real external services in unit or integration tiers —
  fakeredis for Redis, `pytest-postgresql` for Postgres, monkeypatched
  `call_llm_json` for Claude.
- Every PR ships with tests for its diff. Untested behavior fails
  review. Prefer tests that fail against the unfixed code.

## What "tested" means for LLM-heavy code

Non-determinism means we cannot assert on exact model output. Instead:

- Assert on the **structure** of the response — JSON parses, required
  keys present, types correct, scores in `[0, 1]`.
- Assert on the **prompt shape** — inputs are packed correctly into the
  prompt (unit tests on prompt-builder helpers).
- Every LLM-calling module stubs `call_llm_json` and exercises both
  well-formed and malformed responses, so fallback paths (supervisor
  default routing, verifier fail-closed, refiner keep-current) are
  covered without an API call.
- Pipeline-level quality is guarded by the nightly eval, not the PR
  suite.

## Planned, not built: the e2e cassette tier

The design calls for a third tier — the full LangGraph workflow run
against recorded LLM cassettes (VCR-style, one recorded response per
prompt) so a pipeline-level regression is caught deterministically and
without API cost. **No such tests exist yet**: the `e2e` marker is
registered but unused, and no cassette fixtures are checked in.

Name the consequence, because it already bit once: everything between
individual node behavior and the nightly LLM-judged eval is currently
untested, and the production audit found a P0 hiding in precisely that
gap — a defect no unit test could see and the nightly eval didn't
surface. Until the cassette tier is built, treat cross-node integration
changes (workflow wiring, state schema, runner/streaming interplay)
with extra review care, and do not claim e2e coverage anywhere.

When the tier is built it should: live in flat `tests/test_e2e_*.py`
modules marked `e2e`, run on merge-to-`main` and nightly (not per-PR),
and gate a live-API mode behind an env flag (e.g. `E2E_LIVE=1`) for
local debugging only.
