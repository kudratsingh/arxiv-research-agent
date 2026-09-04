# Evaluation and benchmark strategy

Status: **PROPOSED — FOR DISCUSSION**

The evaluation system is the prerequisite for every advanced capability in
this program. Without it, test-time compute rewards verbosity, self-improvement
optimizes its own judge, feedback becomes an anecdote, and RL scales an
undefined objective.

## 1. Evaluation model

Use a five-axis scorecard. No single aggregate score should hide a regression.

| Axis | Core question | Example measures |
|---|---|---|
| Outcome quality | Is the result useful and correct? | task success, claim precision/recall, citation accuracy, coverage, human preference |
| Agent process | Did the policy make good decisions? | plan quality, tool success, evidence yield, recovery rate, redundant actions, stop quality |
| Systems | Is it production-worthy? | completion rate, p50/p95/p99 latency, cost, tokens, queue time, timeout/cancel recovery |
| Safety and integrity | Did it respect boundaries? | injection resistance, source laundering, data isolation, denied-action rate, privacy and consent checks |
| Product outcome | Did it help the user over time? | report acceptance/edit burden, task continuation, learning-session completion, return/use outcomes |

Report a Pareto surface across quality, cost, latency, and risk. A quality gain
that doubles cost may be valuable for a deliberate tier and unacceptable as
the default.

## 2. Evaluation units

### Research episode

One `TaskSpec`, its full trajectory, all intermediate artifacts, the final
report, verification results, and any adjudicated feedback.

### Guided-learning episode

One learner persona/profile snapshot, paper/session spec, turn trajectory,
assessment evidence, progress events, and user outcome. Research quality and
pedagogy quality remain separate metric lanes.

### Long-horizon project

A goal tree containing subtasks, dependencies, checkpoints, artifact versions,
human interventions, final deliverables, and a human-time estimate. This is a
future lane rather than a larger value of the current research query.

## 3. Benchmark portfolio

Build a portfolio rather than one leaderboard.

### A. Deterministic component sets

Run on every merge and make them free of live model calls:

- query normalization, deduplication, and source/date filters;
- paper identity and citation resolution;
- PDF parsing, section detection, chunk ranking, and evidence-span linkage;
- calculator/code/tool contracts;
- task, trajectory, artifact, feedback, and verification schemas;
- prompt-injection, SSRF, tenant-isolation, and data-retention fixtures;
- stopping, budget, timeout, cancel, resume, and idempotency policies.

### B. Recorded trajectory replay

Extend the repository's fixture discipline into an agent replay lane:

- observations and tool results are recorded with provenance and hashes;
- policy decisions can be re-run without network or provider spend;
- changed policies are compared on the same observations;
- recordings detect schema and prompt drift;
- replay results are clearly labeled as counterfactual when a changed action
  would have produced a different real-world observation.

Replay is excellent for routing and parsing regression. It cannot prove live
retrieval freshness or a new tool policy's downstream behavior.

### C. Frozen internal research sets

Evolve the current 20-query set into versioned, stratified suites:

| Slice | What it tests | Ground truth strategy |
|---|---|---|
| Retrieval | Find known papers/evidence under controlled cutoffs | paper ids, source spans, temporal snapshot |
| Synthesis | Build a supported answer from a supplied corpus | claim/evidence rubric and expert answer outline |
| Contradiction | Preserve and explain conflicting findings | labeled source pairs and acceptable uncertainty |
| Freshness | Separate knowledge available before/after a date | time-stamped corpus and publication cutoffs |
| Deep survey | Multi-hop literature review across subfields | expert rubric, required/optional evidence, citation audit |
| Adversarial | Injection, citation laundering, poisoned metadata | deterministic expected safety behavior |
| Follow-up | Use prior work without copying stale conclusions | linked multi-turn tasks and updated evidence |

Keep three splits:

- `development`: visible tasks for iteration;
- `validation`: limited-access tasks for promotion decisions;
- `canary`: sealed tasks used rarely to detect overfitting and contamination.

### D. Guided-learning sets

Retain the current scenarios and add longitudinal tasks only when real pilot
outcomes exist. Measure plan fit, evidence-grounded feedback, learner effort,
misconception handling, honest abstention, continuity, and downstream recall.
Do not collapse these into a mastery score.

### E. External capability probes

External benchmarks are useful for transfer and comparability, not as the
product objective:

- [BrowseComp](https://openai.com/index/browsecomp/) for persistent,
  hard-to-find browsing with easily checked short answers;
- [DeepResearch Bench](https://arxiv.org/abs/2506.11763) and
  [DeepResearch Bench II](https://arxiv.org/abs/2601.08536) for long-form
  research, citation quality, and rubric diagnosis;
- [GAIA](https://arxiv.org/abs/2311.12983) for general reasoning and tool use;
- [PaperBench](https://arxiv.org/abs/2504.01848) for much later, long-horizon
  research replication and hierarchical rubric evaluation;
- [MLE-bench](https://arxiv.org/abs/2410.07095) for a future ML-engineering
  agent with code and compute tools;
- a human-time-bucketed internal suite inspired by
  [METR's task-completion time-horizon methodology](https://metr.org/time-horizons/).

Adopting a benchmark means documenting its license, contamination risk, task
fit, environment cost, reproducibility, and which capability it does *not*
measure.

## 4. Outcome metrics for research

Retain the current metrics, then make them more diagnostic.

### Evidence and factuality

- citation validity: cited identifier/source resolves;
- citation correctness: cited source supports the associated claim;
- citation completeness: externally verifiable claims have evidence;
- claim precision: supported claims / checked factual claims;
- evidence recall: required rubric claims with supporting evidence;
- quote fidelity and numeric consistency;
- contradiction recall and calibrated uncertainty;
- source quality, diversity, independence, and freshness.

### Task fulfillment

- rubric item coverage with per-item evidence;
- required deliverable/schema completion;
- answer relevance and decision usefulness;
- explicit resolution of ambiguities and constraints;
- expert pairwise preference and edit distance to accepted output.

### Calibration

Require claim-level confidence or an uncertainty category only where it can be
calibrated. Measure Brier score or expected calibration error against
adjudicated claims. “Confident writing” is not confidence data.

## 5. Process and trajectory metrics

| Category | Measures |
|---|---|
| Planning | valid plan rate, dependency correctness, rubric coverage before execution, re-plan frequency |
| Retrieval | query diversity, unique relevant sources per call, evidence yield, dead-end rate, cache hit rate |
| Tool use | valid call rate, timeout/error rate, retries, result utilization, denied unsafe calls |
| Reasoning policy | successful recovery, repeated-state rate, oscillation, premature stop, budget exhaustion |
| Verification | pass/fail/abstain rate, repair success, false-pass/false-fail against human labels, judge disagreement |
| Memory | useful retrieval rate, stale-memory use, compression loss, cross-principal leakage (must be zero) |
| Human interaction | intervention rate, clarification usefulness, approval reversals, time-to-decision |

Every metric needs an explicit direction and denominator. For example, a low
tool-call count is not inherently good if evidence recall collapses.

## 6. Test-time compute evaluation

For each compute strategy, estimate:

- pass@1 and pass@k;
- selection accuracy: how often the selector chooses the best candidate;
- oracle gap: best available candidate quality minus selected quality;
- marginal gain from candidate or verifier number `k`;
- quality per dollar, per token, per tool call, and per wall-clock minute;
- tail latency and budget-overrun rate;
- task-conditional gains by difficulty slice;
- correlation between routing uncertainty and actual failure.

Use matched compute budgets when comparing generation and verification. A
four-candidate strategy should not be called better without stating that it
used roughly four trajectories of work.

## 7. Judge validation

LLM judges are instruments, not labels.

1. Create an expert-labeled calibration set with clear disagreement policy.
2. Blind judge inputs to candidate identity and experiment arm.
3. Randomize pairwise ordering and test position bias.
4. Measure agreement, false-pass, false-fail, and abstention by task slice.
5. Include adversarial cases: plausible unsupported prose, citation swaps,
   verbosity, stylistic polish, and injected instructions in source text.
6. Keep the generator and judge policy versions independently recorded.
7. Recalibrate when the judge, prompt, rubric, or source representation changes.
8. Route low-confidence or high-disagreement cases to human adjudication.

Where possible, use deterministic graders or executable checks before an LLM
judge. For open-ended reports, prefer rubric-level and claim-level judgments to
one holistic score.

## 8. Experimental design

### Comparisons

- use paired tasks and identical source snapshots when possible;
- run enough repeats to estimate stochastic variance before setting a gate;
- report the distribution and task-level deltas, not only the mean;
- predeclare the primary metric and non-inferiority safety/cost constraints;
- separate exploratory tuning from confirmatory evaluation;
- record every failed, timed-out, and null-scored run in the denominator;
- do not tune on the sealed promotion set.

### Statistics

The exact method depends on the metric, but the default should be paired
bootstrap confidence intervals over tasks, with hierarchical resampling when
there are repeated trials per task. Binary success rates should include
uncertainty intervals. Multiple slices are diagnostic unless a correction and
gate were declared in advance.

The current flat regression thresholds can remain as a compatibility gate, but
they should be replaced or justified after a repeated live baseline estimates
real variance.

### Error analysis

Every campaign should classify failures into a stable taxonomy:

```text
task understanding
planning/decomposition
retrieval miss
source-quality/freshness miss
parsing/chunking/ranking
evidence-to-claim reasoning
synthesis/organization
citation/provenance
verification false pass/false fail
tool/runtime failure
budget/timeout/premature stop
safety/policy refusal
human-interface failure
```

An architecture change should target a measured error class, not a generic
desire for “more reasoning.”

## 9. Promotion ladder

| Gate | Evidence | Cost boundary | Result |
|---|---|---|---|
| G0: contract | Schema, unit, security, property, and mutation tests | No paid calls | Proposal may become a flag-gated prototype |
| G1: replay | Recorded/canned trajectory regression and adversarial cases | No paid calls | Prototype is behaviorally coherent offline |
| G2: funded benchmark | Repeated paired internal evaluation with run manifests | Explicit model-spend approval | Candidate is measurably better or archived |
| G3: human calibration | Blind expert labels/preferences and judge analysis | Explicit labeling budget/time | Outcome metrics are credible |
| G4: shadow/canary | Real traffic with no autonomous external side effects | Deployment and inference approval | Operational and product SLOs hold |
| G5: default | ADR, rollback, data/consent review, final scorecard | Approved ongoing budget | Policy becomes default for named task tiers |

Training work adds two gates before G4: training-data approval and held-out
model-safety evaluation.

## 10. Required campaign artifacts

```text
campaign/
  manifest.json
  task-set.json
  arm-configs/
  episodes/<task>/<repeat>/<arm>/
    trajectory.jsonl
    artifacts/
    verification.jsonl
    scores.json
  human-labels/
  aggregate.json
  report.md
  error-analysis.md
  decision.md
```

The manifest must identify code, prompts, models, tool and source snapshots,
sampling settings, budgets, judge versions, and data split. The decision must
name wins, regressions, uncertainty, costs, and whether the candidate was
promoted, revised, or archived.

## 11. First evaluation milestone

Before building a new agent policy:

1. ratify the product task taxonomy and primary metrics;
2. normalize a trajectory schema around the current research graph;
3. create a small human-labeled claim/citation calibration set;
4. run the existing funded baseline with at least enough repeats to estimate
   task-level variance, after explicit cost approval;
5. publish the first error taxonomy and quality/cost/latency frontier;
6. choose the first architecture experiment from the largest addressable error
   class.

That milestone turns the existing sophisticated harness into an improvement
engine.

The first planned comparison is now specified in
[`07-first-policy-experiment.md`](07-first-policy-experiment.md). Its design is
approved; its implementation, paid calibration, and funded execution remain
separate gates.
