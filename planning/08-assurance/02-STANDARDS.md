# Standards adopted, and what they actually require

Status: **PROPOSED**

Phase A is deliberately unoriginal. Every convention below already exists,
already has a specification, and already has tooling that reads it. Inventing
a private convention would cost the same effort and buy none of the
interoperability — which matters here specifically because the owner's reason
for this phase is *"we can build on top of this and add mcp and other agent
tools and infra."* Infrastructure reads standard names.

Each section states what the standard requires, what Phase A adopts, and what
Phase A skips and why. The final section is the honest list of what a
repository this size should **not** adopt.

> **Verification status.** The GenAI semantic conventions are experimental and
> have churned more than once. Attribute names in §1 are pinned in the ADR
> that WO-A07 writes, against the specification version current at
> implementation time — not against this page. Where this page and the spec
> disagree, the spec wins and WO-A07 must say so in its PR.

## 1. OpenTelemetry GenAI semantic conventions

### What it requires

The GenAI conventions live in the OpenTelemetry semantic-conventions
repository (`docs/gen-ai/`) and are **experimental** — stable enough to adopt,
not stable enough to assume. They define:

- **Span naming**: `{gen_ai.operation.name} {model}`, e.g. `chat claude-…`.
  Operation names include `chat`, `text_completion`, `embeddings`,
  `create_agent`, `invoke_agent`, `execute_tool`.
- **Request attributes**: `gen_ai.operation.name`, `gen_ai.request.model`,
  and the sampling parameters (`gen_ai.request.max_tokens`,
  `.temperature`, `.top_p`).
- **Provider identity**: historically `gen_ai.system`; more recent revisions
  introduce `gen_ai.provider.name`. **This is the single most likely
  divergence** between this page and the current spec — WO-A07 checks it.
- **Response attributes**: `gen_ai.response.model`, `gen_ai.response.id`,
  `gen_ai.response.finish_reasons`.
- **Usage attributes**: `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`.
- **Agent and tool attributes**: `gen_ai.agent.name`, `gen_ai.tool.name`,
  `gen_ai.tool.call.id`, `gen_ai.conversation.id`.
- **Metrics**: `gen_ai.client.token.usage` (histogram, unit `{token}`) and
  `gen_ai.client.operation.duration` (histogram, unit `s`).
- **Errors**: the general `error.type` attribute, not a GenAI-specific one.
- **Content capture is opt-in.** Prompt and completion text is captured only
  when explicitly enabled (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`
  is the environment flag the convention uses), because prompts routinely
  contain user data. The representation of captured content has itself churned
  — treat it as unstable.

The HTTP conventions, by contrast, are **stable**: `http.request.method`,
`http.route`, `http.response.status_code`, and the
`http.server.request.duration` histogram in seconds. Use `http.route` (the
template), never the raw path — that is the cardinality rule written into the
specification rather than invented by us.

### What Phase A adopts

All of the above, in WO-A07 and WO-A10, with the repository's current names
(`llm_calls_total`, `llm.cost_usd`, …) retained as aliases for one release so
nothing that reads them breaks silently.

### What Phase A skips

Content capture stays **off**. This repository's telemetry would otherwise
carry paper text, learner text, and research queries. The flag exists, defaults
to off, and A03's log redaction assumes it is off.

Cost is **not** in the conventions — there is no `gen_ai.usage.cost`. The
repository's existing `llm_cost_usd_total` is retained as a first-class local
instrument, and that decision is recorded rather than papered over.

## 2. Evaluation practice

### The taxonomy worth having

Four layers, answering different questions, and a system that conflates them
cannot diagnose anything:

1. **Component evaluation** — deterministic checks on parsers, rankers,
   schema validators. Cheap, exact, and the layer this repository is
   strongest at.
2. **Trajectory evaluation** — did the agent take a sensible path? Measured as
   tool-call precision/recall, in-order or any-order match against a reference
   trajectory, redundant-action rate, recovery rate. This repository asserts
   trajectories only in WO-A15's e2e tier; richer trajectory scoring belongs
   to the agent-engineering program.
3. **End-to-end task success** — did the deliverable meet the rubric?
4. **LLM-as-judge, with meta-evaluation** — a judge is an instrument with its
   own error rate. Agreement with human labels is reported with a
   chance-corrected statistic (Cohen's κ for two raters, Krippendorff's α for
   more), plus false-pass and false-fail rates by slice.

### Judge reliability, concretely

The practices that matter, in rough order of value per unit of effort:

- **Pin the judge model.** A judge that follows the product model is not an
  instrument. This is the single highest-value fix available to this
  repository at zero cost.
- **Version the rubric** and record the version with every score.
- **Control position and verbosity bias** — randomize pairwise order, run a
  reversed replicate, and check whether score correlates with length.
- **Prefer deterministic graders** where a deterministic grader exists. An
  executable check beats a judge on cost, variance, and defensibility.
- **Meta-evaluate against human labels** before trusting a judge as ground
  truth. This costs money and human time, and Phase A explicitly defers it.

### Statistical rigour for gates

- Report **intervals, not point deltas**. Paired bootstrap over tasks is the
  workhorse; Wilson intervals for binary rates; McNemar for paired binary
  outcomes.
- **Repeats estimate variance.** A gate whose threshold was never compared to
  measured run-to-run variance is a guess — which `docs/decisions/0044`
  already concedes in writing.
- **Aggregate repeats by task before comparing.** Comparing repeat 1 to repeat
  1 discards the variance the repeats were run to measure.
- **Predeclare the primary metric** and treat slices as diagnostic unless a
  correction was declared in advance; otherwise 20 independent per-query tests
  produce false alarms by arithmetic.

### Frameworks, honestly

| Tool | Genuinely good at | Why not here |
|---|---|---|
| Inspect AI (UK AISI) | rigorous eval specs, solvers/scorers, sandboxing | strong candidate later; a full framework adoption is a bigger diff than this phase |
| promptfoo | fast prompt/red-team matrices, CI-friendly | overlaps the safety corpus we author; adds a JS toolchain to a Python gate |
| DeepEval / Ragas | RAG metrics off the shelf | ADR 0005 already chose custom metrics over Ragas deliberately |
| LangSmith / Braintrust / Phoenix | hosted tracing + eval UX | hosted, costs money, owner decision |
| OpenAI Evals | registry-style task definitions | provider-shaped; this repo is Anthropic-native |

**Adopt the practices, not the platform.** Phase A takes the ideas — pinning,
versioning, provenance, intervals, aggregation — into the harness that already
exists. That harness is well-built; its defect is integrity of attribution,
not architecture.

## 3. Safety and adversarial evaluation

### OWASP Top 10 for LLM Applications (2025)

The category set Phase A maps to, and where each lands for this system:

| ID | Category | Relevance here |
|---|---|---|
| LLM01 | Prompt injection | **primary** — retrieved paper text and learner text are both untrusted |
| LLM02 | Sensitive information disclosure | **primary** — raw exception text to clients (baseline §2), report bodies to logs (§5) |
| LLM03 | Supply chain | covered by ADR 0045's lock discipline and the web audit gate |
| LLM04 | Data and model poisoning | poisoned paper metadata, source laundering |
| LLM05 | Improper output handling | export renderers, markdown → PDF/DOCX |
| LLM06 | Excessive agency | **rising** — the reason this phase precedes MCP and new tools |
| LLM07 | System prompt leakage | prompt-isolation boundary |
| LLM08 | Vector and embedding weaknesses | embedding cache and retrieval path |
| LLM09 | Misinformation | the faithfulness/citation metrics exist for this |
| LLM10 | Unbounded consumption | cost caps exist; per-principal ceilings do not (baseline §5) |

OWASP's agentic-AI threat work extends this for tool-using agents; it is the
right reference to revisit when MCP lands, not before.

### Corpus strategy

Phase A **authors** its corpus rather than importing one. Public suites worth
knowing — AgentDojo and InjecAgent for tool-using injection, JailbreakBench
and HarmBench for refusal, `garak` and PyRIT as scanners — each carry a
licence, an environment, and a maintenance cost, and none of them knows this
system's tool surface. A small, honest, repository-specific corpus with
behavioural assertions beats a large imported one scored on substrings.

The measurement that matters is **attack success rate with its denominator**,
plus zero-tolerance classes that fail on a single occurrence. A canary
substring check is not a safety metric: a model that obeys an injection while
paraphrasing passes it, which is exactly the defect WO-A11 exists to fix.

## 4. Assurance and compliance frameworks

The goal is not certification. It is that a reviewer can ask "how do you know?"
and get an artifact rather than a paragraph.

### NIST AI RMF 1.0 + the Generative AI Profile (NIST AI 600-1)

Four functions — **GOVERN, MAP, MEASURE, MANAGE**. What each asks a repository
to actually produce:

| Function | Artifact this repository can produce |
|---|---|
| GOVERN | ADRs, the charter's constraint list, the owner-decision ledger |
| MAP | intended use and out-of-scope use in the model card; the threat model in `docs/security.md` |
| MEASURE | eval reports with provenance and intervals; the safety report with its denominator; coverage and gate output |
| MANAGE | runbooks, alert rules, the known-gaps register, rollback statements in every work order |

### ISO/IEC 42001

An AI management-system standard: policy, roles, risk assessment, lifecycle
controls, documented information. Full conformance needs organizational
process this project does not have and should not pretend to. What is worth
borrowing is its **documented-information discipline** — decisions, changes and
evidence are recorded and retrievable, which is what the ADR + evidence-pack
habit already does.

### EU AI Act (Reg. (EU) 2024/1689)

This system is a research and study assistant; it is very unlikely to be
high-risk. Adopting the Act's *record-keeping posture* is still the cheapest
way to be defensible later:

- **Article 12-style logging**: automatic recording of events over the
  system's lifetime, sufficient to trace behaviour after the fact. That is
  precisely correlated run/job/request identity plus retained eval and safety
  records — WO-A03, A07 and A08.
- **Transparency**: users are told they are interacting with an AI system and
  what its limits are — the model card.
- **Technical documentation**: architecture, data sources, evaluation results,
  known limitations — the assurance pack in WO-A14.

> **Verification note:** the Act's application timeline for GPAI and high-risk
> obligations has been subject to amendment proposals. WO-A14 states dates
> only if it verifies them at the time of writing; otherwise it describes the
> obligations without asserting a schedule.

## 5. Reliability engineering

- **SLIs before SLOs, SLOs before alerts.** An alert that does not defend an
  SLO is noise. Phase A defines the SLIs it can actually measure and says
  plainly that the initial objectives are declared, not earned.
- **Error budgets** make "how reliable" a decision rather than an argument.
- **Circuit breaker, bulkhead, timeout, retry with jitter, idempotency** —
  the standard set. The repository already has bulkheads (semaphore + thread
  pool) and a clamped retry envelope for the model path; it is missing
  breakers everywhere and timeout hygiene in two places.
- **Graceful degradation must be visible.** This repository degrades well and
  reports it poorly: the reader's abstract-only fallback is tallied and logged
  but never reaches the user (baseline §2). Degradation that the user cannot
  see is indistinguishable from a confident wrong answer.

## 6. Testing practice

| Practice | Verdict for this repository |
|---|---|
| Property-based testing (Hypothesis) | **adopt** — parsers and redaction are the ideal shape, and a hand-written property already exists |
| Branch coverage with a ratcheting floor | **adopt** — the web half already does this; the Python half does not |
| Deterministic isolation (no net, no key, no ambient env) | **adopt** — the single highest-value missing piece |
| Fault injection as a first-class tier | **adopt** — error-handling code is otherwise untested by construction |
| Schemathesis against OpenAPI | **skip** — large dependency tree against ADR 0045's deliberately small lock; the property tier covers the same parsers |
| Mutation testing (mutmut / cosmic-ray) | **skip for now** — hours of runtime with no CI home; revisit as an out-of-CI cadence |
| VCR-style cassettes | **skip** — recording them requires paid calls; mock mode is the existing zero-spend seam |
| Flake quarantine policy | **adopt the policy**, not a plugin — a documented rule and a marker |

## 7. What a repository this size should not adopt

Being realistic about a solo-maintainer project under a hard zero-spend
constraint matters more than being comprehensive:

- **No hosted eval or observability platform.** Costs money, and the value
  arrives only once there is traffic to observe.
- **No external benchmark suite as a product objective.** Useful for
  comparability later; a distraction now, and each one carries licence and
  contamination homework.
- **No certification pursuit.** Map to the frameworks, produce the artifacts,
  claim nothing an auditor has not granted.
- **No RL, preference learning, or post-training.** That is the other
  program's horizon, and it is gated on funded measurement that does not exist.
- **No 100% coverage target.** A floor that ratchets beats a number that
  invites tests written to execute rather than to assert.
