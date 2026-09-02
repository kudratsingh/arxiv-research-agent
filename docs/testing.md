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
"Selective execution" describe. The **web** suite under `web/` has
**eight tiers** — unit, component, story, integration, contract, e2e,
accessibility and budgets — described with a local command each in "The
web suite" below. `e2e` means different things in the two: in Python it
is an unused marker reserved for a cassette tier, and in `web/` it is
the Playwright tier, which is built and gating today.

Two numbers in this page are both eight and they are **not the same
eight**: CI runs eight parallel *jobs*, and the web suite has eight
*tiers*. Several tiers share the `web` job; two jobs (`lint`,
`docker-build`) carry no web tier at all.

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
   filter only exists to keep the door closed on a future e2e tier),
   then the **scripted learner-simulation campaign**: all fifteen
   guided-read scenarios driven through the real session graph in mock
   mode, with `src/eval/scripted_tier_check.py` asserting 15/15 sessions
   and `$0.0000` spend from the run's `summary.jsonl` (WO-W11; see
   [`eval.md`](eval.md), "The per-PR scripted tier"). The run uploads as
   the `scripted-simulation-summary` artifact under `if: always()`
4. `docker-build` — API image build + base and production compose-file
   validation
5. `web-image` — `docker build ./web`, run it against a stub upstream,
   probe `/` and `/api/healthz` through the proxy
6. `web` — TypeScript typecheck, ESLint, contract drift, Vitest **with
   coverage thresholds**, the **dependency audit gate**, and the
   production build **with the route budget check**
7. `web-storybook` — story tests and the static Storybook build
8. `web-e2e` — Compose up + seed + Playwright + axe, chromium only

Nothing else gates a merge. Three schedules run beside it, none of them
blocking a PR:

- `ci.yml` itself on a 03:20 UTC schedule, where the only behavioural
  difference is that `web-e2e` runs the **full browser matrix** instead
  of chromium alone.
- `.github/workflows/nightly.yml` — Lighthouse CI against the seeded
  stack (WO-29); see tier 8 below.
- `.github/workflows/eval-nightly.yml` (ADR
  [0010](decisions/0010-nightly-eval-ci.md)) — the LLM-judged benchmark
  diffed against the stored baseline. **This is the only workflow in
  the repo that spends Anthropic credits.** No web tier ever makes a
  paid model call, structurally; see "The cost boundary" below.

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

The frontend has its own tiers, specified in
[`04-ARCHITECTURE.md`](revamp/04-ARCHITECTURE.md) §7.1 and wired into
CI by WO-24 against §7.5 and
[`docs/revamp/05-MIGRATION.md`](revamp/05-MIGRATION.md) §3 (items C4,
C7, C8, C9, C10). Every one of them is a gate — a red job, not a report
nobody reads.

### The eight tiers

All commands run from `web/`. Vitest is configured with two *projects*
— `unit` and `storybook` — and tiers 1, 2, 4 and 5 all live in the
`unit` project, separated by directory rather than by a runner. A bare
`npm run test` runs every Vitest tier (1–5) in one process.

| # | Tier | What it covers | Local command | Job |
|---|---|---|---|---|
| 1 | Unit | `lib/api/` normalizers, the job reducer's total transition table, token/Tailwind parity | `npx vitest run --project=unit tests/job tests/api.test.ts tests/tokens.test.ts` | `web` |
| 2 | Component | primitives and patterns through Testing Library — behaviour and a11y, never snapshots | `npx vitest run --project=unit tests/primitives tests/patterns` | `web` |
| 3 | Story | every story renders and passes axe | `npx vitest run --project=storybook` | `web-storybook` |
| 4 | Integration | features and query hooks against MSW handlers + recorded fixtures | `npx vitest run --project=unit tests/features tests/queries` | `web` |
| 5 | Contract | fixture parse, generated-type drift, SSE event-name pinning | `npm run contract:check` then `npx vitest run --project=unit tests/contract` | `web` |
| 6 | E2E | the vertical slice and the guided-read session against the seeded local stack | `npm run e2e` (stack first — see below) | `web-e2e` |
| 7 | Accessibility | axe over every state × theme, plus keyboard, zoom and reduced-motion probes; also per story at tier 3 | `npm run e2e -- --grep "@axe\|@a11y"` | `web-e2e`, `web-storybook` |
| 8 | Budgets | per-route gzip ceilings in `web/budgets.json` | `npm run budgets` | `web` |

Tier 3 runs in jsdom, not a real browser, so it needs no Playwright
install; tiers 6 and 7 do. `npm run build-storybook` additionally
proves the static bundle builds, which is what `web-storybook` uploads.

Two further gates ride on these tiers rather than being tiers of their
own — both are red jobs, not reports:

| Gate | Command | What fails it |
|---|---|---|
| Coverage | `npm run test -- --coverage` | falling below the thresholds in `web/vitest.config.mts` |
| Dependency audit | `npm run audit:gate` | any high/critical advisory in the production tree, or one in the dev tree that `web/audit-exceptions.json` does not name |

**Tier 8's second half: Lighthouse, nightly.** The byte budgets gate
every PR; the *performance* budgets are asserted by Lighthouse CI on
its own workflow (`.github/workflows/nightly.yml`, WO-29), not by the
per-PR gate. `npm run lhci` is `node scripts/lhci-run.mjs`, which runs
`lhci autorun` once per form factor against `web/lighthouserc.json`:
four seeded states × three profiles (mobile 412×823, desktop 1350×940,
and mobile 320×568 for the narrow-strip case) × three runs each,
asserting per-URL category scores and Core Web Vitals ceilings.
Locally it needs the seeded stack and a base URL:

```bash
cd web
npm run e2e:stack:up && npm run e2e:stack:seed
LHCI_BASE_URL="$(bash ./e2e/support/stack.sh url)" npm run lhci
npm run e2e:stack:down
```

Nightly rather than per-PR because it needs the full Compose stack, so
a regression is caught within a day rather than at the gate. Reports,
resolved configs and assertion results land in `web/build/lhci/`, and
`summary.md` is written *before* the script exits non-zero, so a red
run publishes its own numbers.

**Every Lighthouse number is a lab number.** It is a throttled local
run against a seeded stack, not field data — there is no RUM and no
telemetry egress by design. Read it as a regression detector, not as
what users experience. It also cannot catch the class of bug it once
scored 98–99 through: a fast page whose usable content is squeezed into
a narrow strip. The no-horizontal-scroll assertion at tier 6 is the
gate that actually holds there.

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
breach as `budget-report.md`. The ratified ceilings, the ratchet rule
and every movement so far are recorded in ADR
[0056](decisions/0056-design-tokens.md).

**Browser tier (C8).** `web/e2e/README.md` is the manual.
`npm run e2e:stack:up && npm run e2e:stack:seed && npm run e2e` brings
up the local Compose stack under an isolating overlay, writes only
`baseline-*` fixtures directly into Postgres and Redis, and runs
Playwright plus `@axe-core/playwright` against it. **Chromium only per
PR**; firefox, webkit and the two device projects run on the nightly
schedule, so PR wall-clock stays bounded. Traces, screenshots, video,
the HTML report and every axe JSON land under `web/build/e2e/` and are
uploaded as an artifact whether the run passed or failed.

**Accessibility tier (C9).** Axe runs at two tiers with two different
jobs. Per story (tier 3) the Storybook a11y addon is configured
`test: "error"`, so a violation **fails the story's component test**
rather than decorating a panel nobody opened. Per state (tier 7)
`@axe-core/playwright` sweeps the full state × theme matrix with the
WCAG 2 A/AA + 2.1 A/AA + 2.2 AA + best-practice tag set — the same tags
the retained baseline used, so results stay directly comparable. The
audit viewport is pinned at the baseline's 1440×1200 because at
Playwright's default 1280×720 axe downgrades below-the-fold contrast
findings to `incomplete` and the sweep under-reports. Suppression is
possible only through `web/e2e/axe-allowlist.json`, which requires a
written justification per entry.

Narrow widths are covered at tier 6 rather than here: `reflow.spec.ts`
and `device.spec.ts` assert no horizontal scroll and usable layout at
the small widths, and the device projects run on the nightly matrix.
That split is deliberate — a contrast measurement wants a fixed
viewport, a reflow assertion wants several.

Beyond axe, WO-27 added a second `@a11y`-tagged group in the same job:
`keyboard.spec.ts` walks tab order and focus restoration by pressing
real keys and reading `document.activeElement`, `zoom.spec.ts` covers
200%/400%, `motion.spec.ts` covers `prefers-reduced-motion`, and
`axe-matrix.spec.ts` widens the sweep. These are **observations**, not
judgements: the browser's own focus algorithm decides where focus goes
and the test records where it landed.

**A green run is still not a conformance claim.** What automation
cannot establish stays manual Gate 4 evidence: whether an observed
focus order makes sense to someone who cannot see the layout, whether
a focus ring is *noticeable* rather than merely painted, announcement
quality, and screen-reader comprehension (VoiceOver + Safari, NVDA +
Firefox, transcribed by a person). Those are prose, and marked as
prose.

**The cost boundary is structural.** No web tier ever makes a paid model
call, and three independent mechanisms enforce it rather than one
convention: the Compose overlay pins `ANTHROPIC_API_KEY` to the invalid
sentinel `local-preview-disabled`, `playwright.config.ts` overwrites the
variable in the runner process before any test loads (with
`global-setup.ts` refusing to start if it is anything else), and
`e2e/support/paid-path.ts` fulfils every paid write in the browser —
`POST /api/research`, `POST /api/conversations` and the two guided-session
writes, `POST /api/learn/sessions` and `POST /api/learn/sessions/{id}/turn`
— so no submit leg ever reaches the backend. Each count is recorded in
`web/build/e2e/research-post-count.txt`, one line per scenario, whether the
assertion passed or failed. The `web-e2e` job
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
