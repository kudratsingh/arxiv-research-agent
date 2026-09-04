# Research frontier and product translation

Status: **RESEARCH REVIEW — NOT AN ADOPTION RECORD**

As of: **2026-09-04**

This page separates published research directions from proposals for this
repository. Paper results are evidence about their reported settings, not proof
that the same method will improve this product.

## 1. Test-time compute for agents

### Published direction

[Scaling Test-time Compute for LLM Agents](https://arxiv.org/abs/2506.12928)
studies parallel sampling, sequential revision, verification/merging, and
rollout diversity. Its reported findings support three useful hypotheses:
test-time scaling can improve agents, the timing of reflection matters, and
diverse candidates plus listwise selection can outperform naive repetition.

[When To Solve, When To Verify](https://arxiv.org/abs/2504.01005) shows why
“more verification” is not automatically compute-optimal: under fixed budgets,
solution generation and generative verification have different scaling
behavior. [Multi-Agent Verification](https://arxiv.org/abs/2502.20379) provides
evidence for another axis—multiple aspect verifiers—but also makes it a design
choice to evaluate rather than an assumption.

### Product translation

The repository already has sequential revision and a supervisor, but not
parallel candidate trajectories or adaptive allocation. The useful next step is
not a larger loop limit. It is a matched-budget experiment over:

- diverse search plans;
- candidate outlines or section drafts;
- listwise selection;
- aspect-specific verification;
- task-conditional stopping based on evidence gaps and uncertainty.

The product question is the frontier curve: which strategy gives the largest
quality gain per dollar and per minute for each task class?

## 2. Robust verification

### Published direction

Verification research increasingly treats generation, verification, and
selection as separate policies. The multi-verifier work above suggests that
weak, specialized perspectives can be composed. Deep-research benchmarks also
show why report evaluation must inspect both the output and its citations.

The important counterweight is evaluator dependence: multiple prompts to the
same model are not necessarily independent, scalar judges can reward polish,
and a verifier can confidently repeat the generator's error.

### Product translation

Build a cascade:

1. deterministic checks;
2. source-span and calculation checks;
3. calibrated aspect judges with abstention;
4. human adjudication for disputed/high-value cases.

Measure false passes and false failures against labeled claims. Use verifier
output to name a recovery action, not merely request another reflection.

## 3. Deep research agents

### Published direction

[BrowseComp](https://openai.com/index/browsecomp/) focuses on persistent,
hard-to-find browsing questions whose short answers are relatively easy to
verify. OpenAI's reported best-of-N analysis is another example of test-time
compute helping when verification is easier than discovery.

[DeepResearch Bench](https://arxiv.org/abs/2506.11763) evaluates PhD-level,
long-form research tasks with adaptive report criteria and citation metrics.
[DeepResearch Bench II](https://arxiv.org/abs/2601.08536) continues toward more
diagnostic rubric-based evaluation. These complement rather than replace a
product-specific scholarly benchmark.

### Product translation

A true deep-research mode would add:

- persistent multi-hop search over heterogeneous primary sources;
- a hierarchical research plan and artifact ledger;
- source quality, freshness, and contradiction reasoning;
- analysis through a sandboxed code/data tool;
- claim-level provenance and staged verification;
- context compaction and durable resume;
- explicit user checkpoints for scope, cost, and ambiguous conclusions.

The current arXiv/Semantic Scholar/PDF toolchain is a strong scholarly core,
but it should not be labeled general deep research yet.

## 4. Long-horizon agents

### Published direction

[METR's task-completion time-horizon work](https://metr.org/time-horizons/)
frames capability as the human task duration at which an agent reaches a target
success probability. The updated methodology emphasizes reliability across a
task distribution rather than the longest anecdotal success.

[PaperBench](https://arxiv.org/abs/2504.01848) decomposes research replication
into thousands of rubric items across full projects, illustrating the need for
hierarchical grading, executable artifacts, and long-lived workspaces.

### Product translation

Add an internal benchmark stratified by human-estimated duration and dependent
stage count. The system needs a goal tree, checkpointed artifacts, idempotent
tools, context-loss checks, and explicit blocked/waiting states before raising
timeouts or iteration counts.

Measure success at both 50% and a higher reliability target. Product trust is
closer to repeatable completion than to pass@many where one of many attempts
succeeds.

## 5. Tool use and code execution

### Research direction

Tool-enabled agents gain reliability when tools provide externally checkable
state: search results, database rows, tests, calculations, or files. But tools
also create prompt-injection, credential, supply-chain, network, and destructive
action surfaces. Flexible code tools increase capability and the size of the
sandbox problem together.

### Product translation

Prioritize tools with strong relevance and verifiability:

1. scholarly and web source retrieval with provenance;
2. DOI/arXiv/version/retraction metadata;
3. deterministic calculator and table operations;
4. sandboxed Python for data extraction, statistics, and plots;
5. repository/code tools only for a separately named ML-engineering agent.

Each tool needs typed inputs/outputs, permissions, time and size limits,
idempotency or side-effect classification, observation hashes, and adversarial
tests. A general shell should not be smuggled in as a convenience method.

## 6. Learning from feedback

### Research direction

Agents can use feedback at several levels:

- within-run reflection or repair;
- episodic memory retrieved on similar tasks;
- prompt and policy optimization;
- supervised or preference training;
- reinforcement learning over trajectories.

The difficulty increases from right-to-left credit ambiguity: a report-level
rating says little about which of twenty search, reading, and writing decisions
caused it.

### Product translation

Capture feedback against concrete artifacts and decisions: a claim, citation,
section, plan, candidate choice, tool result, or learner interaction. Preserve
consent scope. Curate offline, compare on held-out tasks, and promote through a
registry. Do not perform online gradient updates or silently turn conversations
into training data.

## 7. Agent reinforcement learning

### Published direction

[DeepSeek-R1](https://arxiv.org/abs/2501.12948) is prominent evidence that
large-scale RL can elicit reasoning behavior, while also reporting that pure RL
can create readability and language-consistency problems that require a
multi-stage recipe.

[Agent Lightning](https://arxiv.org/abs/2508.03680) proposes separating agent
execution from training and assigning credit over agent trajectories, including
tool-using and multi-agent systems. [The Art of Scaling Reinforcement Learning
Compute for LLMs](https://arxiv.org/abs/2510.13786) argues that RL recipes differ
in both compute efficiency and asymptotic behavior, and that small runs can be
used to reason about scaling only under a stable protocol.

### Product translation

RL is a late-stage option, not the next sprint. The project first needs:

- a stable environment and action schema;
- trajectory capture and replay;
- rewards that cannot be cheaply hacked;
- credit assignment below the final report;
- a model whose weights and serving stack we control;
- training and held-out datasets with consent and provenance;
- compute, checkpoint, and experiment tracking;
- SFT, preference, and inference-time-search baselines.

The first RL target should be narrow and verifiable—query planning, source
selection, or compute-tier routing—not unconstrained report generation.

## 8. Train-time scaling

### Current opportunity

Most value available to this repository is post-training, not foundation-model
pretraining. Scale in this order:

- data quality and diversity;
- task curriculum;
- supervised distillation;
- preference data;
- rollout quantity;
- training duration and model size;
- verifier/value-model capacity.

Treat total system cost as training amortization plus serving. A small policy
model that saves repeated frontier-model calls may be more valuable than a
slightly better full report generator.

### Research questions

- When does a learned router dominate a deterministic compute policy?
- Does training a query planner transfer across research domains?
- Can a small verifier preserve recall while reducing expensive judge calls?
- Does distilling successful tool trajectories improve new-task planning or
  only imitate benchmark templates?
- Where is inference-time branching cheaper than another training cycle?

## 9. Self-improving systems

### Published direction

[Self-Adapting Language Models (SEAL)](https://arxiv.org/abs/2506.10943)
studies models that generate their own adaptation data and update directives.
[Darwin Gödel Machine](https://arxiv.org/abs/2505.22954) explores agents that
modify agent code, retain a diverse archive, and empirically evaluate
descendants in sandboxed coding tasks. Both point to interesting research
directions; neither justifies live, unsupervised self-modification here.

### Product translation

Create an offline improvement lab only after the benchmark and policy registry
are mature. Let candidates propose changes and gather evidence, but keep these
outside their control:

- sealed tasks and labels;
- security tests;
- cost and resource ceilings;
- dataset eligibility and consent;
- promotion rules;
- production credentials and deployment.

Maintain candidate lineage and negative results. A diverse archive can be more
informative than repeatedly editing one incumbent, but every surviving
candidate still needs an external gate.

## 10. Planning and multi-step reasoning

### Current opportunity

The current planner and supervisor already provide a basis for experiments.
Improvements should target measured planning failures:

- missing or redundant sub-questions;
- incorrect dependencies;
- plans that cannot be verified;
- search queries that do not discriminate between hypotheses;
- no explicit stopping condition;
- re-plans that forget completed work;
- mismatch between plan effort and available budget.

### Proposed progression

1. compile requests into a typed `TaskSpec` and rubric;
2. add dependency-aware plans and acceptance checks;
3. evaluate plan execution, not plan prose;
4. preserve completed work during re-planning;
5. branch plans only on uncertain high-value decisions;
6. learn planning or routing from trajectories after reward calibration.

## 11. Research bets for this repository

| Bet | Expected leverage | Evidence burden | Recommended timing |
|---|---|---|---|
| Claim-level verifier with abstention and targeted repair | High reliability gain from existing components | Human claim labels and paired live runs | First |
| Difficulty-conditioned T0/T1 compute | Cost and latency efficiency | Repeated baseline plus uncertainty features | First/second |
| Diverse search branches + listwise merge | Better coverage on hard surveys | Matched-budget branch ablation | Second |
| Heterogeneous web research tools | Major capability expansion | Source/safety benchmark and provenance | After core verification |
| Sandboxed Python analysis | Better quantitative research | Sandbox and reproducibility suite | After tool boundary |
| Learned compute router | Efficiency at scale | Sufficient trajectories and drift tests | After deterministic router |
| Small query-planning or verifier model | Lower recurring cost, controllable training | Approved dataset and serving decision | After feedback loop |
| Agent RL | Possible planning/tool gains | Stable rewards, GPU budget, held-out eval | Late research |
| Self-generated code/prompt variants | Faster experimentation | Immutable external evaluation and sandbox | Last |

## 12. What remains uncertain

- How much of the current quality ceiling is retrieval versus synthesis versus
  evaluation error is not yet measured.
- The supervisor path's advantage over the fixed pipeline has not been
  established by a current repeated live campaign.
- The best judge topology for scholarly claims is unknown until human
  calibration exists.
- User demand for deep-research latency and cost tiers is not yet observed.
- There is no basis yet for choosing a model size, training method, or GPU
  budget.
- Long-horizon reliability may be dominated by product/task design rather than
  a more capable planner.

These are experiment inputs, not reasons to select fashionable infrastructure
in advance.
