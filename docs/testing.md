# Testing strategy

Every piece of code merged into `main` has tests. Untested code doesn't
merge. This page describes the suite **as it exists** — the layout on
disk, the markers that select tiers, and what CI actually runs. Earlier
versions of this page described an aspirational directory layout, and
carried a section for an e2e tier that was planned but not built; that
drift is exactly how gaps hide, so the rule is: this page documents
reality, and planned work is labelled as such. The e2e tier is now
built (WO-A15) and its section describes what it does, including what
it still does not cover.

Two suites live here and they are selected differently. The **Python**
suite is flat and marker-selected; that is what the sections up to
"Selective execution" describe. The **web** suite under `web/` has
**eight tiers** — unit, component, story, integration, contract, e2e,
accessibility and budgets — described with a local command each in "The
web suite" below. `e2e` means different things in the two: in Python it
is the whole-workflow tier in `tests/e2e/`, run from `make test-e2e` in
mock mode at zero spend, and in `web/` it is the Playwright tier
against a seeded Compose stack. Both gate a PR, in different jobs.

Two counts in this page are **not the same list**: CI runs **nine**
parallel *jobs*, and the web suite has **eight** *tiers*. Several tiers
share the `web` job; three jobs (`lint`, `docker-build`, `web-audit`)
carry no web tier at all.

## Layout — flat, marker-selected

Tests live **flat** in `tests/test_*.py` — there are no `tests/unit/`
or `tests/integration/` directories, because the tier is a marker, not
a path. One test module per source module (`tests/test_chunker.py` ↔
`src/tools/chunker.py`), named so the mapping is obvious. Fixtures
live in the test modules that use them.

Three directories exist — `tests/e2e/` (WO-A15), `tests/property/`
(WO-A05) and `tests/fault/` (WO-A06) — and they earn the exception
rather than contradicting the rule. Each holds a tier with a harness of
its own worth a scoped `conftest.py`, and inside each directory the
modules are still flat and still marker-selected.

The rule, stated precisely so the next one does not have to re-argue
it: **a directory may group tests by purpose; it may never be how a
tier is selected.** `pytest -m fault` finds every fault test whether it
lives in `tests/fault/` or beside the module it exercises, and moving a
file between directories changes nothing about what runs. Nothing
selects on the path.

## Markers: two orthogonal axes

Markers are registered in `pyproject.toml` under
`[tool.pytest.ini_options].markers`, and `--strict-markers` means an
unregistered one is a startup error rather than a test that silently
never runs. There are two axes and they answer different questions
(ADR [0065](decisions/0065-test-isolation-and-coverage-floor.md)).

**Tier — how much a test costs. Exactly one per test, enforced.**

- `unit` — a module or a function in isolation. No server, no compiled
  LangGraph workflow, no live network. Temp-file I/O is allowed;
  "no I/O at all" was never the operative rule here and pretending
  otherwise just pushes tests into the wrong tier.
- `integration` — external libraries and local servers on fixtures:
  fakeredis for Redis, `pytest-postgresql` for Postgres, an ASGI app
  driven through httpx, canned XML for arXiv, a checked-in sample PDF
  for PyMuPDF. Still no live network.
- `e2e` — a whole workflow end to end at zero spend, asserted on the
  trajectory it took. 16 tests, in `tests/e2e/` (see "The e2e tier"
  below). Excluded from the merge gate's first selection, so a change
  here does not move what CI measures coverage over; it runs as its own
  step in the same job (WO-A13).

**Purpose — what a test protects. Zero or more, orthogonal to the tier.**

- `security` — asserts a boundary: tenancy scoping, prompt injection,
  SSRF, auth, rate limiting, redaction.
- `property` — hypothesis-driven; asserts an invariant over generated
  input. Built by WO-A05, in `tests/property/`.
- `fault` — asserts behaviour when a dependency fails.
- `contract` — pins a wire shape: OpenAPI snapshot, SSE event names,
  fixture parity, container and deployment contracts.
- `network` — the opt-out from the conftest network guard. Exactly one
  member, the test that proves the opt-out works. A second member should
  be argued for in a PR body.

The purpose axis is what makes a boundary runnable on its own. Before
it existed, "run the tenancy and injection tests" had no expression;
now it is `make test-security`.

**State of the suite** (measured on `c3d63da` with WO-B2 applied,
`pytest --collect-only`): **3,456 tests collected** from **2,977 `def
test_` functions** across **139 modules** — the gap is parametrization.
By tier: 3,005 `unit` + 435 `integration` + 16 `e2e` = 3,456, which is
the whole suite, because the tier axis is a partition and a test module
with no tier fails `tests/test_harness_guards.py`. By purpose: 314
`security`, 166 `fault`, 152 `property`, 117 `contract`, 1 `network`.

The four purpose counts have a **band** around them since WO-B2, in
`tests/test_harness_guards.py`. Nothing else notices a tier going
empty: purpose markers gate a merge only by sitting inside the `-m
"not e2e"` selection, so a renamed marker or a deleted `pytestmark`
takes the tier out of CI without taking a single test red. The bands
are stated over test *functions* rather than collected items — 40
`property` functions expand to the 152 collected above — with the
**floor** at 80% of the measured population, set so that dropping the
tier's largest single module lands below it, and the **ceiling** at
twice it. The ceiling is there because a floor only ever looks down: a
tier that doubles leaves its floor reading as 80% of the tier in the
comment and 40% of it in fact. Growing past the ceiling is not a
failure of the tier — it is the change that grew it being asked to
re-centre the band.

> Earlier versions of this page reported 1,426 collected with "roughly
> half the suite carrying no marker at all". Both halves of that are now
> out of date: the count was stale, and the 38 unmarked modules were
> tagged by WO-A02. `pytest -m unit` is now a real tier rather than an
> arbitrary subset. CI still selects with `-m "not e2e"`.

**One known gap in the tier data.** Twelve modules marked `unit` build
a real ASGI app (`tests/test_api_auth.py`, `test_api_lazy_imports.py`,
`test_api_learn_routes.py`, `test_bounded_executor_cancel.py`,
`test_contract_learn_fixtures.py`, `test_contract_openapi_snapshot.py`,
`test_errors.py`, `test_guided_session_graph.py`,
`test_learn_profile_routes.py`, `test_otel_metrics.py`,
`test_per_principal_scoping.py`, `test_workflow_startup_once.py`). By
the definition above they are `integration`. WO-A02 classified the
*previously unmarked* modules honestly but did not re-tier these,
because moving twelve modules changes what `make test` runs and that
belongs in its own reviewable PR. It does not affect the merge gate,
which selects `-m "not e2e"`.

## What actually gates a merge

The per-PR CI workflow (`.github/workflows/ci.yml`, design in ADR
[0024](decisions/0024-pr-ci-lint-mypy-tests.md)) runs nine parallel
jobs on every PR and every push to `main`:

1. `lint` — `ruff check .`
2. `typecheck` — `mypy --strict src/`
3. `tests` — **every Python tier, under coverage**. Five gates in one
   job, and the reasoning for that shape is written out in the workflow:
   - `make test-cov` — the unit and integration tiers, which is
     everything but the 16 `e2e` tests. The runner reports **3,259
     passed and 2 skipped** where a laptop reports 3,206 and 55:
     Postgres is on PATH in this job, so the integration tests that
     skip locally actually run. With the **project floor and the four
     per-package floors** enforced — through the Makefile target, not a
     pytest line copied into the workflow, so the floors have one
     definition (`pyproject.toml` for the project number, `COV_API` /
     `COV_AGENTS` / `COV_SECURITY` / `COV_EVAL` for the packages).
     `property`, `fault` and `security` are purpose markers *inside*
     this selection, so all three run here — and, since WO-B2, a band
     on each one's membership runs with them, because "inside the
     selection" is not the same as "gated" for a tier that has gone
     empty
   - **patch coverage** — `diff-cover` against `origin/main` at the
     `COV_DIFF` floor, reading the XML the step above wrote rather than
     running the suite a second time
   - **the `e2e` tier** — `make test-e2e`, 16 tests in ~5 s, in mock
     mode at zero spend. Wired in by WO-A13; before that the `-m "not
     e2e"` filter excluded it from CI entirely
   - **the adversarial safety suite** (ADR 0072) — the 42-case corpus
     against this checkout's own defences, publishing its
     attack-success rate as an artifact
   - the **scripted learner-simulation campaign**: all fifteen
     guided-read scenarios driven through the real session graph in mock
     mode, with `src/eval/scripted_tier_check.py` asserting 15/15
     sessions and `$0.0000` spend from the run's `summary.jsonl` (WO-W11;
     see [`eval.md`](eval.md), "The per-PR scripted tier")

   Three artifacts, all under `if: always()` so a red run still leaves
   its evidence: `python-coverage` (the XML, the term report and the
   patch-coverage HTML), `safety-attack-success-rate` and
   `scripted-simulation-summary`
4. `docker-build` — API image build + base and production compose-file
   validation
5. `web-image` — `docker build ./web`, run it against a stub upstream,
   probe `/` and `/api/healthz` through the proxy
6. `web` — TypeScript typecheck, ESLint, contract drift, Vitest **with
   coverage thresholds**, and the production build **with the route
   budget check**. Four gates, all of them local compute, ~4 min
7. `web-audit` — the **dependency audit gate** (`npm run audit:gate`).
   Its own job since 2026-09-04, because it is the one web gate whose
   answer comes from a remote service (npm's advisory endpoint): when
   that endpoint degraded, an unbounded audit call spent the whole
   `web` job ceiling and the four gates above were cancelled unreported
   on three PRs and three main runs. It is a **hard gate** — an audit
   that could not run is red, not green — but it can no longer take
   anything else down with it. Uploads the `web-npm-audit` artifact
8. `web-storybook` — story tests and the static Storybook build
9. `web-e2e` — Compose up + seed + Playwright + axe, chromium only

Every network step in that workflow carries its own `timeout-minutes`
and npm fetch bounds (`NPM_CONFIG_FETCH_TIMEOUT` and friends), because
a job-level ceiling bounds the *job*, not a step that hangs — npm's
default is a five-minute timeout **per request** with two retries.

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

Local equivalent of the Python half of the gate — the same commands CI
runs, in the same order:

```bash
make test-cov        # unit + integration under the project and package floors
make test-cov-diff   # patch coverage for this branch vs origin/main
make test-e2e        # the e2e tier, mock mode, zero spend
.venv/bin/python -m src.eval.safety_suite
make typecheck
.venv/bin/python -m ruff check src/ tests/
```

Both coverage floors gate a PR as of WO-A13; until then they were a
local convention and the workflow ran a bare `pytest -m "not e2e" -q`.
CI reaches the same targets with `make <target> VENV_PYTHON=python`,
because `$(VENV_PYTHON)` is `.venv/bin/python` on a desk and a runner
has no venv. The one difference is that CI's patch-coverage step reads
the XML the coverage step already wrote instead of running the suite
again; branch, floor and verdict are identical, so a green
`make test-cov-diff` here means a green step there.

**`make test` is still not the merge gate.** It expands to
`pytest -m unit`, which selects a real tier (2,826 of 3,277 tests)
rather than an arbitrary subset — but it is a tier, not the suite. The
merge gate is `-m "not e2e"` **plus the e2e tier as its own step**,
which is every test in the repository. ADR 0024's follow-up ("add a
merge-to-main variant that runs `pytest -m 'unit or integration'`") is
closed by that: `-m "unit or integration"` selects the same 3,261 tests
`-m "not e2e"` does, and the 16 the filter drops are now run beside it.

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
| 6 | E2E | the vertical slice, the guided-read session, and one whole guided read start-to-close against the seeded local stack | `npm run e2e` (stack first — see below) | `web-e2e` |
| 7 | Accessibility | axe over every state × theme, plus keyboard, zoom and reduced-motion probes; also per story at tier 3 | `npm run e2e -- --grep "@axe\|@a11y"` | `web-e2e`, `web-storybook` |
| 8 | Budgets | per-route gzip ceilings in `web/budgets.json` | `npm run budgets` | `web` |

Tier 3 runs in jsdom, not a real browser, so it needs no Playwright
install; tiers 6 and 7 do. `npm run build-storybook` additionally
proves the static bundle builds, which is what `web-storybook` uploads.

**Tier 6 has a second, local-only stack (WO-W17).** `npm run e2e:pilot`
runs `web/e2e/pilot.spec.ts` against a stack with a Caddy edge, two
pilot principals and no shared web key, under its own Playwright config
(`web/playwright.pilot.config.ts`). It cannot share the `web-e2e` job's
stack — the pilot map and the shared key are mutually exclusive by
design, and the `baseline-*` fixtures belong to a principal neither
pilot holds — and no Phase W card edits a workflow, so **CI runs it as
five skipped tests with a reason** and the isolation proof is a local
run recorded in the WO-W17 and WO-W17b PRs. What CI *does* prove about
the mode is the whole unit tier: `web/tests/pilotPrincipal.test.ts`
drives the real route handler through every guard,
`web/tests/workspaceIdentity.test.ts` drives the identity descriptor the
header renders through the same guards,
`web/tests/shell/identity.test.tsx` compares the rendered identity slot
against the markup it produced before that descriptor existed, and
`web/tests/principal.test.ts` passes unmodified — which together are the
mode-off byte-identity claim. `web/e2e/README.md` §"The pilot tier" is
the manual.

Two further gates are not tiers of their own — both are red jobs, not
reports. Coverage rides on the Vitest tier inside `web`; the dependency
audit runs as the separate `web-audit` job (see "What actually gates a
merge" above for why it is not inside `web`):

| Gate | Command | Where | What fails it |
|---|---|---|---|
| Coverage | `npm run test -- --coverage` | `web` | falling below the thresholds in `web/vitest.config.mts` |
| Dependency audit | `npm run audit:gate` | `web-audit` | any high/critical advisory in the production tree, or one in the dev tree that `web/audit-exceptions.json` does not name — or an audit that could not reach npm's advisory endpoint inside its 6-minute bound |

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

**The copy honesty gates.** Every user-facing string lives in
`web/lib/copy/`, and two mechanisms keep it there and keep it honest.
An ESLint rule (`copy/no-inline-text`) rejects rendered string
literals inside `components/patterns/` and `components/features/`;
`web/tests/copy/forbidden.test.ts` walks every exported value of every
copy module, **drives every exported composer**, and applies the
forbidden-string deny-list, seam S6's ownership prohibition and the
lexicon to the result. A composer with no entry in that file's table
fails its coverage assertion rather than escaping the walk.

The learning surfaces are held to one list more. `PEDAGOGY_PHRASES` in
`web/lib/copy/index.ts` bans mastery, percentages, "unlocked", XP,
streaks and streak-guilt phrasing, badges, proficiency, any knowledge
scalar, "score", "grade" and "dashboard" — the copy half of the ban
`src/learning/progress_store.py` already enforces at its write
boundary and in a CHECK constraint. It applies to every copy module
the `(learn)` route group's import graph reaches, and that set is
**discovered by walking the graph** rather than listed, so a new
learning surface is covered the moment it renders a string. It is
scoped to those modules on purpose: "quality score" is the research
metric's real name and cannot be banned product-wide.

Both gates are proven by committed fixtures that **must fail** —
`web/tests/fixtures/copy-inline.fixture.tsx` for the lint rule and
`web/tests/fixtures/copy-pedagogy.fixture.ts` ("87% mastered") for the
pedagogy list — because a rule nobody has watched fire is a convention
rather than a gate. Neither fixture is inside `npm run lint`'s scope
(`app`, `components`, `lib`), so a file that is supposed to fail
cannot turn the repository red.

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
call, and four independent mechanisms enforce it rather than one
convention: the Compose overlay pins `ANTHROPIC_API_KEY` to the invalid
sentinel `local-preview-disabled`, `playwright.config.ts` overwrites the
variable in the runner process before any test loads (with
`global-setup.ts` refusing to start if it is anything else),
`e2e/support/paid-path.ts` fulfils every paid write in the browser —
`POST /api/research`, `POST /api/conversations` and the two guided-session
writes, `POST /api/learn/sessions` and `POST /api/learn/sessions/{id}/turn`
— so no submit leg ever reaches the backend, and the overlay pins
`USE_MOCK_DATA=true`, under which the session graph constructs no model
client on any path. Each count is recorded in
`web/build/e2e/research-post-count.txt`, one line per scenario, whether the
assertion passed or failed. The `web-e2e` job
hard-codes the same sentinel and is never given the repository secret;
`web/tests/ci.test.ts` asserts that against the workflow's own text.

The **one** place a write is forwarded rather than fulfilled is
`e2e/session-flow.spec.ts`, which needs the graph to actually start, park,
checkpoint and resume for Gate W1's end-to-end row. It opts in explicitly
(`sessionMode: "mock-pass-through"`) and `e2e/support/mock-mode.ts` refuses
unless both pins above are present — in the overlay and, when a Docker daemon
is reachable, in the running container. The counts still land in
`research-post-count.txt`, with a `mode=` column so a forwarded row cannot be
read as an interdicted one, and the finished session's own `llm_calls` is
asserted to be 0. `POST /api/research` has no such mode and is 0 on every
row. `web/e2e/README.md` is the long form.

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
every test target keeps the prefix, and
`tests/test_harness_guards.py::TestMakefileTestTargets` pins it for
targets added after that file was written, by discovering them instead
of listing them.

`TEST_ENV` also carries `PYTHONHASHSEED=0`. That one is about
determinism, not about crashes, and it has to be in the environment
rather than in `conftest.py`: CPython reads it once at interpreter
start, so setting it from inside a running process reaches only the
subprocesses the suite spawns.

## The harness: what `tests/conftest.py` guarantees

Until ADR [0065](decisions/0065-test-isolation-and-coverage-floor.md)
there was **no `conftest.py` anywhere** in the repository. Four
properties everyone assumed held were only usually true, and the suite
could not tell you when they did not. All four are now autouse — a test
cannot forget them, and opting out leaves a marker in the diff.

| Guarantee | What it does | Opt out |
|---|---|---|
| Env isolation | The developer's `.env` is not read, and every environment variable `Settings` declares is scrubbed before `src.config` is first imported. The suite then declares its own: `ANTHROPIC_API_KEY=local-preview-disabled`. `Settings(_env_file=...)` still works when a test asks for a file explicitly. | none |
| Network guard | A `connect`/`connect_ex` to any non-loopback address raises `NetworkAccessDenied`, naming the test. Loopback and unix sockets pass, so `pytest-postgresql` and every ASGI transport are unaffected. DNS is untouched — `tests/test_pdf_parser.py` patches `getaddrinfo` for the SSRF checks. | `@pytest.mark.network` |
| Spend guard | `src.llm._get_client` raises `LLMSpendDenied` unless a fake is installed — either by patching `_get_client` itself (twenty existing call sites) or by patching `src.llm.anthropic.Anthropic` (what `tests/test_llm.py::TestGetClient` does, since it tests the construction logic). The denial fires on exactly one condition: a real client about to be built with a real key. | install a fake |
| Determinism | `random` reseeded before *every* test, so a failure reproduces from its node id without a recorded ordering. `numpy`'s global RNG too when it is loaded. A `frozen_clock` fixture is available (not autouse) for the modules that hand-patch time. | `frozen_clock` is opt-in |

Both guard exceptions derive from `BaseException`, not `Exception`.
That is deliberate: this codebase degrades gracefully on purpose, and
around fifty `except Exception` sites implement that. A guard those
handlers can swallow reports a green test for a run that reached the
internet.

**It found something on day one.** Three tests —
`tests/test_assessment_judge.py::TestGraphIntegration` (two) and
`tests/test_guided_session_graph.py::TestSessionApiEndToEnd` — were
opening live TLS connections to the Anthropic API on every single run,
including in CI. `progress_update_agent` summarises a session through
`src/learning/memory.py`, which reads its *own* module-level settings;
that module was missing from both files' per-module patch lists, so the
summary call went to the real client, failed on the invalid key, and
was absorbed by the module's degrade path. The assertions passed. This
is precisely the failure mode `tests/test_api_smoke_e2e.py` had already
described in prose — per-module monkeypatching is not a seam — and it
is the argument for a structural guard over a convention.

**Strictness that comes with it**, all in `[tool.pytest.ini_options]`:
`--strict-markers` (an unregistered marker is a startup error, so
`@pytest.mark.uni` can no longer be a test that never runs),
`--strict-config`, `xfail_strict` (an xfail that starts passing is a
failure), a 60-second per-test timeout via `pytest-timeout` — about 13×
the slowest test measured (4.4s) — and `filterwarnings = ["error", ...]`.
Three scoped exemptions remain, each naming the message it mutes: the
SWIG `DeprecationWarning`s that faiss and PyMuPDF raise at import
(`SwigPyObject`, `swigvarlink`, `SwigPyPacked`). They drop out when both
projects ship a SWIG release that sets `__module__` on its builtin
types. A fourth exemption was written for Starlette's
`HTTP_422_UNPROCESSABLE_ENTITY` deprecation — attributed by stack level
to FastAPI, but really ours, since `src/api/routes.py` read the
deprecated alias — and was deleted before this landed: WO-A01's error
taxonomy removed the last reader. A dead exemption is worse than none,
so exemptions are re-tested, not inherited.

## Coverage policy

The web half has enforced coverage thresholds since WO-24. The Python
half measured nothing at all — no `pytest-cov`, no `coverage`, nothing
in the lock, the Makefile or CI. That asymmetry was the finding, not
the percentage.

**Branch coverage, not line coverage.** Line coverage systematically
over-reports on compound conditions, and this codebase is full of them;
a fully line-covered `if a and b` can leave half its outcomes untried.

**Every floor is a measured value, rounded down. The rule is ratchet up
only.** A threshold nobody can meet is a threshold that gets skipped —
the same reasoning the web budgets and Vitest thresholds are set by.
Raising a floor is a normal PR. Lowering one requires the reason in the
PR body.

Measured on `pytest -m "not e2e"` when the gate was adopted
(11,214 statements, 3,216 branches):

| Scope | Measured | Floor | Where the floor lives |
|---|---|---|---|
| project | 89.21% | **89** | `pyproject.toml` `[tool.coverage.report].fail_under` |
| `src/api` | 86.60% | **86** | `Makefile` `COV_API` |
| `src/agents` | 92.59% | **92** | `Makefile` `COV_AGENTS` |
| `src/security` | 97.37% | **97** | `Makefile` `COV_SECURITY` |
| `src/eval` | 91.05% | **91** | `Makefile` `COV_EVAL` |
| changed lines | — | **90** | `Makefile` `COV_DIFF` (`make test-cov-diff`) |

The per-package floors are in the Makefile because coverage.py's
`fail_under` is global; a project number can hold steady while the one
package that matters rots underneath it. For reference, the packages
without a floor measured: `src/tools` 79.31%, `src/learning` 84.94%,
`src/graph` 90.89%, `src/content` 92.97%, `src/observability` 94.89%.
`src/tools` and `src/learning` are the two worth a floor next, and
neither has one yet precisely because setting it would be aspirational
rather than measured-and-held.

**Ratchet from the desk number, not the CI one.** The same target
reports **92.39%** in the `tests` job and **91.31%** on a laptop at the
same commit, because CI puts Postgres on PATH and the integration tests
that skip locally run there. A floor lifted to the CI measurement is a floor no
developer can meet before pushing, which is how a gate stops being run
locally at all.

**Patch coverage is the number that matters on a PR.** Project coverage
improves logarithmically — a large diff can be entirely untested while
the total barely moves. `make test-cov-diff` runs `diff-cover` against
`origin/main`, entirely locally: no service, no account, no token.

**Both floors gate in CI since WO-A13**, in the `tests` job, through
these same Makefile targets. The project and per-package floors fail
the job from `make test-cov`; patch coverage fails it from `diff-cover`
at `COV_DIFF`. The reports upload as the `python-coverage` artifact
(XML, the term report, and an HTML page naming which of the PR's own
lines are missing) with 30-day retention, because Gate A3 cites them.
A run against `main` has an empty diff and diff-cover passes it — the
patch floor is a claim about a change, and a push to `main` is not one.

**Three integrity checks, because gates get gamed.** All three live in
`tests/test_harness_guards.py`:

1. Exclusions are configured centrally in
   `[tool.coverage.report].exclude_also`, each with a written reason,
   and `[tool.coverage.run].omit` is empty and asserted empty — an
   `omit` entry is an exclusion with no reason and no line in the
   report. Inline `# pragma: no cover` is capped at its census (16) and
   every one must carry a reason after a dash. Pragma growth is the most
   reliable symptom of a gate being met on paper — and this check earned
   its keep before it merged, catching four new pragmas that arrived
   with WO-A01 and WO-A03 while WO-A02 was in review.
2. `--cov-context=test` records which test executed each line, so
   `coverage html --show-contexts` answers "who covers this?" — the
   question that exposes code executed by a test that asserts nothing
   about it.
3. Each purpose marker carries a band on its membership (WO-B2). A
   tier that stops selecting tests is the one regression a suite cannot
   report on its own, because the tests that would have gone red were
   never collected: emptying `property` entirely on `de54129` left
   `pytest -m "not e2e"` at **3,352 passed, 55 skipped** — green, with
   152 tests silently gone — while `pytest -m property` exited 5 with
   nothing to run. The bands read the source
   rather than the session's collection, so they hold under a filtered
   run as well as under the gate's. The same treatment was applied in
   the same PR to `tests/test_operability_docs.py`'s instrument count,
   which was a bare `>= 20` — and it is why `docs/architecture.md`
   could go on claiming nine OTel instruments while the real set grew
   to twenty-one with every test green.

**`make test-cov` pins `COVERAGE_CORE=ctrace`**, and it has to. From
Python 3.14 — the version `.python-version` pins — coverage defaults to
the `sys.monitoring` core, which does not support context switching,
so pytest-cov's `--cov-context=test` makes it warn `no-sysmon-context`
once per test; this suite turns warnings into errors, so the target
errored on every test it ran. WO-A13 found it by running the target on
CI for the first time: 3,208 tests, 6,414 errors, none of them about
the code under test. A 3.13 desk venv never saw it, because below 3.14
the C tracer is already the default.

The real counter-pressure to coverage theatre is the `property` and
`fault` tiers, not a higher percentage — which is why they have bands
of their own rather than being trusted to stay populated.

## Flake policy

**No blanket reruns.** Roughly one in six newly-flaky tests is masking a
real production defect, so `--reruns` applied to everything converts
that signal into green noise. The policy, for when a rerun plugin is
eventually added (`pytest-rerunfailures` is not a dependency today —
this paragraph is the policy, not the wiring):

- Reruns apply **only** to tests explicitly marked flaky, and **only**
  to error classes that are legitimately environmental:
  `--only-rerun 'ConnectionError|TimeoutError'`. Never `AssertionError`
  — an assertion that fails intermittently is a bug report.
- Quarantine is a **marker plus a non-blocking job**, never a `skip`.
  A skipped test is a deleted test that still looks present in the count.
- The number of quarantined tests is capped and the cap is visible. A
  quarantine that grows without a bound is a second, unmeasured suite.
- A quarantined test carries the issue it is waiting on. No issue, no
  quarantine.

## Selective execution

The durable selection mechanism is the marker filter. Two of them gate
a merge, in that order: `-m "not e2e"` under coverage, then `-m e2e`.
The purpose axis adds three more selectors, each of which crosses tiers
on purpose — a boundary is not a speed. They run inside the gate's
first selection rather than beside it, so these targets are for running
one of them alone, not for making it gate:

```bash
make test-security   # 314 tests: tenancy, injection, SSRF, auth, redaction
make test-fault      # 160 tests: behaviour when a dependency fails
make test-property   # 152 tests: Hypothesis invariants
make test-e2e        #  16 tests: whole workflows, ~5s, $0.0000
```

Path-based selection (running only the test modules that mirror a PR's
changed source paths) was considered in ADR 0024 and deliberately
deferred: at the suite's current wall clock (~tens of seconds),
selection logic costs more to maintain than it saves. Revisit when a
full run crosses ~2 minutes.

## Test writing standards

- One test module per source module, named `tests/test_<module>.py`.
- Module-level `pytestmark = pytest.mark.unit` (or `integration`) on
  new modules so tier membership is explicit rather than implied. A
  module with no tier fails `tests/test_harness_guards.py`, so this is
  a gate rather than a convention. When one class in a module belongs to
  a different tier, declare the tier **per class** rather than adding a
  second module-level marker — two tiers on one test is also a failure.
- Add a purpose marker when the test protects a boundary, an invariant,
  a failure mode or a wire shape. `pytestmark = [pytest.mark.unit,
  pytest.mark.security]` is the list form.
- Prefer parametrized tests (`@pytest.mark.parametrize`) over
  copy-paste.
- Never hit real external services in unit or integration tiers —
  fakeredis for Redis, `pytest-postgresql` for Postgres, monkeypatched
  `call_llm_json` for Claude. The conftest network and spend guards
  enforce this, but they are the floor: a test that trips one is a test
  that was going to be wrong in CI.
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

## The property tier

`tests/property/`, selected by `pytest -m property`, run with Hypothesis. 36
properties expand to 126 cases in roughly 15 seconds. Where the rest of the
suite asserts that a specific input produces a specific output, these assert
that **something is true of every input** — no chunk exceeds its budget,
header-free text survives chunking byte-for-byte, a generated secret never
appears in a redacted string, an encode/decode round-trip is the identity, a
value outside a declared range is always refused.

Two rules keep the tier honest:

- **The profile is pinned and `derandomize` is on in CI**, so a failure is
  reproducible from the report alone rather than "it failed once on Tuesday".
- **A property must be able to fail.** WO-A05's PR body records six seeded
  mutants — a deliberate off-by-one in the chunker window, a narrowed API-key
  pattern, a dropped citation suffix — and shows each one being caught. A
  property that no mutation can falsify is decoration, and the mutant check is
  how you find out which kind you wrote.

Run the wider profile before opening a PR: `HYPOTHESIS_PROFILE=explore` draws
far more examples and has already falsified a property that the default
profile passed — the property was wrong and the production code was right,
which is the outcome worth knowing about before review rather than after.

## The fault tier

`tests/fault/`, selected by `pytest -m fault`, ~150 cases in about 10 seconds.
Unit tests exercise the happy path, so error-handling code is the least-tested
code in most systems by construction. This tier asserts what happens when a
dependency fails: Redis gone at submit and mid-job, the Postgres pool
exhausted, the model provider returning 429/500/timeout, cancellation between
and inside nodes, a worker dying with its lease outstanding, the cost cap
tripping mid-run, an SSE terminal frame that never lands.

**Every fault test asserts the triple: the right error code, the right log
event, and the right metric.** That is the point of the tier and not a style
preference — it is what makes the error contract (ADR 0064), the log contract
(ADR 0067) and the telemetry contract (ADR 0066) enforce each other instead of
being three claims maintained separately. A test that only asserts "an
exception was raised" does not belong here.

Where a gap is known and not yet fixed, the tier pins it explicitly rather
than staying silent — a Redis outage at submit currently moves no job metric
at all, and there is an `assert_not_recorded` saying so, so the day someone
fixes it the assertion fails and tells them.

## The e2e tier

`tests/e2e/`, marked `e2e`, **16 tests in ~5s**. Run it with `make
test-e2e`. It drives whole workflows from a caller's first call to
their last, and asserts on the **trajectory** each one took rather than
on the prose it produced (WO-A15; design in
`planning/08-assurance/03-ARCHITECTURE.md` §3.6).

This page carried "planned, not built: the e2e cassette tier" for a
long time, and the tier that got built is not the one that was planned.
Two decisions differ from that plan and both are deliberate.

**Mock mode, not cassettes.** Recording VCR-style cassettes needs a
paid session to create and a second paid session every time a prompt
changes. Mock mode is the zero-spend seam this repository already
proves works: the scripted learner-simulation campaign has run all
fifteen guided-read scenarios through the real session graph in the
per-PR gate, for `$0.0000`, since WO-W11. The tier reuses that seam
instead of buying a new one.

**A directory, not flat modules.** Everything else in `tests/` is flat
(see "Layout"), and the tier keeps that convention *inside*
`tests/e2e/`. It has a directory because it has a shared harness worth
one `conftest.py` — the settings installer, the canned agent surface,
and the autouse cost ledger below — and because `tests/fixtures/e2e/`
needs somewhere to belong.

### What "mock mode" does and does not cover

Worth stating plainly, because the asymmetry is easy to get wrong and
costs money when you do. `USE_MOCK_DATA` swaps the arXiv search for
five fixture papers (`src/agents/search.py`) and makes the tutor and
the assessment judge deterministic (`src/agents/tutor.py`,
`src/agents/assessment.py`). It does **not** touch `src/llm.py`. So:

- the **session graph** runs free on mock mode alone — no Anthropic
  client is constructed anywhere on its path, which is why
  `simulate_learner` can drive fifteen sessions in CI;
- the **research graph** does not. Its planner, reader, synthesizer and
  critic call `call_llm_json` under mock mode exactly as they do in
  production, so the tier cans those four per module, the way
  `tests/test_api_smoke_e2e.py` does. `call_llm_json` is imported into
  each agent's own namespace; patching `src.llm.call_llm_json` does
  nothing.

### Zero spend, asserted rather than assumed

Every e2e test asserts its run cost exactly `$0.0000`. That is a
deliverable of the tier, not a nicety, and it rests on four layers:

1. `make test-e2e` pins `USE_MOCK_DATA=true` and the
   `local-preview-disabled` sentinel, the same pair `simulate-learner`
   pins.
2. `tests/conftest.py` denies `src.llm._get_client` unless a fake is
   installed, and denies any non-loopback socket. Both raise
   `BaseException` subclasses, so the agents' `except Exception`
   fallbacks cannot swallow them.
3. The canned agent surface means `record_llm_call` is never reached,
   so the accumulator cannot move.
4. `tests/e2e/conftest.py`'s **autouse** `zero_spend_ledger` binds a
   cost accumulator to every test in the directory and asserts at
   teardown that it never moved — so a test added here gets the check
   whether or not its author writes one.

Two numbers, always, because they fail differently: a dollar total can
round to zero from spend that really happened, a call count cannot.
This is the pair `src/eval/scripted_tier_check.py` settled on for the
same reason. Where a job runs in its own context — anything driven
through `run_job` — the accumulator this fixture holds cannot see the
job's spend, so those tests assert `cost_usd` and `llm_calls` on the
job row and on the terminal SSE frame, and the exported markdown's
`| Cost | $0.0000 |` line, which is the claim as a user reads it.

### What each module asserts

- `test_research_workflow.py` — the fixed pipeline start to report. The
  node sequence read two independent ways (LangGraph's own `stream`
  chunk keys and the `name` each agent stamped on its message), the
  iteration count, citations that survived the synthesizer's parser,
  and a bounded revision loop: a critic that never approves must route
  back to the node it named and must stop at `max_iterations`.
- `test_guided_session.py` — a guided read driven through all four of
  its pauses with `Command(resume=...)`, the way
  `src/eval/simulate_learner.py` drives it. Node sequence, the four
  turn kinds in order, the honest `recorded_ungraded` assessment (ADR
  0060), evidence-linked progress events, a pause that survives into a
  rebuilt graph, and an early exit that closes without inventing an
  assessment.
- `test_http_surface.py` — submit, stream, fetch, export. It serves the
  app with **uvicorn on an ephemeral loopback port** rather than
  through `httpx.ASGITransport`, because that transport does not
  stream: it runs the whole ASGI app to completion and buffers the
  body, so an SSE response only arrives once the job has already
  finished. A real socket is the only way to prove a client attached
  mid-run is told what is happening while it happens. The conftest
  network guard allows loopback by design; nothing leaves the machine.
- `test_hitl_review.py` — the plan-review breakpoint driven to each of
  its three ends (revise, approve, cancel), plus the `hitl_bypass`
  path. `tests/test_api_hitl.py` already covers the route against a
  stub; what only this can show is that the reviewer's decision reaches
  the graph — the revised plan is read back out of the checkpointer
  after the run, and a cancel is asserted to have stopped *at* the
  planner rather than after searching and reading.

### Where it runs, and what it still does not cover

**This tier gates a merge.** WO-A15 built it, WO-A13 wired it in: the
coverage step still selects `-m "not e2e"`, and `make test-e2e` runs
immediately after it as its own step in the same `tests` job. It got a
step rather than a job because 16 tests in 5 seconds do not justify a
runner spin-up and a second install of the ML stack, and it stays
outside the coverage selection because the floors were measured against
`-m "not e2e"` — running the tier must not lift the project number and
re-baseline a floor as a side effect.

The old warning on this page is half retired and half still true. The
sequence-level gap is closed: workflow wiring, state schema, the
router's revision branch, the HITL resume, the session pause and the
SSE frame trajectory are all now driven end to end, and the class of
break ADR 0040 records has a test that would have caught it. What is
still uncovered is real LLM **content** — every model call in this tier
is canned, so nothing here says a prompt change produced a worse
report. That remains the nightly LLM-judged eval's job, and no test in
`tests/` should be described as covering it.

A live-API mode behind an `E2E_LIVE=1` flag was in the original plan
and is deliberately not built. It would be a spend path with no gate in
front of it in a repository whose whole assurance posture is that spend
is structurally impossible in the test suite; the funded lane already
exists for that, in `src/eval/`, where it is budgeted and metered.
