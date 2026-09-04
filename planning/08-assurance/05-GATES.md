# Phase A gates

Status: **PROPOSED**

Three gates, one per wave. A gate is not a status meeting: it is a list of
statements that are either mechanically true on `main` or the gate does not
close. Every criterion below names the thing that fails when the criterion
stops holding, because a criterion with no enforcement is a wish.

## How a gate closes

1. Every work order in the wave is merged to `main`.
2. `main` is re-verified **as a whole** — not as the sum of individually green
   PRs. Individually green PRs have already failed to compose once in this
   repository (#94–#96 → #97), and the response to that lesson is a probe of
   the merged tree, not more confidence.
3. An evidence pack is assembled under `evidence/gate-aN/` from CI artifacts
   and runner-verified local output. **No number in a pack is typed by hand.**
4. Anything that did not close is written into `known-gaps.md` with a
   numbered section, an owner, and whether it blocks the next gate.

## Gate A1 — Foundations

Closes after WO-A01, A02, A03.

| # | Criterion | Enforced by |
|---|---|---|
| A1.1 | The suite cannot reach a non-loopback address | network-guard test in `tests/conftest.py` |
| A1.2 | The suite cannot construct a real model client | spend-guard test |
| A1.3 | A developer `.env` cannot change a test outcome | env-isolation test |
| A1.4 | Every test file carries exactly one tier marker | marker-completeness test |
| A1.5 | A mistyped marker fails collection | `--strict-markers` |
| A1.6 | Python coverage is measured and has a floor | `fail_under` in `[tool.coverage]`, CI step (A13 wires it) |
| A1.7 | Every client-visible failure has a stable code from a closed set | `ERROR_CODES` test |
| A1.8 | An unhandled exception yields the envelope, an ERROR log, and no upstream text | bare-`Exception` handler test |
| A1.9 | `job.error` contains no raw exception text | simulated-psycopg-failure test |
| A1.10 | A log line can be joined to its run, job, request and principal | log-context test |
| A1.11 | An un-allowlisted log field is dropped, not merged | allowlist test |
| A1.12 | User content is not logged by default | report-body test |

**Evidence pack:** local gate output (test counts, mypy, ruff), the coverage
report with its measured floor, the marker census, and the diff of the error
code set.

## Gate A2 — Behaviour

Closes after WO-A04, A05, A06, A07, A08, A15.

| # | Criterion | Enforced by |
|---|---|---|
| A2.1 | An upstream outage opens a breaker instead of paying the full retry envelope | breaker state tests |
| A2.2 | A healthy system behaves exactly as before the breaker existed | pass-through test |
| A2.3 | A Redis outage degrades the rate limiter rather than returning 500 | fault test |
| A2.4 | A poison job dead-letters instead of looping | redriver attempt-counter test |
| A2.5 | Every timeout is configuration, not a literal | settings test + grep assertion |
| A2.6 | Parser and redaction invariants hold on generated input | `pytest -m property` |
| A2.7 | Every fault asserts a code, a log event, and a metric | `pytest -m fault` |
| A2.8 | Model calls are spans, and submit → node → call is one trace | trace-continuity test |
| A2.9 | Telemetry names follow the GenAI conventions | literal-name test |
| A2.10 | Budget-exhausted sessions no longer report as successes | metric attribute test |
| A2.11 | A judge cannot silently follow the product model | judge-pinning test |
| A2.12 | A rubric edit without a version bump fails | prompt-hash test |
| A2.13 | Every eval row states what produced it | provenance test |
| A2.14 | The full agent workflow is asserted end to end at zero cost | `pytest -m e2e` |

**Evidence pack:** the property, fault and e2e tier outputs with wall times; a
trace showing one id across submit/node/call; a scripted-tier `summary.jsonl`
row showing the provenance block; the `$0.0000` assertion.

## Gate A3 — Assurance

Closes after WO-A09, A10, A11, A12, A13, A14.

| # | Criterion | Enforced by |
|---|---|---|
| A3.1 | The regression gate reports intervals and says when N is too small | stats tests + report snapshot |
| A3.2 | A single quantized judge flip no longer trips the gate alone | epsilon test |
| A3.3 | Repeats aggregate before they are compared | aggregation test |
| A3.4 | `/readyz` fails when a dependency is down | readiness test |
| A3.5 | HTTP RED metrics exist and are cardinality-bounded | middleware tests |
| A3.6 | An obedient-but-paraphrasing injection response fails containment | safety suite |
| A3.7 | Attack success rate is reported with its denominator | safety gate artifact |
| A3.8 | Zero-tolerance safety classes fail on a single occurrence | safety suite |
| A3.9 | Every alerted metric name exists in the code | name-consistency test |
| A3.10 | Every incident the instruments surface has a runbook | runbook index test |
| A3.11 | The new tiers gate on every PR | CI shape pin |
| A3.12 | Every README claim maps to its enforcement, or is listed as unenforced | claim index |
| A3.13 | The framework mapping has an honest "not satisfied" column | review |

**Evidence pack:** the CI run that gates the new tiers, the safety report with
its denominators, the claim → enforcement index, the framework mapping, and
the model card.

## What a gate does not do

- It does not approve spend. Funded evaluation stays blocked on the owner's
  W-OD-1 regardless of what any gate here says.
- It does not enable a nightly workflow.
- It does not certify compliance. The framework mapping in WO-A14 records what
  this repository can evidence; a certification claim would require an
  external auditor and is not something a gate of ours can grant.
