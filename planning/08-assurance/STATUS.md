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
