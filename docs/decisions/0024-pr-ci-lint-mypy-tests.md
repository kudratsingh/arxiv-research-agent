# 0024. PR CI: ruff + mypy strict + pytest gate

- **Status**: accepted
- **Date**: 2026-07-09
- **Depends on**: ADR
  [0010](0010-nightly-eval-ci.md) (nightly eval workflow that owns
  the e2e tier)

## Context

Sprint 4 opens the deployable arc. Before we ship the FastAPI
surface, Docker, and Postgres-backed cache, we need a per-PR CI gate
so every subsequent PR — and every commit that lands on `main` — is
verified against the same three checks a human reviewer would
otherwise run by hand: lint, static types, and the fast test suite.
Today the only CI in the repo is `eval-nightly.yml` (ADR 0010),
which runs the LLM-judged benchmark against real Anthropic calls
once per day. It catches quality regressions but not
lint/type/plumbing regressions, and it doesn't gate merges. Anything
that breaks between nightlies is discovered by the next contributor
running tests locally, which violates the testing mandate ("every
merge ships with tests") and the production-scale mandate
("industry-standard, ready from milestone one").

Two constraints shape the design:

1. **No Anthropic spend on PRs.** Every PR should not hit the API —
   at typical PR volume that becomes a five-figure yearly line item
   that buys nothing the nightly eval doesn't already buy. The e2e
   tier stays with the nightly job, which uses the API key secret
   scoped to that workflow.
2. **Selective by test tier, not by cost tolerance.** The testing
   mandate calls for path- or marker-based selection so CI doesn't
   run the full suite on every PR. Today all 525 tests are unit-tier
   (mocks throughout, ~3s wall clock), so a full-suite PR run is
   effectively free. But the marker infrastructure needs to be in
   place so integration + e2e tiers get filtered automatically as
   they get authored — otherwise we're papering over the problem
   until the day a heavy test lands and everyone's PRs jump to five
   minutes.

## Decision

Add `.github/workflows/ci.yml` with three parallel jobs, all
blocking on PRs and pushes to `main`:

- **`lint`** — `ruff check .`. Ruff ships as a single-binary Python
  install, so this job runs in ~15 seconds without an editable
  project install. Ruleset configured in `pyproject.toml`:
  `E`, `F`, `I`, `B`, `UP`, `SIM`. Deliberately conservative —
  broader rules (docstring conventions, security patterns) come in
  follow-ups so this PR does not turn into a lint-fix megadiff.
- **`typecheck`** — `mypy --strict src/`. Strict is on for the
  source tree. Test tree is out of scope for this PR because tests
  monkeypatch aggressively (91 strict-mypy errors on the test suite
  today, most about `dict` generic args in fake-return-value
  helpers). A follow-up PR brings tests under the same gate; the
  source scope is the durable production gate.
- **`tests`** — `pytest -m "not e2e"`. The `not e2e` filter
  currently matches everything (no e2e tests exist yet), but keeps
  the door closed on accidentally running e2e in PR CI once those
  tests get authored. `unit` and `integration` markers are also
  registered in `pyproject.toml` per the testing doc; a
  merge-to-main variant of this workflow can run
  `-m "unit or integration"` explicitly once integration tests
  exist.

Python version is pinned via `.python-version` (matches the nightly
eval workflow); pip cache keyed on `pyproject.toml` for cold-start
speed.

The workflow does **not** own the e2e tier. E2E lives in
`eval-nightly.yml` (ADR 0010) which has the Anthropic API key
secret and runs the LLM-judged benchmark against real papers. Two
workflows, two purposes: `ci.yml` guards code correctness; `eval-
nightly.yml` guards quality.

## Alternatives considered

- **One monolithic job** (lint + mypy + tests in a single step) —
  faster cold start (one Python install) but slower feedback since
  the entire pipeline reruns on any config tweak. Rejected: three
  jobs give parallel signal and independent retries. The install
  cost per job is ~15s with pip caching; the total wall clock stays
  under a minute.
- **Include a real-API smoke query on PR** — one benchmark query
  end-to-end against Claude on every PR. Rejected on cost: at
  typical PR volume it's a five-figure yearly line item that buys
  what the nightly eval already buys. The graph-plumbing smoke
  (`tests/test_smoke.py`) already exercises node wiring without an
  API call.
- **Path-based test selection** (inspect the PR diff, run only
  test modules that mirror the changed source paths) — rejected as
  premature. At 3s full-suite wall clock, the selection logic costs
  more to maintain than it saves. Revisit when a merge-to-main run
  ever crosses ~2 minutes.
- **Non-blocking mypy (`continue-on-error: true`)** — considered as
  a shortcut around the initial 25 strict-mode errors on `src/`
  when this PR was drafted. Rejected: those 25 errors were mostly
  missing generic args and single-line fixes; landing them in this
  PR is the right size for a bundled slice and turns mypy from
  advisory to load-bearing.

## Consequences

- **Positive.** Every PR and every `main` push is now gated on
  lint, static types, and the fast test suite. Sprint 4's
  subsequent PRs (FastAPI, Docker, Postgres cache) land against a
  green baseline. The `pyproject.toml` marker + ruff config
  centralizes the per-tool policy so a future switch (e.g. adding
  `RUF` rules or bumping mypy strictness on tests) is a single
  config edit plus a follow-up fix pass.
- **Negative.** Test suite runs under the marker filter but isn't
  under strict-mypy yet, so a test-only diff can pass CI but still
  contain type bugs. The follow-up test-strict-mypy PR closes that
  gap. Cold-start install is duplicated across three jobs (~45s
  aggregate); this is the price of parallel jobs and stays
  acceptable at current suite size.
- **Follow-ups.**
  - Bring `tests/` under `mypy --strict` — 91 errors to work
    through, most trivial. Separate PR to keep the diff focused.
  - Add a merge-to-main variant (or a matrix job) that runs
    `pytest -m "unit or integration"` once integration tests exist.
  - Path-based test selection once the suite crosses ~2 minutes.
  - Broader ruff rulesets (`RUF`, `D`, `S`) after the baseline
    settles.
