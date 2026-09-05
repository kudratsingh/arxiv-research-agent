# 0076. Make arm C a research policy, not a flag combination

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Agent-capability lane (CAP-02)

## Context

[`07-first-policy-experiment.md`](../agent-engineering/07-first-policy-experiment.md)
§3 defines five arms and records that one of them does not exist:

> **Implementation status:** not present. The current `enable_verifier`
> setting adds a supervisor action and is a no-op in the fixed graph.
> Arm C therefore requires a new fixed verify-and-repair policy and
> tests before execution.

That is exactly right about the code.
[`src/graph/workflow.py`](../../src/graph/workflow.py) had two shapes
selected by one boolean, and
[`src/agents/verifier.py`](../../src/agents/verifier.py) was reachable
only as a supervisor action. `ENABLE_VERIFIER=true` with
`ENABLE_SUPERVISOR=false` — the configuration a reader of the settings
table would reach for to "turn on verification in the fixed graph" —
compiles the plain fixed pipeline and verifies nothing.

Three consequences, and they compound:

1. **An experiment could not run arm C.** It could only run something
   and label it C.
2. **W05 cannot label what does not exist.**
   [`12-p0-work-orders.md`](../agent-engineering/12-p0-work-orders.md)
   §11 makes "C cannot be represented by `ENABLE_VERIFIER=true` under
   the fixed graph" an acceptance criterion for the run manifest's
   policy-shape introspection. Without a structural selector to read,
   the introspection has nothing to be right about.
3. **Verification that changes nothing is not verification.**
   [`02-target-architecture.md`](../agent-engineering/02-target-architecture.md)
   §5 requires a failed check to return a bounded, named recovery
   action, and ends the section with "reflect again is not a recovery
   policy". Today's verifier returns a recommendation *string* that only
   the supervisor reads.

The forcing function is the order of the lane's own work: CAP-02 must
land before W05 can claim C is representable, and before any funded
campaign can enter its dry-run resolution with an arm it can prove.

Two assumptions, either of which would change the answer if false: that
the first experiment freezes prompt text as its instrument (ADR
[0070](0070-eval-integrity-provenance.md)), and that arm C is a *fixed*
policy — if dynamic routing were allowed in, C and D would stop being
separable and the experiment would lose the contrast H3 exists to
measure.

## Decision

### One selector, refused when its companions contradict it

```python
research_policy: Literal["legacy", "fixed_verify_repair"] = "legacy"
```

`legacy` is the default and derives the graph from `enable_supervisor`
exactly as before: arms A, B and D stay expressed by
`ENABLE_SUPERVISOR` / `ENABLE_EVIDENCE_STORE` / `ENABLE_VERIFIER`,
untouched.

`fixed_verify_repair` refuses to load unless
`enable_supervisor=false`, `enable_evidence_store=true` and
`enable_verifier=false`. All seven other combinations raise at settings
load with a message naming every offending flag. The refusal is about
labelling, not about the graph: a run that recorded
`research_policy=fixed_verify_repair` on its manifest while the
supervisor owned routing would be compared to arm B as though it were
arm C, and no amount of downstream analysis could detect that.

### One new graph shape

```text
planner -> search -> reader -> synthesizer -> verify
verify  -> repair        (verdict fail, repair_count == 0, an action exists)
verify  -> critic        (pass | abstain | the repair is spent)
repair  -> search        (retrieve_missing_evidence)
repair  -> synthesizer   (qualify_or_remove_claims)
repair  -> critic        (total-router fallback; unreachable through verify)
critic  -> route_after_critique   (unchanged)
```

New node names: **`verify`** and **`repair`**. Every existing node name
is unchanged, and `_build_fixed_pipeline` and `_build_supervisor_loop`
are untouched.

### Three verdicts, and abstain is one of them

`verify` wraps the same judge, with the same prompt, at the same cost,
and classifies the result:

| Verdict | When | Reason codes |
|---|---|---|
| `pass` | the judge approved every cited claim | `verified` |
| `fail` | the judge reported a problem | `unsupported_claims`, `missing_evidence`, `unsupported_and_missing`, `verifier_reported_failure` |
| `abstain` | nothing was judged | `no_draft`, `no_citations`, `upstream_model`, `upstream_model_output` |

Abstention is not a polite failure. Every path that reaches a result
without a usable judgement — an empty draft, a report with no citations,
a provider that did not answer, output the parser could not use — has
found no fault, and a policy that repaired on it would spend the run's
one repair on a diagnosis nobody made. The last two codes are
`src/errors.py`'s own, reused so the two surfaces join.

The supervisor's `verified` boolean is unchanged, including its
conservative `verified=False` on an unusable judge response. The verdict
is the new value; the old field keeps its ADR-0015 meaning.

### The repair is a table, not a model call

`src/policies/repair.py::decide_repair(state) -> RepairDecision` is
pure: no LLM, no settings, no I/O.

| Verifier output | Action | Executes |
|---|---|---|
| `missing_evidence` non-empty | `retrieve_missing_evidence` | search with the named gaps as queries -> reader -> synthesizer |
| `unsupported_claims` non-empty, no missing evidence | `qualify_or_remove_claims` | synthesizer, with the claims listed in a bounded extra user-prompt block |
| verdict `pass` or `abstain` | `none` | straight to the critic |

Precedence between the two implemented repairs is deliberate: retrieval
can make an unsupported claim supportable, while rewriting a claim
cannot make a missing source appear.

Three more reason codes carry `none` where a repair was indicated but is
not built: `reread_sections_not_implemented` and
`rewrite_section_not_implemented` for two of the five repairs 07 §3
approves, and `missing_evidence_all_tried` for gaps the run has already
searched. Naming them is what lets an evaluation count how often the
missing repair was the indicated one, instead of seeing an
undifferentiated "nothing happened".

Gap queries are deduplicated against `tried_search_queries` with the
query refiner's own normalisation and capped at five. The refiner stays
off; only its rule is reused.

### Bounds

One repair per run — `repair_count` is incremented by the repair node
whether or not the decision found something to do, so the cap holds even
for a repair that turns out to be a no-op. Every repair is followed by
re-verification. The critic's revision loop and `max_iterations` are
untouched and run *after* verification, so the two recoveries stay
separable in a trajectory. Cost, cancellation and timeout enforcement
are the gateway's and the node wrapper's (ADRs
[0047](0047-bounded-executor-and-cooperative-cancel.md),
[0051](0051-llm-cost-enforcement-and-visibility.md)) and are not
duplicated here.

### State

Four keys, in a `total=False` block `ResearchState` inherits:
`verification_verdict`, `verification_reason`, `repair_count`,
`repair_action`. They are written by `verify` and `repair` and by
nothing else, so their presence on a state is itself the signal that arm
C ran. Optional rather than total because three initial-state
constructors build `ResearchState` as a literal and two of them belong
to other work orders; a required key would either break `mypy --strict`
on a fenced file or move the scripted research tier's committed
baseline.

## Alternatives considered

- **`ENABLE_VERIFY_REPAIR` as a fourth boolean.** Cheapest, and the one
  07 §4 explicitly rules out: "Do not add these as ad hoc Boolean
  combinations." Four independent booleans describe sixteen
  configurations, of which the experiment names five; the other eleven
  are unlabelled things a campaign can be run in by accident. A selector
  with a validator makes the unlabelled ones unloadable.
- **Let the verifier's `recommended_action` choose the repair.** It
  already exists and reads like a decision. But it is a model output:
  the same state could produce a different repair on every run, and a
  campaign could not attribute an outcome to the policy. The
  recommendation is still read — as the input to two of the
  `not_implemented` codes — but it does not decide.
- **A repair that loops until the verifier is satisfied.** Rejected on
  the same evidence the critic's `max_iterations` rests on: an unbounded
  self-correction loop is a spend multiplier with no measured quality
  ceiling, and this arm's hypothesis (H2) is about *one* targeted
  repair, not about convergence.
- **Reset `repair_count` when the critic sends the run back.** It would
  let a revised report earn a fresh repair. Rejected: the cap is
  per-run, the critic's loop is already bounded, and two recoveries
  compounding would make the arm's cost unpredictable and its
  attribution ambiguous.
- **Implement all five approved repairs now.** Re-reading named sections
  needs a reader that accepts a section brief, and section-scoped
  rewriting needs a synthesizer that can regenerate one section. Both
  are real work orders; shipping them badly here would put untested
  behaviour inside the arm the experiment is meant to measure.

## Consequences

- **Positive.** Arm C exists and is structural: no combination of the
  three legacy flags produces it, which is the property W05's
  policy-shape introspection needs and which
  `tests/test_research_policy.py` asserts over all eight combinations.
  A failed check now changes the result instead of writing a string
  nobody reads. Default settings are unchanged, proven by a golden node
  and edge listing captured before the change and by the scripted
  research tier passing unmoved.
- **Negative.** Arm C costs one extra model call on every run and four
  on a repaired one (verify, the repair's synthesis, re-verify, plus the
  reader fan-out when the repair retrieves). A third shape is a third
  thing to keep working: `docs/architecture.md` now describes three
  graphs, and any future node added to "the fixed pipeline" has two
  places to be added. The verifier's judgement quality is the arm's
  whole substrate and remains unmeasured (see below).
- **Follow-ups.**
  - The verdict and the repair action are carried on state and published
    on the SSE `node_completed` frame, not as their own log events: the
    closed `KNOWN_EVENTS` registry lives in `src/observability/`, which
    CAP-02 does not own. Two names — one for the verdict, one for the
    repair — are a one-line follow-up for whoever holds that package.
  - The two `not_implemented` repairs are a later work order, as are
    section-scoped rewriting and the reader-brief re-read.
  - `docs/architecture.md`'s heading still reads "two shapes" above an
    additive third-shape section; correcting it touches a line three
    lanes are editing and was left for the coordinator.

## What W05 may rely on

Published surface, changed only with a new ADR:

- the setting `research_policy` and its values `legacy` and
  `fixed_verify_repair`;
- the requirement that `fixed_verify_repair` implies
  `enable_supervisor=false`, `enable_evidence_store=true`,
  `enable_verifier=false`, enforced at settings load;
- the node names `verify` and `repair`, and that they appear in no other
  shape;
- the state keys `verification_verdict` (`pass` | `fail` | `abstain` |
  `""`), `verification_reason`, `repair_count`, `repair_action`;
- `src/policies/repair.py::REPAIR_ACTIONS` as the closed set of repair
  names.

## What is not verified without a live call

Everything above is structure, and structure is all this work order
proves. Specifically **not** established here:

- that the verifier's judgements are correct, or that its `abstain`
  rate against real drafts is low enough for the arm to be informative;
- that either repair improves claim support — H2 is a hypothesis, and
  this ADR builds the mechanism that lets it be tested, not evidence for
  it;
- that the repair's extra call is worth its cost or latency;
- that the bounded repair instruction has the intended effect on a real
  model's output. The block is asserted to reach the prompt; what a
  model does with it is unmeasured.

CAP-06 is the funded live smoke where those become answerable. Until it
runs, no number produced by this policy may be quoted as a quality
finding.
