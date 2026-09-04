# Decisions and discussion guide

Status: **OPEN FOR OWNER DISCUSSION**

The broader product direction is already recorded in the learning-platform
campaign: build a real product, learn by building, keep the guided-reading
wedge first, and treat the nine longer-term directions as a portfolio rather
than simultaneous execution. This document does not reopen that decision. It
identifies the agent-engineering choices needed to turn the new program into
work orders.

## How to use this page

For each decision, choose or edit the recommendation, record the reasoning, and
date it. A decision may authorize planning without authorizing implementation,
paid evaluation, training, or deployment.

## D1 — First optimization target

**Recommendation:** improve claim support and evidence completeness through
calibrated verification and targeted repair.

Why: it builds on existing components, directly improves trust, creates useful
trajectory/reward data, and has a bounded rollback. It is more foundational
than adding open-web tools or training a policy.

Alternatives:

- improve retrieval recall first;
- improve report usefulness/organization first;
- optimize cost/latency first;
- expand guided-learning outcomes first.

Decision: **APPROVED — 2026-09-04**

Owner ruling: claim support and evidence completeness are the first
optimization target. This approves planning around calibrated verification and
targeted repair; it does not authorize implementation or a paid run.

## D2 — North-star scorecard

**Recommendation:** use a constrained scorecard rather than one scalar:

- primary: task-rubric success with claim/evidence support;
- non-inferiority: safety, citation validity, and completion rate;
- frontier dimensions: human preference/edit burden, cost, and latency.

One weighted “agent score” is convenient for training but dangerous for
product decisions because it hides tradeoffs and invites reward hacking.

Decision: **APPROVED — 2026-09-04**

Owner ruling: use the constrained scorecard above. Task-rubric success and
claim/evidence support are the primary outcomes; safety, citation validity, and
completion are non-regression gates; preference/edit burden, cost, and latency
remain separate frontier dimensions rather than one blended agent score.

## D3 — Baseline and default policy

**Recommendation:** keep the fixed research graph as the control and production
fallback until a repeated, funded comparison shows where the supervisor or a
new policy wins. Do not assume “more agentic” means better.

Experiment ruling:

- use five ordered arms to isolate the evidence path, fixed verify-and-repair,
  supervisor routing, and adaptive compute;
- hold query refinement and reader recovery out of the first comparison so
  they do not become hidden extra variables;
- report results by predeclared task slice so a higher-latency policy can win
  for difficult work without becoming the universal default.

Decision: **APPROVED — 2026-09-04**

Owner ruling: retain the fixed pipeline as the control and fallback. Evaluate
the five ordered arms in
[`07-first-policy-experiment.md`](07-first-policy-experiment.md); no candidate
becomes the default without repeated evidence and a later promotion decision.

## D4 — User-visible compute tiers

**Recommendation:** eventually offer named intent/latency tiers such as Quick,
Verified, and Deep, while allowing the system to route within each hard
envelope. Show the expected time/cost behavior without exposing internal token
counts as a quality promise.

Alternative: one automatic tier for every request. This is simpler but makes
cost and latency less predictable and provides no explicit product contract for
deep research.

Decision: **OPEN**

## D5 — Source scope

**Recommendation:** make the first improvement arXiv/Semantic Scholar-centric,
then add heterogeneous web sources as a separate capability with source policy,
freshness, provenance, and injection evaluation.

Questions:

- Are official documentation, standards, code repositories, and datasets the
  first non-paper sources?
- Should general news/web content ever be allowed for the scholarly product?
- Which sources require licenses or paid APIs?

Decision: **OPEN**

## D6 — Code and data-analysis tool

**Recommendation:** add a narrow sandboxed Python/data tool before any general
shell or repository-modification tool. Default to no network, no secrets,
immutable mounted inputs, bounded CPU/memory/time, and captured artifacts.

Questions:

- Is quantitative paper analysis a near-term user need?
- May the tool install packages or access the network with approval?
- Which artifact types should be publishable: tables, plots, notebooks, code?

Decision: **OPEN**

## D7 — Feedback experience

**Recommendation:** ask for sparse but attributable feedback: mark a factual
error, reject a citation, identify a missing topic, prefer a candidate, or
accept/edit a section. Keep the generic helpful/unhelpful control as a product
signal, not the sole learning reward.

For learning, ask whether the explanation helped and where confusion remains;
do not infer mastery from engagement.

Decision: **OPEN**

## D8 — Data consent and retention

**Recommendation:** separate these scopes explicitly:

1. necessary product operation;
2. support and abuse investigation;
3. de-identified aggregate analytics;
4. human evaluation;
5. model or policy training.

Training should be opt-in or governed by a clearly approved policy, with
retraction and deletion behavior defined before collection. Learner data should
receive the strictest default.

Decision: **OPEN — REQUIRED BEFORE FEEDBACK STORAGE OR TRAINING**

## D9 — First funded evaluation

**Recommendation:** fund measurement before new inference architecture:

- repeated current-default research campaign;
- repeated supervisor/evidence arm only if the budget permits a paired
  comparison;
- the deferred guided-learning funded row;
- a small expert claim/citation calibration set.

The exact campaign shape, model prices, maximum spend, and stop conditions must
be calculated immediately before approval because provider prices and retry
costs can change.

Decision: **OPEN — EXPLICIT COST APPROVAL REQUIRED**

## D10 — Model ownership strategy

**Recommendation:** continue using hosted frontier models for high-quality
generation while the data loop matures. If training becomes justified, begin
with an open-weight router, query planner, reranker, or verifier—small roles with
clear rewards and measurable serving economics.

Alternative: fine-tune an end-to-end research model first. This offers broader
control but needs much more data, compute, evaluation, and serving work and
makes failures harder to attribute.

Decision: **OPEN — NEEDED BEFORE P5**

## D11 — First RL target

**Recommendation:** no RL target is selected now. Revisit after P0–P3. If the
prerequisites hold, compare query planning, source selection, and compute-tier
routing on reward verifiability and expected business value.

Do not begin with free-form report generation or tutor behavior: the reward is
too subjective and safety/product regressions are easy to hide.

Decision: **DEFERRED UNTIL DATA AND REWARD AUDIT**

## D12 — Self-improvement authority

**Recommendation:** permit offline proposals and sandboxed evaluation only.
Keep evaluation data, judges, safety gates, budgets, merge, and deployment
outside the candidate's authority permanently.

Questions:

- Which files may a future candidate modify?
- May it generate new development tests if those tests never enter its score?
- Who reviews candidate lineage and benchmark-overfitting evidence?

Decision: **OPEN FOR RESEARCH POLICY; PRODUCTION SELF-MODIFICATION REJECTED**

## D13 — Long-horizon autonomy ceiling

**Recommendation:** define autonomy tiers by side effects and reversibility:

| Tier | Agent authority | Human role |
|---|---|---|
| A0 | Read and draft only | User receives an answer |
| A1 | Use bounded retrieval/analysis tools | User can inspect provenance |
| A2 | Execute a durable multi-stage plan in a sandbox | User approves scope and spend |
| A3 | Propose external or repository changes | Human approves each consequential action |
| A4 | Perform reversible external actions in an approved domain | Human sets policy and audits |

This program should target A0–A2 first. Deployment, payment, publication,
messaging, destructive changes, and credential changes remain human-controlled.

Decision: **OPEN**

## D14 — Deep-research product contract

**Recommendation:** define Deep Research as a separate mode with a richer
deliverable and longer budget, not as an invisible expansion of every query.

Candidate contract:

- hierarchical plan visible for review;
- heterogeneous primary sources with access dates;
- evidence/contradiction table;
- optional reproducible calculations;
- checkpointed progress and resumability;
- verified final claims with explicit unresolved questions;
- published time, source, and spend envelope.

Decision: **OPEN**

## D15 — Build-versus-integrate policy

**Recommendation:** keep core task, evidence, trajectory, evaluation, and
promotion contracts in-repo. Integrate commodity model gateways,
observability, sandbox runtimes, experiment trackers, and benchmark adapters
only after a small comparison against the contracts.

Avoid replacing the current system with a framework merely to obtain a feature
that can be added at one boundary. Also avoid rebuilding infrastructure whose
operational burden is unrelated to product differentiation.

Decision: **OPEN**

## Decision status and remaining discussion order

The first three decisions are approved. The remaining decisions are easier in
this order:

1. D9 — whether/when to fund the baseline;
2. D4/D14 — product compute tiers and Deep Research contract;
3. D5/D6 — new tool scope;
4. D7/D8 — feedback and data policy;
5. D10/D11 — model training and RL;
6. D12/D13 — self-improvement and autonomy authority;
7. D15 — integration choices once requirements are concrete.

## Ratified answers from the first conversation

The owner approved these answers on 2026-09-04:

```text
First target:
  claim support + evidence completeness

Primary evaluation:
  task-rubric success and supported claims,
  bounded by safety/completion non-regression,
  with cost and latency shown separately

Control:
  current fixed pipeline

First candidate:
  evidence graph + calibrated verifier abstention + targeted repair

First compute policy:
  T0 direct versus T1 verify-and-repair; deterministic routing

Training:
  deferred until consented trajectories and rewards exist

Self-improvement:
  offline proposals only; immutable external promotion gate
```

The five-arm experiment is specified in
[`07-first-policy-experiment.md`](07-first-policy-experiment.md). The next
documentation step is to write the P0 technical RFCs for `TaskSpec`,
`RunManifest`, trajectory events, and the benchmark/data registry—still without
implementing them.
