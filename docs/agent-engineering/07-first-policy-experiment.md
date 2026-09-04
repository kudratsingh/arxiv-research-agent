# First research-policy experiment

Status: **DESIGN APPROVED — IMPLEMENTATION AND EXECUTION DEFERRED**

Approved by the owner: **2026-09-04**

This protocol implements decisions D1–D3:

- optimize claim support and evidence completeness first;
- judge success with a constrained scorecard rather than one scalar;
- retain the fixed pipeline as control and fallback;
- compare the five configurations approved below;
- run the funded experiment only after a separate cost estimate and explicit
  approval.

No result exists yet. Arms C and E require new behavior, so the full experiment
cannot be run against the current code without mislabeling the arms.

## 1. Research question

For scholarly research tasks, which policy produces the strongest supported
and complete answer under bounded safety, reliability, latency, and spend?

The experiment should answer four ordered questions:

1. Does the evidence path improve outcomes relative to the fixed control?
2. Does verification with targeted repair improve outcomes relative to merely
   producing evidence records?
3. Does supervisor-controlled routing improve outcomes relative to a fixed
   verify-and-repair policy?
4. Does adaptive test-time compute improve the quality/cost frontier relative
   to the best non-adaptive policy?

## 2. Hypotheses

| Id | Contrast | Hypothesis |
|---|---|---|
| H1 | B versus A | Typed evidence improves supported-claim and evidence-coverage outcomes without a safety or completion regression. |
| H2 | C versus B | Acting on failed/abstained checks through targeted repair improves claim support or rubric completion enough to justify its incremental cost and latency. |
| H3 | D versus C | Dynamic supervisor routing helps difficult or evidence-sparse tasks, but may not be preferable for simple tasks. |
| H4 | E versus best of A–D | Difficulty-conditioned compute moves the quality/cost or quality/latency frontier outward rather than merely spending more on every task. |

These are directional hypotheses, not guaranteed outcomes. B can lose to A,
and the supervisor or adaptive policy can remain non-default if its gains are
limited to a narrow slice.

## 3. Experimental arms

### Arm A — fixed control

Current graph shape:

```text
planner -> search -> reader -> synthesizer -> critic
   ^          ^             ^             |
   |----------|-------------|-------------|
       bounded re-entry to plan, search, or synthesis
```

Purpose: establish the repeated reference distribution and preserve the
production fallback.

### Arm B — fixed plus evidence

The fixed graph remains unchanged, but the reader emits typed evidence claims
and the synthesizer uses the evidence path.

Purpose: isolate the value and cost of evidence-grounded synthesis before an
active verifier changes the trajectory.

### Arm C — fixed plus verify-and-repair

The fixed evidence path runs an explicit verification stage after synthesis.
Failed or abstained checks may trigger one bounded, named repair action, then
the affected output is verified again.

Allowed initial repairs:

- retrieve evidence for a named missing rubric item;
- re-read named paper sections;
- replace or qualify an unsupported claim;
- remove an unsupported claim;
- rewrite the named section without regenerating unrelated sections.

Purpose: measure the value of verification that changes the result, without
introducing general supervisor routing.

**Implementation status:** not present. The current `enable_verifier` setting
adds a supervisor action and is a no-op in the fixed graph. Arm C therefore
requires a new fixed verify-and-repair policy and tests before execution.

### Arm D — supervisor plus evidence and verifier

Use the existing supervisor graph with the evidence store and verifier enabled.
The supervisor chooses among the existing strict actions and owns stopping
within the common budget.

Purpose: measure whether dynamic action selection adds value beyond the fixed
policy.

Query refinement and reader-recovery flags remain off in the first comparison
so they do not become hidden extra variables. They can be evaluated as later
factorial additions if D's error analysis justifies them.

### Arm E — supervisor plus adaptive compute

Use the supervisor, evidence, and verification substrate with an explicit
compute controller that selects a bounded tier from pre-action difficulty and
runtime uncertainty signals.

Initial tiers:

- `T0 direct`: one fixed evidence path plus deterministic checks;
- `T1 verify-repair`: one verification pass and at most one targeted repair;
- `T2 branch`: a bounded set of diverse search plans or candidate outlines,
  listwise selection, then verification;
- `T3 deliberate`: reserved for later long-horizon work and excluded from this
  first experiment unless separately approved.

Purpose: determine whether selective compute beats a static policy on the
quality/cost frontier.

**Implementation status:** not present. No current setting estimates difficulty,
chooses a compute tier, manages sibling candidates, or stops on marginal value.
Arm E requires those capabilities and no-cost qualification before execution.

## 4. Configuration matrix

The P0 contracts that make this matrix reproducible are defined in the
[`TaskSpec`](08-task-spec-rfc.md),
[`RunManifest`](09-run-manifest-rfc.md),
[`TrajectoryEvent`](10-trajectory-event-rfc.md), and
[`benchmark/data registry`](11-benchmark-data-registry-rfc.md) RFCs. The
experiment should not enter a funded stage until its dry-run resolution can
prove the intended arm, task revision, data revision, budget, and event schema
for every episode.

### Existing runtime settings

These are the settings the current code understands. Values marked `common`
are frozen identically across every arm.

| Setting | A | B | C | D | E | Reason |
|---|---:|---:|---:|---:|---:|---|
| `ENABLE_SUPERVISOR` | false | false | false | true | true | Defines fixed versus supervisor graph shape |
| `ENABLE_EVIDENCE_STORE` | false | true | true | true | true | Isolates the evidence path in B |
| `ENABLE_VERIFIER` | false | false | false* | true | true | Existing flag only has behavior under the supervisor |
| `ENABLE_QUERY_REFINER` | false | false | false | false | false | Held out of the first five-arm comparison |
| `ENABLE_READER_RECOVERY` | false | false | false | false | false | Held out of the first five-arm comparison |
| `ENABLE_PROMPT_ISOLATION` | true | true | true | true | true | Common safety floor; required for untrusted paper-derived control signals |
| `ENABLE_SEMANTIC_SCHOLAR` | false | false | false | false | false | Prevents source expansion from confounding policy effects |
| `ENABLE_PROMPT_CACHING` | false | false | false | false | false | Prevents run order/cache state from changing effective cost |
| `USE_MOCK_DATA` | false | false | false | false | false | Funded quality evaluation must use the live model and real benchmark inputs |
| `ENABLE_HITL` | false | false | false | false | false | Human plan edits would make arms incomparable; eval runner compiles without the pause |

`*` Arm C invokes a new fixed-policy verifier stage, not the existing
`ENABLE_VERIFIER` supervisor action. That distinction must be structural and
tested; setting `ENABLE_VERIFIER=true` with `ENABLE_SUPERVISOR=false` does not
create Arm C.

### Proposed policy selectors

Final names require an implementation ADR. The experiment uses these conceptual
selectors so the intended behavior is unambiguous:

| Arm | Conceptual policy | Required new implementation |
|---|---|---|
| A | `fixed` | None |
| B | `fixed_evidence` | None beyond configuration and manifest capture |
| C | `fixed_verify_repair` | Fixed verifier node, typed repair decision, one-repair cap, re-verification |
| D | `supervisor_verified` | None beyond configuration and manifest capture |
| E | `adaptive_verified` | Difficulty features, T0–T2 controller, candidate lineage, listwise selection, marginal stop record |

Do not add these as ad hoc Boolean combinations. Prefer one versioned research
policy selector plus a policy-specific typed configuration; invalid combinations
should fail at settings load.

### Common frozen settings

The final manifest must record the exact values. The starting proposal is:

| Setting | Proposed value |
|---|---|
| `ANTHROPIC_MODEL` | One exact, then-current model id for every arm; resolve immediately before the run |
| Per-agent model overrides | Empty or the same explicit mapping across every arm |
| LLM temperature | Current shared implementation value, `0.3`, frozen across arms |
| `MAX_PAPERS` | `10` |
| `RESULTS_PER_QUERY` | `5` |
| `READER_MAX_WORKERS` | `5` |
| `READER_MAX_CHUNKS_PER_PAPER` | `5` |
| `READER_MAX_CLAIMS_PER_PAPER` | `5` where evidence is enabled |
| `MAX_ITERATIONS` | `3` |
| `MAX_LOOP_ITERATIONS` | `20` for supervisor arms; recorded but unused by fixed arms |
| `MIN_QUALITY_SCORE` | `0.75` |
| `ANTHROPIC_MAX_RETRIES` | `4` |
| `ANTHROPIC_TIMEOUT_SEC` | `120` |
| `MAX_COST_USD` | One common per-episode cap, no higher than the current `$2.00` default; exact value requires approval |
| Campaign cap | Required through `--max-budget-usd`; calculated after a no-cost/pilot estimate and approved separately |

The common prompt-isolation setting means A is the fixed graph under the
experiment's shared safety floor, not a byte-for-byte replay of every default
environment value. Since no funded baseline exists yet, A becomes the declared
baseline for this experiment.

## 5. Tasks and repeats

### Available first benchmark

Use the repository's existing 20-query research benchmark as
`research-policy-v1`. It spans multiple ML/AI research domains and already feeds
the current metrics. Because its contents are checked into the repository, it
is a development/comparative benchmark—not a sealed generalization test.

Before promotion, add a limited-access validation set and a sealed canary set
under the dataset-registry work in P0.

### Repetition rule

Run at least three independent repeats per query and arm. The research runner
does not currently expose `--repeats`, so orchestration must create distinct
run manifests/output directories rather than overwrite or treat `--resume` as
a repeat.

With all five arms, the full v1 matrix is:

```text
20 queries x 3 repeats x 5 arms = 300 research episodes
```

This is a maximum design matrix, not an approved bill. Use the staged plan
below to avoid funding a clearly broken arm at full scale.

## 6. Staged execution plan

### Stage 0 — no-cost qualification

- implement the missing C and E policies behind typed selectors;
- add config-validity and policy-shape tests for every arm;
- prove every arm's run manifest records the intended graph and flags;
- run deterministic, mocked, adversarial, timeout, cancellation, and budget
  tests;
- validate trajectory and score schemas;
- prove the arm cannot read its labels or change evaluators;
- generate a dry-run matrix that makes zero provider calls.

Exit: all five arm identities are mechanically distinguishable and every
non-paid gate is green.

### Stage 1 — paid calibration smoke test

After a separate approval, run one repeat on a small, predeclared development
slice chosen to cover easy, hard, retrieval-heavy, and synthesis-heavy tasks.
The slice and maximum campaign cost must be written before execution.

Exit: every arm completes, artifacts are valid, observed per-episode costs are
available, and no arm violates a safety or budget gate. This stage sizes—not
proves—the full campaign.

### Stage 2 — screening experiment

Run five representative development queries, two repeats, all five arms:

```text
5 queries x 2 repeats x 5 arms = 50 research episodes
```

Archive an arm before Stage 3 if it is structurally failing, dominated on every
target metric, or materially breaches a non-regression gate. Do not eliminate
an arm only because a noisy mean is lower.

### Stage 3 — full comparative campaign

Run A plus every surviving candidate over all 20 queries with three repeats.
Interleave arm order within each query/repeat block so model-service or source
drift does not align with one arm. Record start time and retrieval provenance.

### Stage 4 — live-retrieval robustness follow-up

The core comparison should use the most controlled source snapshot practical.
A later, separately reported sweep uses live retrieval to measure freshness,
tool failures, and source drift. Do not mix controlled and live-source episodes
inside one aggregate.

### Stage 5 — human adjudication and promotion decision

Blind a predeclared sample of reports and disputed claims for human review.
Compare human preferences and labels with the automated judges. Publish the
decision even if no candidate is promoted.

Each paid stage requires its own go/no-go confirmation if it exceeds the
previously approved total cap.

## 7. Scorecard

### Primary outcomes

Use two primary measures rather than blending them:

1. **Task-rubric success:** proportion of predeclared task-specific rubric
   items satisfied with admissible evidence.
2. **Supported-claim precision:** supported factual claims divided by all
   checked factual claims; abstained/unverifiable claims stay visible and do
   not become passes.

A candidate is eligible if it improves at least one primary outcome and is
non-inferior on the other. The non-inferiority margin must be set from the
repeated baseline and human calibration before candidate results are unblinded.

### Secondary diagnostic outcomes

- evidence recall/completeness;
- citation validity and citation correctness;
- contradiction detection and appropriate uncertainty;
- selector accuracy and oracle gap for E;
- verifier abstention, false-pass, and false-fail rates;
- successful repair rate and repair-induced regression rate;
- retrieval yield and redundant/repeated action rate;
- critic score for compatibility with the current harness.

### Non-regression gates

- prompt-injection and source-isolation safety;
- citation validity;
- job completion rate;
- no privacy, principal-scoping, or policy failure;
- per-episode and campaign budget adherence;
- no increase in missing/null metric denominators hidden by aggregation.

### Frontier dimensions

Report separately:

- human pairwise preference and edit burden;
- workflow cost and judge cost;
- LLM calls and retries;
- p50/p95 latency and timeout rate;
- tool calls, unique sources, and evidence yield;
- compute tier chosen and marginal gain for E.

## 8. Analysis plan

### Ordered contrasts

Analyze the approved questions in order:

1. B − A;
2. C − B, with C − A also reported;
3. D − C;
4. E − the best eligible non-adaptive arm.

This preserves causal interpretability better than declaring the highest of
five noisy means the winner. All arm-to-arm tables may be published, but only
the predeclared contrasts decide the experiment.

### Statistical reporting

- show every query/repeat result and denominator;
- use paired bootstrap intervals over queries, with repeats nested inside query;
- report binary-rate intervals for completion and safety failures;
- show distributions and task-slice deltas, not only means;
- keep failed, timed-out, budget-stopped, and judge-null episodes in the report;
- determine practical/non-inferiority margins before unblinding candidate
  results;
- treat the checked-in 20-query result as evidence for this benchmark, not a
  universal claim about research agents.

### Task slices

At minimum report:

- retrieval-heavy versus synthesis-heavy;
- straightforward versus ambiguous/comparative;
- evidence-rich versus evidence-sparse;
- tasks with and without contradictory findings;
- low versus high observed baseline difficulty.

Slice definitions must be assigned without looking at candidate outcomes.

## 9. Stop conditions

Stop or pause the campaign if:

- the campaign or episode cost ceiling is reached;
- an arm's manifest does not match its declared configuration;
- source/provider drift makes paired comparison invalid;
- an arm exposes benchmark labels, bypasses safety checks, or modifies grading;
- a systemic judge failure removes a predeclared fraction of primary scores;
- repeated infrastructure failures make one arm's ordering unfair;
- a serious privacy or security issue appears.

Stopping is an experiment outcome. Preserve completed episodes and publish the
reason; do not silently restart only the failed arm until it obtains a better
sample.

## 10. Required artifacts

```text
outputs/eval/research-policy-v1/<campaign-id>/
  manifest.json
  protocol.md
  arm-configs/{A,B,C,D,E}.json
  task-set.json
  episodes/<query-id>/<repeat>/<arm>/
    run-manifest.json
    trajectory.jsonl
    artifacts/
    verification.jsonl
    scores.json
  human-labels/
  aggregate.json
  scorecard.md
  error-analysis.md
  decision.md
```

The public report must include negative results, excluded data with reasons,
judge disagreement, actual cost, actual latency, and the exact policy versions.

## 11. Promotion rule

Experiment approval is not default-policy approval.

- A remains the fallback throughout.
- B may ship as evidence infrastructure even if its report-quality delta is
  neutral, provided cost and safety are acceptable.
- C, D, or E may be promoted only for the task slices where it passes the
  scorecard and later shadow/canary gates.
- A more expensive arm should become a named compute tier rather than the
  universal default when its gains are concentrated on difficult tasks.
- If no arm wins, retain A and use the error analysis to choose the next
  experiment.

## 12. Approval ledger

| Item | Status |
|---|---|
| D1 optimization target | Approved 2026-09-04 |
| D2 scorecard structure | Approved 2026-09-04 |
| D3 fixed control/fallback | Approved 2026-09-04 |
| Five-arm protocol design | Approved 2026-09-04 |
| Arm C implementation | Not authorized |
| Arm E implementation | Not authorized |
| Paid calibration smoke test | Not authorized; cost approval required |
| Screening/full campaign | Not authorized; cost approval required |
| Policy promotion | Not authorized; requires results and a later decision |
