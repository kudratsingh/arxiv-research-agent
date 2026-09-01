# 0060. Evidence-grounded explain-back assessment

- **Status**: accepted
- **Date**: 2026-09-01
- **Deciders**: kudratsingh
- **Follows**: [ADR 0041](0041-retrieval-and-degradation-honesty.md),
  [ADR 0059](0059-guided-read-session-graph.md)
- **Implements**: WO-W04 in
  [`planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md`](../../planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md#wo-w04--the-explain-back-assessment-judge)

## Context

WO-W03 records an explain-back but deliberately does not interpret it. The
first assessment capability must be useful to the tutor without turning a
nondeterministic model response into a grade, a mastery bar, or an unsupported
profile claim. The highest-risk failure is a plausible gap that the learner
never expressed.

## Decision

`enable_assessment_judge` is independent and default-off, and requires the
session loop. When enabled, one call returns gaps, strengths, one optional
follow-up probe, and evidence. Every finding must carry a quote that appears
verbatim in the current learner explain-back and in the response's evidence
list. The response shape is exact: extra keys, numeric scores, missing keys,
duplicate findings, ungrounded quotes, timeouts, and parse failures all discard
the entire judgment and record `unassessed`.

The learner text is prompt-isolation wrapped. `assessment_model` follows ADR
0021's per-agent routing pattern and otherwise uses `anthropic_model`.

The result is tutor guidance only. Raw gaps, strengths, and evidence are absent
from `SessionDetail`, SSE frames, and the web-client contract. The append-only
assessment event retains the internal evidence for audit, but the public
progress view exposes only that an evidence-backed assessment happened.

When a grounded gap includes a follow-up probe, the graph offers exactly one
additional learner turn and then moves through a fixed edge to progress update.
There is no judge revision loop and no second assessment call. With the flag
off, WO-W03's informal recorded-ungraded close remains unchanged.

WO-W09's checked-in calibration set is explicitly unratified. Therefore even a
valid assessment cannot write an `assessed` skill claim or present a grade.
That boundary changes only after owner-ratified, funded calibration evidence.

## Consequences

- A malformed or unavailable judge is observable as `unassessed`, never as an
  empty set of gaps that could be mistaken for success.
- One grounded gap may add one learner turn and its associated model-free
  waiting time; cost remains one assessment call.
- Mock mode constructs no client and records `unassessed` rather than inventing
  a synthetic judgment.
- A future profile-write card must consume the ratified calibration gate; this
  ADR grants it no authority to promote skills.
