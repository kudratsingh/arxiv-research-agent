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

Two counts in this page are **not the same list**: CI runs **nine**
parallel *jobs*, and the web suite has **eight** *tiers*. Several tiers
share the `web` job; three jobs (`lint`, `docker-build`, `web-audit`)
carry no web tier at all.

## Layout — flat, marker-selected

All tests live **flat** in `tests/test_*.py` — there are no
`tests/unit/`, `tests/integration/`, or `tests/e2e/` directories. One
test module per source module (`tests/test_chunker.py` ↔
`src/tools/chunker.py`), named so the mapping is obvious. Fixtures
live in the test modules that use them.

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
- `e2e` — the full workflow end to end at zero spend. **Zero tests carry
  this marker today** (see "Planned, not built" below).

**Purpose — what a test protects. Zero or more, orthogonal to the tier.**

- `security` — asserts a boundary: tenancy scoping, prompt injection,
  SSRF, auth, rate limiting, redaction.
- `property` — hypothesis-driven; asserts an invariant over generated
  input. **Zero members today**; the tier is WO-A05.
- `fault` — asserts behaviour when a dependency fails.
- `contract` — pins a wire shape: OpenAPI snapshot, SSE event names,
  fixture parity, container and deployment contracts.
- `network` — the opt-out from the conftest network guard. Exactly one
  member, the test that proves the opt-out works. A second member should
  be argued for in a PR body.

The purpose axis is what makes a boundary runnable on its own. Before
it existed, "run the tenancy and injection tests" had no expression;
now it is `make test-security`.

**State of the suite** (measured, `pytest --collect-only`): **2,256
tests collected** from **2,080 `def test_` functions** across **103
modules** — the gap is parametrization. By tier: 1,929 `unit` + 327
`integration` = 2,256, which is the whole suite, because the tier axis
is a partition and a test module with no tier fails
`tests/test_harness_guards.py`. By purpose: 157 `security`, 86 `fault`,
40 `contract`, 1 `network`, 0 `property`.

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

Local equivalent of the Python half of the gate:

```bash
.venv/bin/python -m pytest tests/ -q -m "not e2e"
make typecheck
.venv/bin/python -m ruff check src/ tests/
```

Plus, for a change that touches `src/`, the coverage floors:

```bash
make test-cov        # project + per-package floors
make test-cov-diff   # patch coverage for this branch vs origin/main
```

Neither runs in CI yet — wiring them into `.github/workflows/ci.yml`
needs a workflow edit, which WO-A02 did not own. Until that lands they
are a local gate, and the numbers below are the record of where the
floors were set.

**`make test` is still not the merge gate.** It expands to
`pytest -m unit`, which now selects a real tier (1,929 of 2,256 tests)
rather than an arbitrary subset — but it is a tier, not the suite. The
merge gate is `-m "not e2e"`. ADR 0024's follow-up ("add a
merge-to-main variant that runs `pytest -m 'unit or integration'`") is
now *safe* to close as written, because the tier axis is a partition
and `-m "unit or integration"` selects all 2,256 tests; the earlier
objection — that filter silently dropping half the suite — no longer
holds. It remains redundant with `-m "not e2e"`.

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

**Patch coverage is the number that matters on a PR.** Project coverage
improves logarithmically — a large diff can be entirely untested while
the total barely moves. `make test-cov-diff` runs `diff-cover` against
`origin/main`, entirely locally: no service, no account, no token.

**Two integrity checks, because coverage gates get gamed.** Both live
in `tests/test_harness_guards.py`:

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

The real counter-pressure to coverage theatre is the `property` and
`fault` tiers, not a higher percentage.

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

The durable selection mechanism is the marker filter; `-m "not e2e"`
is the only filter that gates a merge. The purpose axis adds three
local selectors, each of which crosses tiers on purpose — a boundary is
not a speed:

```bash
make test-security   # 157 tests: tenancy, injection, SSRF, auth, redaction
make test-fault      #  86 tests: behaviour when a dependency fails
make test-property   #   0 tests until WO-A05 lands the first one
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
