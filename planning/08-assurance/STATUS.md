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
| [`04-WORK-ORDERS.md`](04-WORK-ORDERS.md) | Sixteen executable work orders in three waves, with file ownership and acceptance |
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
