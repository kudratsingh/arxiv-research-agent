# 0065. Test isolation harness, a two-axis marker model, and a measured coverage floor

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: kudratsingh

## Context

`pytest -m "not e2e"` reported **2042 passed, 52 skipped** on `main`
when this work started (2173 by the time it landed, after WO-A01 and
WO-A03 merged ahead of it).
That is a genuinely large suite, and it is why this decision is about
*proof* rather than volume: four of the things everyone assumed the
suite guaranteed were not guaranteed at all, and no quantity of
additional tests of the existing kind would have detected any of them.

**There was no `tests/conftest.py` anywhere in the repository.**
Verified by `find`. Every consequence below follows from that one
absence.

- **A developer's `.env` could change a test outcome.** `src/config.py`
  declares `env_file=".env"`, a real `.env` sits at the repo root, and
  more than thirty modules construct a bare `Settings()`. The ambient
  environment was equally unfiltered.
- **Nothing stopped a test reaching the network.** `test_pdf_parser.py`
  patched `socket.getaddrinfo` to drive the SSRF checks; every other
  module was on the honour system.
- **Nothing stopped a test constructing a real Anthropic client.** Two
  modules patched `src.llm._get_client` by hand — and both said in their
  docstrings that this was the choke point every paid path funnels
  through, which is a convention documented at exactly the two places
  that already followed it. `tests/test_api_smoke_e2e.py` states the
  problem outright: LLM fakes are per-module monkeypatches, not one
  seam, so a renamed import silently reverts a test to the real client.
- **Nothing pinned the sources of non-determinism.** `random.seed`
  appeared zero times in the suite; `PYTHONHASHSEED` was whatever the
  invoking shell carried.

Two more structural gaps sat alongside:

- **38 of 98 modules carried no tier marker**, so `make test`
  (`pytest -m unit`) ran roughly half the suite and looked green.
  `docs/testing.md` already called this a known trap. There was also no
  `--strict-markers`, so a typo'd `@pytest.mark.uni` was a test that
  never ran and never complained; no `--strict-config`; no
  `xfail_strict`; no per-test timeout.
- **Python coverage was never measured.** No `pytest-cov`, no
  `coverage`, nothing in `pyproject.toml`, the lock, the `Makefile` or
  CI. The web half enforces statements 98.15 / branches 94.0 /
  functions 88.8 / lines 99.11 in `web/vitest.config.mts` and has since
  WO-24. The asymmetry was the finding.

The forcing function is Phase A's sequencing: the property tier
(WO-A05), the fault-injection tier (WO-A06) and an e2e tier all need a
harness that cannot reach the network or a real key, so this lands
first. It is also the phase's single dependency diff, so no other work
order touches the lock.

## Decision

### 1. `tests/conftest.py`: four autouse guarantees

In this order, because the order is load-bearing.

**Env isolation runs at conftest *import* time, not in a fixture.**
`src/config.py` builds its `settings` singleton at module import, and
test modules import it during collection — after conftest is imported
but before any fixture runs. A fixture is structurally too late. The
sequence is: wrap `BaseSettings.__init__` to default `_env_file=None`
(pydantic-settings' own documented per-construction override, so a test
that asks for a file explicitly still gets one); assert `src.config` is
not yet in `sys.modules`; import it; derive the variable names from
`Settings.model_fields` rather than listing them, so a new field is
covered the day it lands; scrub those from `os.environ`; apply the
declared set; rebuild the singleton.

The declared set is deliberately tiny — `ANTHROPIC_API_KEY` at the
repo's existing invalid sentinel `local-preview-disabled`, and
`PYTHONHASHSEED=0`. Everything else falls back to the shipped field
default, so a test reads production defaults unless it overrides one.

**`dotenv.load_dotenv` is neutralised in the same block**, because
suppressing pydantic's dotenv source is not sufficient and the gap was
measured rather than imagined. Four modules — `src/main.py`,
`src/eval/runner.py`, `src/eval/simulate_learner.py`,
`src/eval/record_learning_fixtures.py` — call `load_dotenv()` at import,
which copies the file into `os.environ`, where it outranks every default
and is invisible to a `Settings` already constructed. With a `.env` at
the repo root and that path open, importing `src.eval.runner`
mid-session moved eight assertions in `test_config.py`,
`test_observability.py`, `test_search_honesty.py` and
`test_session_cost_cap.py`. It is replaced with a no-op rather than a
raise: calling it at import is correct production behaviour, and a raise
would break the import instead of the leak.

**Network guard.** `socket.socket.connect` and `connect_ex` refuse any
non-loopback address, naming the test from `PYTEST_CURRENT_TEST`. Those
two methods are where `create_connection`, `http.client`, `requests`,
`httpx` and `psycopg` all bottom out. Loopback and non-IP families
(`AF_UNIX`) pass, so `pytest-postgresql` and every ASGI transport are
unaffected. A hostname is refused rather than resolved, because
resolving it to decide would itself be the access under test. DNS is
left alone: `tests/test_pdf_parser.py` patches `getaddrinfo` for the
SSRF checks and taking it over here would collide. Opt out with
`@pytest.mark.network`.

**Spend guard.** `src.llm._get_client` raises unless a fake is
installed. "Installed" means either of the two styles already in the
suite: a patched `_get_client` (twenty call sites), or a patched
`src.llm.anthropic.Anthropic` (`tests/test_llm.py::TestGetClient`,
which needs the real construction logic to run against a fake SDK). The
guard delegates when it sees one, so the denial fires on exactly one
condition — a real client about to be built with a real key.

**Determinism.** `random` (and numpy's global RNG when loaded) reseeded
before *every* test, so a failure reproduces from its node id alone
without a recorded ordering. A `FrozenClock` is offered as the
`frozen_clock` fixture for the ~9 modules that hand-patch time; it is
**not** autouse, because freezing the clock under every test would
change the meaning of the drain, lease and timeout suites, which measure
real elapsed time on purpose. Those modules are not rewritten here.

**Both guard exceptions derive from `BaseException`.** This codebase
degrades gracefully by design — the reader falls back to abstracts, the
supervisor to a default route, the cache to a miss — and around fifty
`except Exception` sites implement that. A guard those handlers can
swallow reports a green test for a run that reached the internet.

### 2. Strictness

`--strict-markers`, `--strict-config`, `xfail_strict = true`, a
60-second per-test `timeout` (about 13× the slowest measured test, 4.4s,
using the `signal` method so the session carries on and reports which
test hung), and `filterwarnings = ["error", ...]`.

Three exemptions, each scoped to one message with the reason inline:
the SWIG `DeprecationWarning`s that faiss and PyMuPDF raise at import
(`SwigPyObject`, `swigvarlink`, `SwigPyPacked`).

A fourth was written and then deleted, which is the point worth
recording. Starlette's `HTTP_422_UNPROCESSABLE_ENTITY` deprecation is
*attributed* by stack level to `fastapi/routing.py`, but the deprecated
alias was ours — `src/api/routes.py` read it in two places, and WO-A02
does not own `src/`, so the exemption was written with the rename named
as the condition for removing it. WO-A01's error taxonomy then merged
and removed the last reader, and the exemption was retested and dropped
before this landed. An exemption that outlives its cause is a filter
nobody can justify, so they are re-tested rather than inherited.

### 3. Markers on two orthogonal axes

The old three markers conflated speed with purpose.

- **Tier** — how much a test costs. `unit` / `integration` / `e2e`,
  exactly one per test. `unit` allows temp-file I/O; "no I/O at all" was
  never the operative rule and pretending otherwise pushes tests into
  the wrong tier. `integration` starts a local server, a compiled graph
  or an ASGI app.
- **Purpose** — what a test protects. `security`, `property`, `fault`,
  `contract`, `network`; zero or more, orthogonal to the tier.

Enforcement is two-sided. A file walk in
`tests/test_harness_guards.py` fails on any `tests/test_*.py` with no
tier marker — it walks the directory rather than a list, so a module
added on another branch is covered the moment it lands. A collection
hook records every collected item whose tier is missing or declared
twice at the same scope; a class- or function-level tier legitimately
shadows a module-level one, which is how `pytestmark` composition is
meant to read. The hook *records* rather than raising, because a hard
failure in `pytest_collection_modifyitems` aborts the whole session and
turns "someone forgot a marker" into "the suite does not run".

### 4. Coverage as a floor

`pytest-cov` with `branch = true` over `src/`. Line coverage
systematically over-reports on compound conditions, which this codebase
has plenty of.

Floors are **measured values rounded down, never aspirational**, and
the rule is **ratchet up only**: project 89 (measured 89.21%),
`src/api` 86 (86.60%), `src/agents` 92 (92.59%), `src/security` 97
(97.37%), `src/eval` 91 (91.05%). Per-package floors live in the
Makefile because coverage.py's `fail_under` is global, and a project
number can hold steady while the one package that matters rots
underneath it.

Every number was re-measured on the rebased tree rather than carried
over: WO-A01 and WO-A03 added ~130 tests and three source modules after
this branch was cut, and the project figure moved from 88.86% to 89.21%.
A published floor binds every future PR through the ratchet rule, so a
stale measurement is not a rounding error — it is the wrong contract.

`diff-cover` adds a patch-coverage gate at 90% for changed lines.
Project coverage improves logarithmically; a large diff can be entirely
untested while the total barely moves.

Two integrity checks guard the gate itself, both in
`tests/test_harness_guards.py`. Exclusions are central
(`exclude_also`, each with a written reason) and `omit` is empty and
asserted empty — an `omit` entry is an exclusion with no reason and no
line in the report. Inline `# pragma: no cover` is capped at its census
of 16 and each must carry a reason; pragma growth is the most reliable
symptom of a gate being met on paper. That check reported before it
merged: it went red in CI on four pragmas that arrived with WO-A01 and
WO-A03, which is exactly the drift it exists to make visible.
`--cov-context=test` records which test executed each line, which is
what `coverage html --show-contexts` needs to answer "who covers this?".

The known gaming failure of a coverage gate is a test that executes code
without asserting on it. The counter-pressure is the `property` and
`fault` tiers, not a higher percentage.

### 5. Dependencies

Five dev packages, floors set by ADR 0045's policy (oldest release that
ships a wheel for the pinned Python 3.14 *and* speaks the API we
target), each verified against PyPI for a cp314 wheel rather than
assumed: `pytest-cov>=7.1.0`, `coverage[toml]>=7.10.0` (7.10.0 is the
first with a real cp314 wheel; 7.9.0 falls back to the pure-Python
tracer), `pytest-timeout>=2.4.0`, `hypothesis>=6.167.1` (unused until
WO-A05; pinned here so no later work order moves the lock), and
`diff-cover>=10.0.0`, which brings `chardet` transitively. All six pins
are dev-only, so `requirements-runtime-lock.txt` is unchanged and
`derive_runtime_lock.py --check` proves it.

## Alternatives considered

- **A `pytest` plugin package instead of a conftest** — a single
  conftest is readable end to end and needs no packaging story,
  versioning story, or second place to look.
- **`freezegun` / `time-machine` for the clock** — a sixth dependency
  for a ~40-line fixture that nine modules will adopt incrementally.
  `FrozenClock` patches the `time` module attributes, which is exactly
  how `src/` reads the clock. Revisit if a caller needs
  `datetime.now()` frozen, which the C type makes awkward to patch.
- **Blocking `socket.getaddrinfo` as well** — strictly stronger, but it
  collides with `tests/test_pdf_parser.py`, which patches
  `getaddrinfo` to drive the SSRF checks. A resolution is not a
  connection; the connect is where the money is.
- **`Exception` rather than `BaseException` for the guards** — reads
  more conventionally, and is wrong here: the ~50 deliberate
  `except Exception` fallbacks would swallow it and report green.
- **Auto-applying `unit` to unmarked tests in a collection hook** —
  proposed in `docs/testing.md` before this ADR. It makes the count look
  right without making the classification right, and it would have
  quietly labelled two ASGI suites `unit`.
- **A blanket `omit` for CLI entry points and `__main__` blocks** — an
  exclusion with no reason attached and no line in the report.
  `exclude_also` does the same job visibly.
- **Codecov or a hosted patch-coverage service** — needs an account, a
  token and a network call in CI. `diff-cover` is Apache-2.0 and runs
  entirely locally against `git merge-base`.
- **`schemathesis` for API property testing** — hard-requires
  `pytest>=9,<10`, which this repo's range permits but which would make
  a pytest major bump a side effect of a dependency diff. Out of scope
  for Phase A.
- **`pytest-rerunfailures` in this PR** — the flake *policy* is the
  deliverable (`docs/testing.md`, "Flake policy"); the plugin without an
  agreed policy is how blanket reruns get adopted by default.

## Consequences

- **Positive.** Three tests were opening live TLS connections to the
  Anthropic API on every run — `tests/test_assessment_judge.py::TestGraphIntegration`
  (two) and `tests/test_guided_session_graph.py::TestSessionApiEndToEnd`.
  `progress_update_agent` summarises a session through
  `src/learning/memory.py`, which reads its own module-level settings;
  that module was absent from both files' per-module patch lists, the
  call went to the real client, failed on the invalid key, and was
  absorbed by the module's degrade path. Every assertion passed. Fixed
  by adding the missing module to each patch list — the guard found in
  one run what the convention had missed for the life of both files.
- **Positive.** Isolation is now demonstrable rather than asserted: with
  a `.env` planting `MAX_PAPERS=1`, `USE_MOCK_DATA=true`,
  `ANTHROPIC_MODEL=claude-from-dotenv` and a fake key at the repo root,
  and with the same four variables exported into the shell, the suite is
  byte-for-byte identical to a clean run.
- **Positive.** `pytest -m unit` is a real tier for the first time
  (1,929 of 2,256 tests), and `pytest -m security` is a runnable gate
  over 157 tests that previously could not be selected at all.
- **Negative.** Warnings are errors, so an upstream deprecation can now
  turn the suite red on an unchanged `main`. That is the intended
  trade — the alternative is a warning nobody reads — but it means an
  exemption occasionally has to be added under time pressure. Each one
  must name its message and say what would let us delete it.
- **Negative.** The `BaseException` guards will not be caught by a
  test's own `pytest.raises(Exception)`. That is the point, and it will
  surprise someone once.
- **Negative.** `make test-cov` runs the suite a second time when a
  developer has already run `make test-all`. Coverage is not in
  `addopts` deliberately: it would slow every partial run and make
  `fail_under` fire on a single-file invocation.
- **Follow-ups.** (1) Wire `make test-cov` and `make test-cov-diff` into
  `.github/workflows/ci.yml`; until then the floors are a local gate.
  (2) Re-tier the twelve `unit`-marked modules that build an ASGI app —
  listed in `docs/testing.md`; it changes what `make test` runs, so it
  is its own PR. (3) Give `src/tools` (79.31%) and `src/learning`
  (84.94%) their own floors — they are the two lowest packages and the
  two most obvious next ratchets. (4) Four of the sixteen inline
  `# pragma: no cover` are `if __name__ == "__main__":` guards now
  covered by the central `exclude_also` rule and can be removed by
  whichever work order next touches those files.
  (5) The `e2e` and `property` tiers are registered with zero members;
  WO-A05 and the e2e work order fill them.
