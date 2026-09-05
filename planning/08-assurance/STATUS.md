# Phase A — assurance campaign status

Updated: 2026-09-04

## The campaign

Owner-authorized 2026-09-04: *"expand and build out the testing, evaluation,
error handling, logging and observability for this project ... follow the true
typical testing and evaluation arc an agent takes to prove its reliable safe
accurate compliant and does exactly what we say."*

| Doc | Subject |
|---|---|
| [`00-CHARTER.md`](00-CHARTER.md) | Mandate, the R0–R10 assurance arc, hard constraints, the boundary with the agent-engineering program |
| [`01-BASELINE.md`](01-BASELINE.md) | What is measurably true on `0caefa2`, with `file:line` evidence — including what is already good |
| [`02-STANDARDS.md`](02-STANDARDS.md) | The external standards adopted, what each actually requires, and what is deliberately skipped |
| [`03-ARCHITECTURE.md`](03-ARCHITECTURE.md) | The target design the work orders implement, and the seams left open |
| [`04-WORK-ORDERS.md`](04-WORK-ORDERS.md) | Seventeen executable work orders in three waves, with file ownership and acceptance |
| [`05-GATES.md`](05-GATES.md) | Gate A1/A2/A3 criteria and what enforces each |

## Method

Planning was written from four independent read-only recon passes over `main`
(error handling, test architecture, evaluation, observability), each required
to cite `file:line` and to verify by reading code rather than inferring from
filenames, plus a standards research pass. The baseline is measured, not
estimated: `pytest -m "not e2e" -q` → **2042 passed, 52 skipped in 35.22s** on
`0caefa2`.

## Execution log

| Date | Event |
|---|---|
| 2026-09-04 | Recon complete; baseline measured; charter, baseline, architecture, work orders and gates written |
| 2026-09-04 | Standards research returned and **materially corrected the plan**: the GenAI conventions moved repositories and have no release to pin (`gen_ai.provider.name`, not `gen_ai.system`); a retry token bucket replaced the circuit breaker in WO-A04; paired McNemar comparison replaced unpaired power assumptions in WO-A09 (~77 items vs ~906); the OWASP **Agentic** list (ASI01–ASI10) replaced the LLM Top 10 as the primary safety mapping, with its CC BY-SA licence constraint recorded; verbosity-bias controls were dropped as measurably obsolete while position bias and abstention handling were kept; and **WO-A16 was added** — the arXiv domain permits deterministic groundedness measurement, so hallucination can be measured with zero model calls |

## Gate A1 — CLOSED 2026-09-04

Merged: WO-A03 (`6587410`), WO-A01 (`1673f2e`), WO-A02 (`a9a1ac2`).
Verified on the **composed** tree, not as three green PRs: 2204 passed,
52 skipped; mypy clean on 87 files; ruff clean; 31 harness-guard proofs; branch
coverage **89.21%** against the newly-measured 89% floor.

**What the harness caught on its first run, which is the case for building it:**

- **Three tests were opening live TLS connections to `api.anthropic.com` on
  every run, including in CI.** `src/learning/memory.py` reads its own
  module-level settings, so the per-module monkeypatch pattern missed it; the
  call failed on the invalid key and the module's degrade path swallowed the
  failure, so every assertion still passed and nothing went red.
- **`dotenv.load_dotenv()` bypassed env isolation entirely** — four `src`
  modules call it at import, so with a `.env` present, importing
  `src.eval.runner` moved eight assertions in four unrelated modules.
- The pragma census went red on four pragmas added by peers — the check working
  before it merged.

## Gate A2 — CLOSED 2026-09-04

Merged: WO-A15 (`68429d0`), WO-A08 (`f41ade3`), WO-A05 (`03fda80`),
WO-A06 (`1dd1660`), WO-A04 (`7e9e6cd`), WO-A07 (`df89abc`).
Verified on the composed tree at `df89abc`:

| Signal | Result |
|---|---|
| `pytest -m "not e2e"` | 2702 passed, 55 skipped |
| branch coverage | **90.10%** (floor 89) |
| `pytest -m property` | 150 passed, 14.9 s |
| `pytest -m fault` | 150 passed, 3 skipped, 10.0 s |
| `pytest -m e2e` | 13 passed, 4.6 s |
| `pytest -m security` | 172 passed, 6.8 s |
| mypy strict / ruff | clean, 90 source files |

## Gate A3 — CLOSED 2026-09-04

Merged: WO-A16 (`3618c94`), WO-A11 (`e329704`), WO-A10 (`dbebdf7`),
WO-A09 (`5e87424`), WO-A17 (`9d0a63d`), WO-A12 (`6285388`), WO-A13 (`ed71098`),
WO-A14 (`ae8bed3`). Verified on the composed tree at `ae8bed3`:

| Signal | Result |
|---|---|
| `pytest -m "not e2e"` | 3235 passed, 55 skipped |
| branch coverage | **91.31%** (floor 89) |
| `pytest -m property` | 152 passed, 16.5 s |
| `pytest -m fault` | 157 passed, 3 skipped, 10.2 s |
| `pytest -m e2e` | 16 passed, 5.7 s |
| `pytest -m security` | 314 passed, 7.2 s |
| mypy strict / ruff | clean, 93 source files |
| CI checks | 9, unchanged — the tiers gate inside the job that already existed |

## The phase in one table

| | 2026-09-04 start (`0caefa2`) | close (`ae8bed3`) |
|---|---|---|
| suite | 2042 passed | **3235 passed** |
| Python coverage | not measured anywhere | **91.31% branch, gated at 89** |
| property tests | 0 | 152 |
| fault tests | 0 | 157 |
| e2e tests | 0 — the marker had no members | 16, gating every PR |
| security tests | 172, not separately runnable | 314, own gate |
| FastAPI exception handlers | 0 | 4 |
| error codes | `type(exc).__name__` | a closed, tested set |
| correlation fields in a log line | 1 (`run_id`) | run, job, request, kind, principal hash, worker, trace, span |
| `gen_ai.*` names | 0 | the conventional span, metric and attribute set |
| OTel instruments | 9 | 21 |
| attack-success measurement | none | 3/42, Wilson 2.46–19.01%, denominators published |
| runbooks | 1 (pilot credentials) | 8 |
| ADRs | 63 | 74 |
| model spend | — | **$0.00** |

## Defects the tiers found

Every one of these was found by a tier built in this phase, before that tier
had gated a single pull request. They are bundled into **WO-A17**, except the
two routed to WO-A10 whose files it owns.

| # | Defect | Found by | Owner |
|---|---|---|---|
| 1 | The critic's ceiling is off by one; a bounded run makes an extra pass and renders `(iteration 3/2)` | e2e tier | A17 |
| 2 | The two `job_completed` SSE frames disagree; a client reading `status` off a live frame gets a `KeyError` | e2e tier | A10 |
| 3 | `CHUNKER_OVERLAP_TOKENS` may exceed `CHUNKER_MAX_TOKENS`; the splitter then emits ~one chunk per character | property tier | A17 |
| 4 | `format_sse` does not sanitise its event name; a newline splits one frame into two | property tier | A17 |
| 5 | No `upstream_model` code: a provider outage gets a *different* code depending on which node was running | fault tier | A17 |
| 6 | A Redis outage at submit moves no job metric at all — the fleet reads as idle rather than failing | fault tier | A10 |
| 7 | `job_lease_refresh_error` emitted but unregistered; the name is a variable so the AST scan missed it | fault tier | fixed in A07 |
| 8 | `admin_migrate.py` logs a principal id verbatim | A03 review | A17 |
| 9 | `synthesizer.py`'s semantic retry multiplies against the SDK envelope: 2 x 5 x 120 s against a 600 s job | A04 review | A17 |
| 10 | `pdf_parser.py`'s download timeout is a constant and gets no clamp | A04 review | A17 |
| 11 | `traced_node` put the user's raw research query on every span — content capture Phase A does not opt into | A07 | fixed in A07 |

## Corrections this campaign made to its own plan

Recorded because a plan that quietly absorbs its own errors teaches nothing:

- **`gen_ai.provider.name` is required on the inference-client span, not on
  every span.** `02-STANDARDS.md` §1.2 was unscoped. WO-A07 read `spans.yaml`
  at the pinned SHA rather than trusting the page.
- **Error families are base classes, not a naming scheme.**
  `03-ARCHITECTURE.md` §2.1 read as a rename instruction; WO-A01 refused it,
  correctly, because renaming would have falsified contract fixtures and
  forked three live metric series.
- **The circuit breaker became a retry token bucket**, and the larger finding
  was that retries happened at five levels at once.
- **Unpaired comparison became paired** (~906 items versus ~77 under McNemar).
- **The OWASP LLM Top 10 became the Agentic list (ASI01–ASI10)** as primary.
- **Verbosity-bias controls were dropped** as measurably obsolete.
- **`docs/testing.md`'s flat-layout rule was restated**: a directory may group
  by purpose, never select a tier.
- **The paired-comparison figure was overstated ~2x.** This plan quoted 77
  paired against 906 unpaired; those are not at matched power, and the
  like-for-like paired number at 80% power is 155. Corrected in
  `02-STANDARDS.md` §2.3. The conclusion holds at 6x.
- **`gen_ai.provider.name` is required on the inference-client span only**, not
  on every span — found by reading `spans.yaml` at the pinned SHA.
- **A duplicate assignment**: `admin_migrate.py` was routed to two work orders
  at once. The coordinator's error; resolved by taking one implementation and
  keeping the other's tests, which asserted something the winner had no test
  for.

## Follow-up wave — CLOSED 2026-09-05

Five work orders against the open items above, merged as PRs #189–#194.
Verified on the composed tree at `ea2b269`: **3385 passed**, 55 skipped;
branch coverage **91.67%** (floor 89); property 152, fault 163+3, e2e 16,
security 314, contract 117; mypy strict and ruff clean across 95 source files.
The leftover PR #162 also landed once the npm audit service recovered.

| WO | Closed |
|---|---|
| B1 | The five false claims, and `tests/test_documented_claims.py` — prose is now read by tests |
| B2 | Tier bands, five unbounded network steps, ADR 0045's lock procedure, and two workflows that lied about their own state |
| B3 | The supervisor's swallowed outage; all ten terminal frames converged |
| B4 | Three flags folded into `Settings`, with the conventional env name kept working |
| B5 | The honest citation metric wired at its call sites, with the rebaseline recorded |

### What the wave found that the open items did not say

- **A cancelled job's supervisor kept dispatching nodes.** The bare `except`
  in `_default_next_action` caught `JobCancelledError` — `call_llm` checks the
  cancel token before it builds a client — and answered with a route. Strictly
  worse than the reported defect, and in the same clause.
- **The redriver's terminal-frame docstring was false in both halves**: it
  claimed field-for-field sync with a function that had become a one-line
  delegate, and the copy was three fields short. A reconnecting client got 12
  keys where a still-subscribed one got 8.
- **ADR 0045's procedure would have corrupted the lock, silently.**
  `pip freeze --exclude-editable` emits 147 distributions against the lock's
  126; the documented step would have written 21 unrelated ones into what CI
  installs, and `derive_runtime_lock.py --check` would have stayed green
  because it walks only the project's own graph.
- **Three unbounded `pip install` steps, not two** — plus the image build and
  the Compose bring-up. The workflow header's "every network step is bounded"
  was further from true than the finding said.
- **`LOG_CAPTURE_USER_CONTENT` had never been "logs only"**, as documented —
  `traced_node` calls the same resolver, so it has always gated span content
  too. The doc was corrected rather than the behaviour, since making the doc
  true would have been a silent behaviour change.
- **A recursion hazard the obvious fix would have created**: warning from
  inside `content_capture_enabled()` with a `raw`-shaped `extra` recurses,
  because the formatter calls that function to decide whether to elide `raw`.

### Two coordinator instructions the builders overrode, correctly

- **A bare floor for the tier census.** I invited it; B2 refused, and proved
  it on its own branch — `contract` went 65 → 81 → 84 as peers merged
  underneath, and the floor correct for 65 no longer caught the largest
  module's loss at 81. A floor only ever looks down. Bands throughout.
- **Deriving the citation metric's epsilon from its quantum**, per ADR 0071.
  B5 refused: that metric's quantum is `1/denominator`, and the denominator is
  the report's own citation count — one, on the e2e fixture — so declaring it
  gives a band of 1.5 and an ungatable metric. The widening rule exists to
  absorb *judge* noise, and a deterministic check has none.

### One correction to this document

Phase A's register said the swallowed outage meant "no alert on any series can
see it." Overstated: `llm_upstream_errors_total` always moved, because
`src/llm.py` counts the failed call before raising. What no series could see
was the **consequence** — a run routed by nothing, reporting success. A test
now asserts that residue explicitly.

## Open items carried out of Phase A

None of these blocks the gates; each has a named home.

| # | Item | Found by |
|---|---|---|
All eight were closed by the follow-up wave (B1–B5, PRs #189–#194).

| # | Item | Found by | Closed by |
|---|---|---|---|
| 1 | `_default_next_action`'s bare `except` swallowed a provider outage | WO-A17 | B3 |
| 2 | An *emptied* tier would still pass CI | WO-A13 | B2 |
| 3 | Unbounded `pip install` steps | WO-A13 | B2 (found five, not two) |
| 4 | No test reads a prose claim | WO-A14 | B1 |
| 5 | Three flags never reached `Settings` | WO-A12 | B4 |
| 6 | Terminal frames still disagreed | WO-A10 | B3 (all ten converged) |
| 7 | `citation_accuracy` returned 1.0 for zero citations | WO-A16 | B5 |
| 8 | ADR 0045's lock procedure | WO-A02 | B2 (defect was larger) |

### Still open after wave C

| Item | Why it stays open |
|---|---|
| The "eval runs nightly" claim is still unenforced | The workflow files now say honestly that they are disabled at the repository level, so a prose-reading test has become *possible* — but `disabled_manually` remains a GitHub-side attribute absent from the checkout, and nobody has written the test |
| `README.md`'s R11, R14, R15 claims | Mechanisable, with named homes: R11's three assertions belong in `tests/test_config.py`; R14 wants the screenshots captured as Playwright snapshots; R15 wants a reflection test over `Settings`' `enable_*` fields |
| `web/vitest.config.mts`'s re-seed note | Prose in a comment, and the only source of truth for the web test count — a re-seed that skips the note leaves the check agreeing with a stale source |
| `redact_text` is a **shape** rule, not a secret rule | Measured: `sk-…` redacts, `gw_live_…` passes untouched. A gateway or proxy credential is not covered by the redaction the log contract rests on |
| Two more plain-`str` secrets | `api_keys` (inbound keystore) and `semantic_scholar_api_key`. Neither is a one-line retype — `parse_api_keys` splits the raw string and `semantic_scholar.py` builds a header from it |
| The scripted research tier scripts the model's words | The better fix is a `use_mock_data` branch on the four research agents, which would let the tier delete its scripted surface. Recorded in ADR 0075's alternatives |
| A25 ("eval runs nightly") is still False | Its blocker is gone and **the test is already written**; the remaining edit is one sentence in `docs/architecture.md`, which WO-C2 did not own |
| `docs/demo.md` carries a stale `eval.md` anchor, twice | Same fix already applied in `docs/eval.md` |
| The web test count of record is 97 tests behind reality | Within the new band; closed by the next coverage re-seed, which is not "the note" WO-C2 was licensed to change |


## Wave C — CLOSED 2026-09-05

Four work orders, merged as PRs #196–#199. Verified on the composed tree at
`f7d2d43`: **3556 passed**, 55 skipped; branch coverage **91.95%** (floor 89);
property 152, fault 163+3, e2e 16, security 314, contract 139; mypy strict and
ruff clean across 96 source files.

| WO | Closed |
|---|---|
| C1 | The research lane gets a **free** gate, and the paired McNemar path runs on it |
| C2 | The last four unenforced claims; the nightly's three artifacts reconciled |
| C3 | `LOG_PRINCIPAL_SALT` reaches `Settings` and stays a secret |
| C4 | The API key becomes a `SecretStr`; three missing Compose forwards |

### The result that justifies the statistics

WO-C1 measured it rather than arguing it: **one lost claim moves
`citation_resolution_rate` by exactly 0.10 — the flat epsilon a move must
*exceed*.** Every threshold band stays green and only the pairing fires. The
aggregate gate would shrug at a real regression; McNemar catches it.

`mcnemar_required_pairs` on the new lane: **77 pairs for significance, 155 at
80% power, and the campaign carries 100** — clears the first bar, not the
second. Printed in every report, which is what turns a funding request into a
costed one.

### The limitation WO-C1 insisted on stating

Mock mode is **not** an LLM stub for the research lane. It swaps arXiv search
only; `src/llm.py` is untouched and all four research agents call the model as
in production. So the scripted research tier scripts the *model's* words where
the learning lane scripts the *learner's*, and the consequence is written into
the module, the ADR and the docs: **it measures the pipeline around the model,
never report quality.**

### Three premises this coordinator got wrong

Recorded because the builders corrected them with measurement, not opinion.

- **The API-key exposure is narrow.** All six accessors leaked, but a sweep of
  `src/`, `tests/`, `scripts/`, `ci/`, `deploy/` and the `Makefile` found
  nothing that fires it — no call site dumps a whole `Settings`, no debug
  route, and a `ValidationError` on another field provably does not carry the
  key. The fix is defence in depth, and the PR says so.
- **No module compares the key field to the disabled sentinel.** Every
  comparison is on the environment variable. The single field-level dependency
  was a truthiness check that survived only because `bool(SecretStr(""))` is
  `False` via `__len__`.
- **Three files in the stated blast radius must not change**: they carry
  `anthropic_api_key` as a canary id and forbidden-artifact regex — the field
  *name* as data. Editing them would have broken the adversarial suite.

## Coordination

Two sessions are active on this repository and are aware of each other.

- **This campaign** owns branches `plan/08-assurance` and `assurance/wo-a*`,
  worktrees under `/private/tmp/arxiv-asr-*`, and writes nowhere under
  `docs/agent-engineering/`.
- **The agent-engineering program** owns `docs/agent-engineering/**`,
  `planning/README.md`, branches `codex/*`, and worktrees under
  `/private/tmp/arxiv-rfc-*`.

Both trees are treated as read-only by the other side.

## Standing constraints carried into this phase

Inherited from the learning-platform campaign and still binding:

- **Zero model spend** until the owner explicitly approves; every local and CI
  path runs with `ANTHROPIC_API_KEY=local-preview-disabled`.
- `nightly-eval` and `nightly-lighthouse` stay **disabled**.
- Never `gh pr merge --auto` — there is no branch protection, so it merges
  immediately rather than on green.
- Never a bare `docker compose down`; use the harness `stack.sh` with `-p`/`-f`.
- No secrets added anywhere; `web/audit-exceptions.json` entries are never
  deleted to work around a registry outage.
- Builders never merge; the coordinator merges on a strictly-verified green.

## Deferred owner decisions (not part of this phase)

W-OD-1 eval funding, W-OD-2 briefing generation, W-OD-3 licensing, W-OD-4
Rung 1 publication, W-OD-5 pilots, W-OD-6 threshold ratification, and W20
(the Gate W2 pack) remain the owner's and are untouched by Phase A. Phase A is
designed so that none of them blocks it.
