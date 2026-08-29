# Testing strategy

Every piece of code merged into `main` has tests. Untested code doesn't
merge. This page describes the suite **as it exists** — the layout on
disk, the markers that select tiers, and what CI actually runs — plus
one explicitly-labelled section for the Python e2e cassette tier that is
planned but not built. Earlier versions of this page described an
aspirational directory layout; that drift is exactly how gaps hide, so
the rule now is: this page documents reality, and planned work is
labelled as such.

Two suites live here and they are selected differently. The **Python**
suite is flat and marker-selected; that is what the sections up to
"Selective execution" describe. The **web** suite under `web/` has its
own tiers — unit, story, coverage, dependency audit, route budget and
browser — and is described in "The web suite" below. `e2e` means
different things in the two: in Python it is an unused marker reserved
for a cassette tier, and in `web/` it is the Playwright tier, which is
built and gating today.

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

State of the suite on `main` at the time of writing: 1,400+ tests
collected (1,426 at the last count), of which ~520 carry an explicit
`unit` marker and ~200 carry `integration`. **Roughly half the suite
carries no marker at all.** That matters for selection:

> An unmarked test is *conceptually* unit-tier, but `pytest -m unit`
> only selects tests that literally carry the marker. A marker-filtered
> run is therefore a subset of the suite, not "the fast tier".
> The only filter that runs the whole suite is the exclusion filter
> `-m "not e2e"` — which is what CI uses.

## What actually gates a merge

The per-PR CI workflow (`.github/workflows/ci.yml`, design in ADR
[0024](decisions/0024-pr-ci-lint-mypy-tests.md)) runs eight parallel
jobs on every PR and every push to `main`:

1. `lint` — `ruff check .`
2. `typecheck` — `mypy --strict src/`
3. `tests` — `pytest -m "not e2e" -q`, **the entire Python suite** (the
   filter only exists to keep the door closed on a future e2e tier)
4. `docker-build` — API image build + base and production compose-file
   validation
5. `web-image` — `docker build ./web`, run it against a stub upstream,
   probe `/` and `/api/healthz` through the proxy
6. `web` — TypeScript typecheck, ESLint, contract drift, Vitest **with
   coverage thresholds**, the **dependency audit gate**, and the
   production build **with the route budget check**
7. `web-storybook` — story tests and the static Storybook build
8. `web-e2e` — Compose up + seed + Playwright + axe, chromium only

The nightly eval workflow (`.github/workflows/eval-nightly.yml`, ADR
[0010](decisions/0010-nightly-eval-ci.md)) is the only job that spends
Anthropic credits: it runs the LLM-judged benchmark and diffs against
the stored baseline. `ci.yml` itself also runs on a 03:20 UTC schedule,
where the only behavioural difference is that `web-e2e` runs the full
browser matrix instead of chromium alone.

Local equivalent of the Python half of the gate:

```bash
.venv/bin/python -m pytest tests/ -q -m "not e2e"
make typecheck
.venv/bin/python -m ruff check src/ tests/
```

**Known trap**: `make test` currently expands to `pytest -m unit`,
which runs only the explicitly-marked subset — a green
`make test` is **not** the merge gate. Until the Makefile is aligned
with CI, use the commands above (or `make test-all`) before opening a
PR. For the same reason, ADR 0024's follow-up — "add a merge-to-main
variant that runs `pytest -m 'unit or integration'`" — must **not**
be closed as written: with about half the suite unmarked, that filter
would silently drop it — `-m "unit or integration"` selects ~720 of
~1,430 tests today — while reporting a plausible-looking pass count.
Either auto-apply the `unit` marker to unmarked tests in
a `conftest.py` collection hook first, or keep `-m "not e2e"` as the
single selection knob.

## The web suite

The frontend has its own tiers, wired by WO-24 against
[`docs/revamp/05-MIGRATION.md`](revamp/05-MIGRATION.md) §3 (items C4,
C7, C8, C9, C10) and [`04-ARCHITECTURE.md`](revamp/04-ARCHITECTURE.md)
§7.5. Every one of them is a gate — a red job, not a report nobody
reads.

| Tier | Command | Job | What fails it |
|---|---|---|---|
| Unit + component | `npm run test` | `web` | any Vitest failure across the `unit` and `storybook` projects |
| Coverage | `npm run test -- --coverage` | `web` | falling below the thresholds in `web/vitest.config.mts` |
| Dependency audit | `npm run audit:gate` | `web` | any high/critical advisory in the production tree, or one in the dev tree that `web/audit-exceptions.json` does not name |
| Route budgets | `npm run budgets` | `web` | a gated ceiling in `web/budgets.json` exceeded |
| Storybook | `npm run build-storybook`, `npx vitest run --project=storybook` | `web-storybook` | a story that fails to render, fails axe, or fails to bundle |
| Browser + axe | `npm run e2e` | `web-e2e` | any Playwright assertion, including the axe sweep over the state matrix |

**Coverage (C10).** Thresholds are seeded at the *measured* value and
ratcheted upward by the work order that raises them — never set
aspirationally, because a threshold nobody can meet is a threshold that
gets skipped. Vitest merges coverage across both projects in one run and
only honours the option at the root, which is why the `web` job's single
`npm run test -- --coverage` is what the floors are measured against;
`web-storybook` runs the story project again on its own so a story
regression is attributed rather than averaged in.

**Dependency audit (C4).** Two gates in `web/scripts/audit-gate.mjs`,
because one would have had to be wrong. The **production** tree
(`npm audit --audit-level=high --omit=dev`) is gated at zero advisories
and has no exception mechanism at all. The **dev** tree is gated against
`web/audit-exceptions.json`, and fails on any advisory that file does
not name — *and* on an entry that no longer matches anything npm
reports, so an exception cannot outlive its advisory. Each entry carries
the advisory ids, the dependency path, a written justification and a
date; an empty justification is a hard error, the same contract WO-22's
axe allowlist uses. The script takes no arguments and reads no
environment variable, so there is no flag that softens it.

**Route budgets (C7).** `web/scripts/route-budgets.mjs` gzips each
route's first-load file union out of the Next build manifests and
compares it with `web/budgets.json`. A ceiling can only move by editing
`budgets.json` in the same commit, with the reason in the PR body
([`04` §8.4](revamp/04-ARCHITECTURE.md)); the report is written before
the script exits non-zero, so a breach uploads the evidence of its own
breach as `budget-report.md`.

**Browser tier (C8).** `web/e2e/README.md` is the manual.
`npm run e2e:stack:up && npm run e2e:stack:seed && npm run e2e` brings
up the local Compose stack under an isolating overlay, writes only
`baseline-*` fixtures directly into Postgres and Redis, and runs
Playwright plus `@axe-core/playwright` against it. **Chromium only per
PR**; firefox, webkit and the two device projects run on the nightly
schedule, so PR wall-clock stays bounded. Traces, screenshots, video,
the HTML report and every axe JSON land under `web/build/e2e/` and are
uploaded as an artifact whether the run passed or failed.

**The cost boundary is structural.** No web tier ever makes a paid model
call, and three independent mechanisms enforce it rather than one
convention: the Compose overlay pins `ANTHROPIC_API_KEY` to the invalid
sentinel `local-preview-disabled`, `playwright.config.ts` overwrites the
variable in the runner process before any test loads (with
`global-setup.ts` refusing to start if it is anything else), and
`e2e/support/paid-path.ts` fulfils `POST /api/research` in the browser
so the submit leg never reaches the backend. The `web-e2e` job
hard-codes the same sentinel and is never given the repository secret;
`web/tests/ci.test.ts` asserts that against the workflow's own text.

**The build tool is pinned.** `web/package.json`'s build script is
exactly `next build --webpack`, and `web/tests/ci.test.ts` asserts the
exact string ([`05` §3.1](revamp/05-MIGRATION.md) B4). Turbopack is a
separate ADR, so without that assertion the pin would be a sentence
rather than a gate.

Local equivalent of the web half of the gate:

```bash
cd web
npm run typecheck && npm run lint && npm run contract:check
npm run test -- --coverage
npm run audit:gate
npm run budgets
npm run e2e:stack:up && npm run e2e:stack:seed
npm run e2e -- --project=chromium
npm run e2e:stack:down
```

## The environment pin: `TEST_ENV`

Every Makefile test target runs under
`OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false` (the `TEST_ENV`
variable, ADR 0052). This is the *second* layer of the native-crash
containment, not the fix: three separate `libomp.dylib` copies ship
in the venv (torch, faiss, scikit-learn vendor one each), and
concurrent MiniLM encodes used to abort the interpreter inside the
OpenMP barrier — exit 139, no traceback, a macOS crash-reporter
dialog. The actual containment is `torch.set_num_threads(1)` inside
`src/tools/embeddings.py`, which covers callers that never touch the
Makefile (a bare `pytest` in CI, `uvicorn` in the container,
`python -m src.main`). What `TEST_ENV` adds is faiss's and
scikit-learn's own libomp copies, which initialize at import — before
any Python code of ours runs. `TOKENIZERS_PARALLELISM=false` is
unrelated to the crash; it only silences the HuggingFace
fast-tokenizer fork warning. `tests/test_repo_hygiene.py` pins that
every test target keeps the prefix.

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

## The production-wiring smoke test

`tests/test_api_smoke_e2e.py` (marked `integration`, so it runs in
the per-PR gate) drives **one job through the production wiring**:
the real `build_workflow` (fixed pipeline, HITL interrupt,
`AsyncSqliteSaver` at a tmp path), `create_app`'s lifespan, the
runner, the store, and the HTTP surface. Only the network edges are
canned — `call_llm_json` per agent module with shape-valid
responses, PDF fetch (empty → abstract fallback), and embedding
ranking. It exists because the shipped configuration once compiled a
*sync* checkpointer under an `astream`-driven runner and every HTTP
job died before its first node — a wiring break no per-module test
could see (ADR 0040). It is a smoke test, not a cassette tier: one
happy path, canned LLM output, no recorded real responses.

## Planned, not built: the e2e cassette tier

The design calls for a third tier — the full LangGraph workflow run
against recorded LLM cassettes (VCR-style, one recorded response per
prompt) so a pipeline-level regression is caught deterministically and
without API cost. **No such tests exist yet**: the `e2e` marker is
registered but unused, and no cassette fixtures are checked in.

Name the consequence, because it has bitten more than once: with real
LLM *content* untested, everything between the smoke test's single
canned path and the nightly LLM-judged eval is uncovered — the ADR
0040 wiring break lived in that gap, and ADR 0053's audit found five
more sequence-level defects (`docker compose up` → UI → query) that
no per-module test drove. Until the cassette tier is built, treat
cross-node integration changes (workflow wiring, state schema,
runner/streaming interplay) with extra review care, and do not claim
e2e coverage anywhere.

When the tier is built it should: live in flat `tests/test_e2e_*.py`
modules marked `e2e`, run on merge-to-`main` and nightly (not per-PR),
and gate a live-API mode behind an env flag (e.g. `E2E_LIVE=1`) for
local debugging only.
