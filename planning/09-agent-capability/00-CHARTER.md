# Agent-capability lane — charter

Status: **ACTIVE — owner-authorized 2026-09-05**

Owner ruling (2026-09-05): the agent-capability work is owned by the Fable
coordinator session; Opus worker agents implement bounded work orders in
isolated worktrees; the coordinator reviews, merges on a strictly verified
green, and keeps its other duties (read-only review of the two sibling lanes).

## 1. Mandate

Make the research agent itself better, in the order the agent-engineering
program's approved decisions already fixed: claim support and evidence
completeness first (D1), the fixed pipeline stays control and fallback (D3),
and every change ships default-off behind a typed setting until a paired
evaluation says otherwise. Nothing in this lane spends model budget; funding
is deferred by the owner until the current build items across all three lanes
close.

Sources of truth this lane implements against:

- `docs/agent-engineering/07-first-policy-experiment.md` §3 — Arm C is
  "not present" and must be a structural policy, not `ENABLE_VERIFIER=true`
  on the fixed graph.
- `docs/agent-engineering/02-target-architecture.md` §4–§5 — compute tiers,
  verification cascade with abstention, recovery policy ("reflect again is
  not a recovery policy").
- `docs/agent-engineering/12-p0-work-orders.md` §11 — W05's acceptance
  requires A/B/C/D to be mechanically distinguishable.
- ADRs 0064–0075 (assurance phase) — error taxonomy, harness, GenAI
  semantic conventions, provenance, statistics, groundedness, scripted tier.

## 2. Scope

| Work order | What | Wave |
|---|---|---|
| CAP-01 | Model-aware request profiles in the gateway: structured outputs, adaptive thinking, effort, sampling only where the model accepts it, thinking-block-safe response parsing | 1 |
| CAP-02 | Arm C — fixed verify-and-repair research policy behind a `research_policy` selector; typed repair decision; one-repair cap; re-verify; abstain first-class | 1 |
| CAP-03 | Orchestrator-workers for the T2 branch tier: sub-question workers with isolated context, evidence-table merge | 2 |
| CAP-04 | Deterministic difficulty features and the T0/T1 compute controller (Arm E prerequisites) | 2 |
| CAP-05 | Anthropic SDK 1.x upgrade (lockfile change under ADR 0045's corrected procedure) | 2 |
| CAP-06 | Live smoke of CAP-01/02 against the real model — **funded; blocked on the owner** | after funding |

Out of scope for this lane: contracts (`src/contracts/**`, Puma), evaluation
harness internals (`src/eval/**`, bumblebee), frontend, infra, deployment,
model post-training, self-improvement.

## 3. Namespace and ownership

- Branches `cap/*`; worktrees `/private/tmp/arxiv-cap-*`; this directory
  `planning/09-agent-capability/**`.
- Files this lane may edit: `src/llm.py`, `src/agents/verifier.py`,
  `src/agents/synthesizer.py`, `src/graph/workflow.py`, `src/graph/state.py`
  (additive keys only), `src/config.py` (additive fields only),
  `docs/agents/*.md` for agents it changes, `.env.example` (its own settings),
  `docs/architecture.md` (additive section only), new modules it creates,
  and its own tests.
- Never edited here: `docs/agent-engineering/**`, `planning/README.md`,
  `src/contracts/**` (Puma); `planning/08-assurance/**`, `docs/assurance/**`,
  `src/eval/simulate_research.py`, `src/eval/scripted_tier_check.py`
  (bumblebee). A needed change in another lane's file is a message to that
  lane, not an edit.
- The shared main checkout at `/Users/kudratsingh/Machine-Learning-Projects/arxiv-research-agent`
  is another session's working directory. Nothing in this lane reads its
  working tree for truth or writes to it. Truth is `origin/main`.

## 4. Hard constraints

1. **Zero model spend.** Every test and local run uses
   `ANTHROPIC_API_KEY=local-preview-disabled`; the harness in
   `tests/conftest.py` blocks the network and a real client. A work order that
   needs a live call to be verified says so and stops at the request-shape
   proof (CAP-06 is where live verification lives).
2. **Default-off, byte-identical.** With every new setting at its default,
   the compiled graph, the node/edge listing, and the kwargs sent to the
   provider are identical to today. Each work order lands a golden test that
   proves it.
3. **One work order per PR.** The PR body names the work order, lists its
   acceptance criteria with the test that proves each, and states what is
   *not* verified without a live call.
4. **Merge gate.** Builders never merge. The coordinator merges only after
   `gh pr checks N --watch` settles and a bare `gh pr checks N --json name,bucket`
   shows all nine checks in the `pass` bucket. Never `--auto`.
5. **Prompts are instruments.** Judge and verifier prompt *text* is not
   changed in wave 1; changing it re-baselines a metric (ADR 0070). Request
   shape may change; wording may not.
6. **ADR per behaviour.** Each work order that changes runtime behaviour
   ships an ADR at the next free number, taken at PR time and rebased if a
   sibling lane takes it first.
7. **Total-state discipline.** New `ResearchState` keys are additive, read
   with a default at every consumer, and set in every constructor this lane
   owns. `src/eval/simulate_research.py` builds its state as `dict[str, Any]`
   and is not edited; if a test enforces constructor parity that would force
   an edit there, the worker stops and reports instead of editing.

## 5. Coordination with the sibling lanes

- **Puma / W05.** The `research_policy` selector name, its values, and the
  node names of the verify-and-repair graph are published in CAP-02's ADR so
  W05's policy-shape introspection can label Arm C. CAP-02 must land before
  W05 claims C is representable.
- **bumblebee / scripted research tier.** Default settings keep the fixed
  pipeline's node sequence unchanged, so the scripted tier's structural
  expectations and its `$0.0000` refusal are unaffected. CAP-01's golden
  request test is the guarantee the tier relies on.
- **Shared files.** `src/config.py` and `docs/architecture.md` are touched
  by all lanes; this lane's edits there are additive blocks under a
  `# ------ Agent capability (CAP-xx) ------` header so rebases stay clean.

## 6. Worker protocol

Each worker: one worktree, one branch, one work order. Read
`docs/development.md`, `docs/testing.md`, the ADRs named in the work order,
and every file it will edit before writing. Run `ruff check .`,
`mypy --strict src/`, and `pytest -m "not e2e" -q` from the worktree root
before opening the PR; run the security, property, and fault tiers when the
work order names them. Push, open the PR, post the validation output in the
body, stop. Report to the coordinator: PR number, test counts, what is
unverified without a live call, and any boundary it could not respect.

## 7. Record

`STATUS.md` in this directory is the execution log: work orders opened,
PRs, merged SHAs, composed-tree verification, defects found, premises
corrected, and what remains open. Updated by the coordinator at wave end.
