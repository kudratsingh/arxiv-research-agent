# 0097. Degradation reasons reach the trajectory, so a campaign can count them

- **Status**: accepted
- **Date**: 2026-09-17
- **Deciders**: agent-capability lane (E4)

## Context

E3 shipped the campaign report (`src/campaign/report.py`, `python -m
src.campaign report`). Its error-taxonomy section maps 03 §8's thirteen
failure classes onto the codes that exist on `main`, and it obeys one
rule strictly: **a class this campaign's records carry no signal for
prints `not detected from records`, never `0`** — because an unmeasured
class is not an absent one, and a zero on an error table reads as a
clean run.

Five of the thirteen rows printed that on the 300-episode mock matrix.
One of them — **task understanding** — is correct and permanent: 15 §7.1
calls it a quality judgement rather than a runtime event, and no code
will ever produce it. The other four were an artefact:

| Class | Why it could not be counted |
|---|---|
| planning / decomposition | `planner_plan_fallback_to_query`, `planner_response_unparseable` — log lines only |
| retrieval miss | `search_empty_keeping_prior_papers` — log line only; the rubric half needs judges |
| parsing / chunking / ranking | `reader_degraded_to_abstract_only`, `reader_paper_abstract_only` — log lines only; a *failed* extraction already reached the trajectory |
| synthesis / organization | `synthesizer_response_unparseable`, `synthesizer_retry_budget_exhausted` — log lines only; the rubric half needs judges |
| citation / provenance | `synthesizer_citations_dropped` — log line only; unresolved citations were already counted from the scores |

Eight codes, and **a campaign record keeps no log.** The episode record
holds scores, cost and a pointer to a durable trajectory; the logs go
wherever the process's handler sends them and are not part of the
evidence a report reads. So the report could not count these however
faithfully they were emitted.

This is ADR 0081's finding one rung further up. That ADR put the
degradation ladder on `research_degradations_total` because a degraded
run *succeeds*: `research_jobs_total{status="succeeded"}` is the correct
answer for it and useless for seeing it, and
`research_job_duration_seconds` *improves*, because reading an abstract
is faster than reading a paper. ADR 0081 fixed that for an operator
watching a dashboard. It did not fix it for an analyst reading a
campaign, because it deliberately kept the *reason* off the metric —
"the metric answers how much and where, the log answers why" — and the
log is exactly what a campaign does not have.

## Decision

**One new trajectory event kind, `degradation.recorded`, emitted at the
eight sites in addition to the log line they already write and the
counter ADR 0081 already moves.**

### The metric and the log are untouched

Three records, three questions, and none of them is a replacement:

- the **log line** is the reason, greppable, with the site's own
  specific fields (`n_prior`, `fallback_reasons`, `elapsed_sec`). Every
  site keeps its own distinct event, which is `docs/reliability.md` §5's
  rule and the reason ADR 0081 declined to fold the rungs onto one.
- the **counter** is how much and where, with two closed attributes and
  no cardinality risk. `record_degradation_rung` is unchanged, still
  called from the sites that count a rung, and this ADR adds no
  instrument and no attribute.
- the **trajectory event** is the record a *campaign* can read back.

Independence matters here rather than being tidy: `record_degradation_rung`
returns on its provider `None` check when `enable_metrics` is off, and
the campaign matrix runs with metrics off. A degradation hung off the
metric helper would have been recorded in an API worker and nowhere
else, which is the one place it was already visible.

### It is a new kind, not `failure.recorded`

RFC 10 §8.8 has `failure.recorded` — "non-terminal or terminal
diagnostic", status `failed`, payload `failure_class`. It was the
obvious reuse and it is wrong twice.

**A degraded run succeeded.** That is ADR 0081's whole argument, and an
event carrying `status: failed` on a run that completed would put
failure-shaped rows on successful runs. `degradation.recorded` carries
`succeeded`, which is the honest envelope: the action completed, in a
degraded state.

**The class would be wrong.** `report.py` already maps
`failure.recorded` onto `tool_runtime`. A planner falling back to the
raw query is planning/decomposition, not a tool failure; routing it
through the failure vocabulary would have moved eight codes into the
catch-all and left the four classes reading zero anyway.

`action.skipped` was the other candidate and is worse: it maps to
safety/policy refusal, and nothing here was refused.

### The payload names its own class

`{degradation_id, taxonomy_class, error_code, component}`.

`taxonomy_class` is on the event rather than derived by the reader. The
alternative was a code-to-class table in `report.py` beside
`_REASON_CLASS` and `_EVENT_CLASS`, which is where such tables already
live — and which would have been a **second** vocabulary, maintained in
a different package from the eight sites that mint it, free to drift the
moment a ninth code is added. The site that degraded knows which class
it degraded in; making it say so is one string at the call site and no
table at all.

The field is `error_code`, not `error_class`. The contract's own
validator requires `error_class` and `failure_class` to hold a canonical
`AppError` code (ADR 0064), and a degradation code is a `KNOWN_EVENTS`
log-event name. Reusing the name would have meant either widening that
check or inventing `AppError` subclasses for eight things that are not
errors.

`degradation_id` is a per-run ordinal (`deg-001`), assigned by the
bridge. The sites do not mint ids: a deterministic ordinal is what keeps
two runs of the same fixture that degrade the same way byte-identical,
the property `_event_id`'s uuid5 derivation exists to preserve.

### The transport is a `ContextVar` observer, not a state key

The eight sites are inside `src/agents/`. None of them can reach a run:
the bridge is opened by the runner and the agents receive only a
`ResearchState`. Two ways across, and the repository has both.

**The state-update channel** — `observe_branches` and
`observe_selection` read `worker_branches` and `candidate_selection` off
the dict a node returns. Rejected: three of the eight sites are not in a
node at all. `_record_fallback` runs inside the reader's per-paper
thread pool, `_second_attempt_fits` is a clock check inside a retry
helper, and `_parse_citations` is a coercion routine. Threading a return
value out of those would have reshaped three functions to carry a
diagnostic, and adding a key to `ResearchState` would have put a new
field in every eval record's `state` block.

**A bound observer** — what `bind_llm_call_observer` already is, for the
identical reason, stated in its own docstring: "the reader's per-paper
fan-out records from a thread pool, and the API runner copies its
context into every node thread". `record_degradation_reason` reads a
`ContextVar`; `observe_degradations(run)` binds it around the workflow
invocation at the three places a run exists — the API runner, the eval
runner, and the campaign executor.

Unbound is the default and costs one `ContextVar` read. **That is the
property every golden rests on**: a run that degrades nothing records
nothing, so the scripted tier, the mock matrix and the eval records are
byte-identical to what they were.

### Scope of the binding

Around the policy and nothing else. In the campaign executor the scope
closes before the scorer runs and before the terminal event is written,
because a judge or a harness degrading is not the arm degrading — ADR
0050's boundary, applied to a third kind of record.

## Consequences

- **The report counts four more classes.** Planning/decomposition
  becomes a `record` class outright. Retrieval miss and
  synthesis/organization keep `judge` detection but gain a
  `record_signal` flag: they are counted on a judge-free pass, and their
  note says the number is a **floor** rather than the class, because the
  rubric half is still missing. Refusing to say that would have been the
  same laundering in the other direction.
- **One row still reads `not detected from records`**, and it is the
  right one. 15 §7.1 and §12.6 are amended from five to one.
- **On the mock matrix all four read `0`, and the zero is now honest.**
  `use_mock_data` short-circuits ahead of every one of the eight sites,
  so nothing degrades. That is why the matrix cannot be the proof:
  `tests/test_degradation_trajectory.py` drives each site with the
  harness's fake client and asserts the observation, one test per code,
  closed in both directions against `DEGRADATION_CODES`.
- **A fourth closed vocabulary**, after `ERROR_CODES` (ADR 0064),
  `KNOWN_EVENTS` (ADR 0067) and ADR 0081's rungs — and it is deliberately
  a *subset* of the second: every degradation code is also a log-event
  name, so an operator grepping a log and an analyst reading a campaign
  are naming the same thing. Enforced by an AST parse of `src/`, which
  is the distinction ADR 0081 draws: a fixture proves the fixture agrees
  with the constant; a parse proves the call sites do.
- **The registry digest moves.** `EVENT_REGISTRY_DIGEST` is computed
  over the definitions, `len(EVENT_TYPE_DEFINITIONS)` is floored rather
  than pinned, and the addition is additive — no existing kind changed,
  so no historical event needs an upcaster and `registry parity` is
  unaffected.
- **Not free for a production job.** An API research job now records
  degradations on its in-memory trajectory. The payload is four bounded
  strings from two closed sets, `content_class` stays `metadata`, and no
  user content is involved, so the D8 posture is unchanged.
- **The obvious next rung is the reverse direction.**
  `tests/test_degradation_ladder.py` pins which published rungs have no
  emitter; nothing yet pins which *log-only* degradation codes have no
  trajectory event. The eight are closed in both directions, but a ninth
  log-only code could be added tomorrow and only this ADR would notice.

## Alternatives considered

- **A code-to-class table in `report.py`** — smallest diff, and the
  module already has two such tables. Rejected: a second vocabulary in a
  different package from the sites that mint it, which is exactly the
  drift 15 §7.1's own third column had already suffered.
- **Reuse `failure.recorded`** — no contract change at all. Rejected on
  both counts above: the status would be a lie and the class would be
  the catch-all.
- **Add `reason` as a metric attribute, as `docs/reliability.md` §7
  originally sketched** — ADR 0081 rejected it for unbounded
  cardinality, and nothing about a campaign changes that argument. A
  campaign is not read off a time series.
- **A state key on `ResearchState`** — no new module, no contextvar.
  Rejected: three of the eight sites are not in a node, and the key
  would appear in every eval record's `state` block, moving goldens for
  runs that degraded nothing.
- **Emit from `record_degradation_rung`** — one call site per
  degradation instead of two. Rejected: that helper returns early when
  metrics are off, which is every campaign process, so the record would
  have existed precisely where it was already visible. Moving the
  observer ahead of the `None` check would have put a second read on the
  one hot path ADR 0081 optimised.
