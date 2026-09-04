# Standards adopted, and what they actually require

Status: **RESEARCHED AND VERIFIED 2026-09-04**

Phase A is deliberately unoriginal. Every convention below already exists, has
a specification, and has tooling that reads it. Inventing a private convention
would cost the same effort and buy none of the interoperability — which
matters here specifically because the owner's reason for this phase is *"we
can build on top of this and add mcp and other agent tools and infra."*
Infrastructure reads standard names.

**Method.** The OpenTelemetry section was verified against the specification
markdown sources directly, not against search summaries or recollection,
because implementers are held to these attribute names. The remaining sections
were verified against primary sources with version numbers, licences and
release dates pulled live from the PyPI and GitHub APIs. Where a claim could
not be verified at the primary source, it is marked. Several widely-repeated
beliefs turned out to be **wrong**, and those are called out — a plan that
silently carries a false premise is worse than one that has none.

## 1. OpenTelemetry GenAI semantic conventions

### 1.1 The three facts that change how we adopt this

1. **The conventions have moved out of the core repository.**
   `semantic-conventions` v1.42.0 (12 Jun 2026) deprecated and relocated every
   `gen_ai.*` span, metric, event and attribute to
   `open-telemetry/semantic-conventions-genai`; v1.43.0 ships none of them.
   The familiar `opentelemetry.io/docs/specs/semconv/gen-ai/` pages are
   redirect stubs.
2. **Nothing is stable and there is nothing to pin.** Every GenAI span, metric,
   event and attribute carries a `Development` badge, and the new repository
   has **no tags and no releases**. There is therefore no versioned schema URL.
   WO-A07 pins a **commit SHA** in its ADR instead, and states that the names
   are expected to churn.
3. **A widely-repeated blog claim is false.**
   `OTEL_SEMCONV_STABILITY_OPT_IN` does **not** govern GenAI content capture —
   it appears nowhere in the GenAI conventions. The only opt-in environment
   variable the conventions define is
   **`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`**.

### 1.2 Spans

Name is `{gen_ai.operation.name} {gen_ai.request.model}`; kind `CLIENT`
(`INTERNAL` for an in-process model).

Only two attributes are **Required**: `gen_ai.operation.name` and
**`gen_ai.provider.name`**. Note that this is *not* `gen_ai.system` — the
attribute was renamed, and `gen_ai.system` is the single most likely stale
name to appear in an implementation written from memory.

- **Conditionally required**: `error.type`, `gen_ai.conversation.id`,
  `gen_ai.output.type`, `gen_ai.request.model`, `gen_ai.prompt.name` /
  `gen_ai.prompt.version`.
- **Recommended**: `gen_ai.request.{temperature,top_p,top_k,max_tokens,stop_sequences,seed}`;
  `gen_ai.response.{id,model,finish_reasons,time_to_first_chunk}`;
  `gen_ai.usage.{input_tokens,output_tokens}` plus
  `gen_ai.usage.cache_read.input_tokens`,
  `gen_ai.usage.cache_write.input_tokens`,
  `gen_ai.usage.reasoning.output_tokens`; `server.address` / `server.port`.

`gen_ai.operation.name` is an enum: `chat`, `generate_content`,
`text_completion`, `embeddings`, `retrieval`, `execute_tool`, `create_agent`,
`invoke_agent`, `invoke_workflow`, `plan`, `fetch_response`, plus seven memory
operations.

**The agent and tool spans map directly onto this repository's graph**, which
is the part that makes adoption worth more than a rename:

| Span | Kind | Fits |
|---|---|---|
| `invoke_agent {gen_ai.agent.name}` | INTERNAL (in-process) | each graph node: planner, search, reader, synthesizer, critic, verifier, supervisor, tutor |
| `plan {gen_ai.agent.name}` | INTERNAL | the planner node specifically |
| `invoke_workflow {gen_ai.workflow.name}` | INTERNAL | a whole research run or guided-read session |
| `execute_tool {gen_ai.tool.name}` | INTERNAL | arXiv search, Semantic Scholar, PDF fetch, embedding |
| `create_agent {gen_ai.agent.name}` | CLIENT | not applicable here |

Agent identity is `gen_ai.agent.{id,name,description,version}`; tool spans take
`gen_ai.tool.name` (required) plus `gen_ai.tool.call.id`, `.description`,
`.type`.

### 1.3 Metrics

All histograms: `gen_ai.client.token.usage` (`{token}`),
`gen_ai.client.operation.duration` (`s`),
`gen_ai.client.operation.time_to_first_chunk` (`s`),
`gen_ai.client.operation.time_per_output_chunk` (`s`),
`gen_ai.invoke_agent.duration` (`s`),
**`gen_ai.invoke_agent.inference_calls`** (`{inference_call}`),
**`gen_ai.invoke_agent.tool_calls`** (`{tool_call}`),
`gen_ai.execute_tool.duration` (`s`), `gen_ai.invoke_workflow.duration` (`s`),
and the server-side `gen_ai.server.request.duration`,
`.time_to_first_token`, `.time_per_output_token`. `gen_ai.token.type` is
`input` or `output`.

The two agent-level counters are worth noticing: "inference calls per agent
invocation" and "tool calls per agent invocation" are exactly the process
metrics an agent system needs, and they are conventional rather than ours to
invent.

**Cost has no conventional attribute.** The repository's `llm_cost_usd_total`
stays, in its own namespace, and that decision is recorded rather than papered
over.

### 1.4 Content capture

The per-message events (`gen_ai.user.message`, `gen_ai.choice`, …) are **gone**.
Content is now carried as **Opt-In span attributes**: `gen_ai.input.messages`,
`gen_ai.output.messages`, `gen_ai.system_instructions`,
`gen_ai.tool.definitions`, `gen_ai.retrieval.documents`,
`gen_ai.retrieval.query.text`. Events collapsed to a single
`gen_ai.client.inference.operation.details`.

The specification says instrumentations "SHOULD NOT capture them by default,
but SHOULD provide an option for users to opt in", and sanctions three
patterns: do not record; record on span attributes (**pre-production**); or
**store externally and record references (production)**.

**Phase A keeps capture off.** This system's telemetry would otherwise carry
paper text, learner text and research queries.

### 1.5 Two conventions we are not implementing yet, but should know exist

- **`gen_ai.evaluation.result`** is a defined event —
  `gen_ai.evaluation.name` (required), `.score.value`, `.score.label`,
  `.explanation`, `gen_ai.response.id`. It is the standard way to attach an
  eval verdict to a trace. WO-A08/A09 record it as the target shape for eval
  emission rather than inventing one.
- **MCP conventions live in the same repository**: `mcp.method.name`,
  `mcp.session.id`, `mcp.request.id`, `mcp.protocol.version`,
  `mcp.resource.uri`; spans `{mcp.method.name} {target}` as CLIENT/SERVER;
  metrics `mcp.client.operation.duration`, `mcp.server.operation.duration`,
  `mcp.session.duration`. **This is the owner's stated next step, and its
  telemetry is already drawn.** Adopting `gen_ai.*` now means MCP
  instrumentation later is a continuation rather than a second convention.

The HTTP conventions, unlike GenAI, are **stable**: `http.request.method`,
`http.route`, `http.response.status_code`, and
`http.server.request.duration` in seconds. Use `http.route` (the template),
never the raw path — that cardinality rule is in the specification, not our
invention.

## 2. Evaluation practice

### 2.1 The taxonomy has settled

Three layers, arrived at independently by several toolchains: **final
response**, **trajectory**, **single step**. Trajectory comparison modes are
semantically stable even though their names are not — strict / unordered /
subset / superset in one vocabulary, EXACT / ANY_ORDER / IN_ORDER in another.
Metric names that are stable across tools: `ToolCorrectness`,
`ArgumentCorrectness`, `TaskCompletion`, `PlanAdherence`,
`AgentLoopDetection`.

**`pass^k` has displaced `pass@1`** as the honest reliability statistic:
`pass^k` is the probability that *all* k trials succeed, which is what a user
experiences from a system they use repeatedly. Published agent results show
the gap is not academic — a model at roughly 61% `pass^1` can fall to about
25% at `pass^8`.

### 2.2 Judge reliability — three 2026 results that change practice

1. **Raw agreement badly overstates chance-corrected agreement**, by 33–41
   percentage points in a 21-judge study: 85% exact match corresponds to a
   κ around 0.48. Any report of judge quality that quotes raw agreement is
   quoting the wrong number.
2. **Verbosity bias has collapsed** (below 0.011 across all 21 judges
   measured). The 2023-era folk model that "judges love long answers" is
   **out of date**, and a plan that spends effort controlling for it is
   spending effort in the wrong place. **Position bias has not** collapsed
   (0.002–0.192 depending on judge) and remains worth controlling, by
   swap/AB+BA averaging — prompt-based debiasing ("be position-neutral")
   has near-zero effect.
3. **For binary verdicts, Pearson, Spearman, Kendall, φ and MCC are the same
   statistic** — report φ/MCC, and always publish the judge's and the human's
   positive rates, because κ = q·φ and κ is not interpretable without them.
   **Abstention handling swings measured accuracy by 10–34 points** on
   identical verdicts, so how abstentions are counted must be stated.

A fourth result bounds what ensembles buy: a nine-judge panel yields an
effective sample size of about 2.2. Panels are not a substitute for a better
instrument.

### 2.3 Statistics — the finding that changes the budget

**Pairing is worth an order of magnitude.** To detect a 5-point gain against
an 80% baseline: roughly **906 items per arm unpaired**, versus roughly **77
paired** using McNemar at low discordance. Always run the baseline and the
candidate on the same items.

Two further constraints matter at this repository's scale:

- Guidance to use ≥1,000 questions for 3-point resolution assumes the
  central-limit approximation holds. **Below a few hundred datapoints the CLT
  materially underestimates uncertainty** — which is exactly the regime of a
  20-query benchmark and 15 learning scenarios. A Bayesian treatment is the
  correct tool there, and a gate that reports a normal-approximation interval
  on N=20 is reporting a number that is too narrow.
- For a suite that passes cleanly, use the **rule of three**: zero failures in
  n trials supports an upper bound of about 3/n, not "zero risk".

Report Wilson intervals for binary rates. Predeclare the primary metric;
treat slices as diagnostic unless a correction was declared in advance,
because 20 independent per-query tests produce false alarms by arithmetic.

### 2.4 Dataset discipline

The practical guidance that holds up: review on the order of 30 traces by
hand, grow to ~100 until failure modes saturate, and budget **100–200 labelled
examples per failure mode** to build a judge; split train/dev/test and keep a
private holdout. Ship a canary GUID but do not trust it — canaries are
demonstrably reproduced by trained models.

### 2.5 Frameworks — the landscape churned hard

| Tool | Status as verified | Verdict here |
|---|---|---|
| promptfoo | **acquired by OpenAI (Mar 2026)**; MIT; native tool-sequence assertions; built-in OTLP receiver | good, but adds a JS toolchain to a Python gate |
| OpenAI Evals | **abandoned**; the hosted Evals platform **shuts down 30 Nov 2026** | do not adopt |
| Ragas | **stalled** (org renamed, ~591 open issues) | ADR 0005 already rejected it; that call aged well |
| Arize Phoenix | core and `arize-phoenix-evals` are **Elastic License 2.0, not Apache** | licence-check before it enters a public requirements file |
| Langfuse | acquired by ClickHouse | hosted; owner decision |
| DeepEval | Apache-2.0; agentic metrics as pytest assertions; local-model support | strongest candidate for a later pytest-native eval gate |
| Inspect AI | MIT; best local-model support; ships `inspect_evals` | strongest candidate for the safety lane |

**Adopt the practices, not the platform.** Phase A takes pinning, versioning,
provenance, pairing and intervals into the harness that already exists. That
harness is well-built; its defect is integrity of attribution, not
architecture.

### 2.6 The domain gift: groundedness without a judge

This repository works over arXiv papers, which means two of the most valuable
accuracy signals are **deterministically checkable**:

- does every cited arXiv identifier actually resolve to a paper?
- does every quoted span appear **verbatim** in the fetched PDF?

That is hallucination measurement with **zero model calls**, and it is
strictly more defensible than a judge. Phase A adds it as WO-A16. It is the
single highest-value evaluation item available at zero spend, and it exists
only because of the domain.

## 3. Safety and adversarial evaluation

### 3.1 Threat model

The compact framing that has held up is the **lethal trifecta**: private data,
untrusted content, and an egress channel. Remove one leg architecturally; a
filter that is 95% effective is not a control. Current agentic threat
taxonomies add agentic supply-chain compromise, goal hijacking, inter-agent
trust escalation, session-context contamination and MCP/plugin abuse — the
last of which is not hypothetical, with on the order of 99 MCP-related CVEs
recorded in 2025.

### 3.2 The list to map against is the agentic one

The OWASP LLM Top 10 (2025) is what most plans cite, and a **2026 edition now
supersedes it** (Excessive Agency rises to third; system-prompt leakage is
broadened into hidden-context exposure). But for a tool-using agent the more
relevant list is **OWASP Top 10 for Agentic Applications (ASI01–ASI10)**:
goal hijack, tool misuse, identity and privilege abuse, agentic supply chain,
unexpected code execution, memory and context poisoning, insecure inter-agent
communication, cascading failures, human-agent trust exploitation, rogue
agents.

**Phase A maps to the agentic list as primary and the LLM list as secondary.**

> **Licensing constraint, and it is a real one.** OWASP prose is **CC BY-SA
> 4.0, which is viral**. WO-A11 and WO-A14 cite category **codes** and write
> their own descriptions. They do not copy OWASP text into this repository.

### 3.3 Corpus strategy

Permissive, offline, judge-free options exist and are better than they were:

- **AgentThreatBench** (MIT, ships in `inspect_evals`, ~24 samples, rule-based
  scorers, no judge model) and **CodeIPI** (MIT, ~45 samples, runs with the
  container network disabled and canary files) — together ~69 samples with no
  API keys, which is a genuinely free safety regression gate.
- **AgentDojo** (MIT, ~629 security cases, rule-based).
- **`nvidia/Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1`** (CC-BY-4.0,
  ungated, ~1,272 rows, deterministic verifier) — the best licence-and-offline
  fit, and the cleanest **schema** to model ours on.

**Avoid:** BeaverTails (CC-BY-NC) and AgentHarm (field-of-use clause) — do not
redistribute either. Note also that PyRIT moved repositories, Lakera's PINT
was never public, and `protectai/llm-guard` is archived (its DeBERTa model
survives under Apache-2.0).

Phase A still **authors** its own corpus, because none of the above knows this
system's tool surface — but it models the schema on the Nemotron set and
records the others as adoption candidates rather than pretending they do not
exist.

### 3.4 How to gate on safety without fooling ourselves

Two findings make the obvious design wrong:

1. **Attack success rate is a property of the deployment surface, not the
   model.** Published measurements put the same model near 0% in a constrained
   environment and near 79% by attempt 200 in a permissive one. An absolute
   ASR threshold is therefore not portable, not even across our own surfaces.
2. **At small n, an ASR threshold flips on noise.** At n=100, an observed 3%
   has a Wilson interval of roughly 1.0–8.5%, so a gate at "ASR < 5%" is a
   coin flip.

The design Phase A adopts:

- gate on **regression-delta against a fixed baseline**, not an absolute rate;
- reserve **absolute zero** for categorical hard violations — a secret
  exfiltrated, an unauthorised tool called, egress to a non-allowlisted host;
- a three-state **PROMOTE / HOLD / ROLLBACK** decision, safety veto evaluated
  first, advisory-by-default behind a flag until the baseline is trusted;
- **zero LLM calls inside the gate logic.** Content-preserving wrappers flip
  57–100% of LLM-judge verdicts, so a judge in the gate is an attack surface,
  not a control.

Defensively, the published pattern set worth knowing is Action-Selector,
Plan-Then-Execute, Dual LLM, Map-Reduce, Code-Then-Execute and
Context-Minimization.

## 4. Assurance and compliance

The goal is not certification. It is that a reviewer can ask "how do you know?"
and get an artifact rather than a paragraph.

### 4.1 EU AI Act — narrower than assumed, and the dates moved

- The high-risk timeline **slipped** under the Digital Omnibus, Regulation
  (EU) 2026/1744: Annex III from 2 Aug 2026 to **2 Dec 2027**; Annex I to
  2 Aug 2028.
- **Article 50 transparency did not move** and has applied since 2 Aug 2026.
- Article 2(12) exempts free and open-source software **unless** Article 5 or
  Article 50 applies — so Article 50 punches through the FOSS exemption.
- Annex III's education entry is bounded by *"in educational and vocational
  training institutions"*. A standalone study assistant is **out of scope**;
  the same system deployed by a school to score work or steer progression is
  in. A public repository is a weak trigger; **a hosted demo is "putting into
  service"**.

**Practical position:** satisfy Art. 50(1) — tell the user they are
interacting with an AI system, clearly and at first exposure — and **document
why Art. 50(2) machine-readable synthetic-content marking is not currently
feasible for text**: the C2PA reference implementation has no text handler,
and sampling-time watermarking is unavailable when calling a hosted API. The
relevant Code of Practice concedes that no single technique meets all four
required qualities.

> **Verification caveat, carried deliberately.** EUR-Lex returns an empty body
> to automated fetch, so the article-level detail of Regulation 2026/1744 was
> reconstructed from secondary analyses. The regulation number and the
> application dates corroborate across many independent sources; **annex-level
> changes are contested between sources**. WO-A14 must re-verify before
> asserting any date, and may describe obligations without asserting a
> schedule.

### 4.2 NIST

AI RMF 1.0 (**AI 100-1**) — GOVERN, MAP, MEASURE, MANAGE across 72
subcategories; currently under revision. The GenAI Profile is **AI 600-1**
(12 risk categories, 212 suggested actions). The highest-yield subcategories
for a repository:

- **MEASURE 2.1** — test sets, metrics and TEVV tooling are *documented*.
  This is precisely WO-A08's provenance block.
- **MEASURE 2.7**, **MANAGE 3.2**, **MANAGE 4.3**.
- **GV-4.3-002** supplies a literal incident-report schema — use it for the
  issue template rather than inventing fields.
- **MS-1.1-009** explicitly sanctions tracking risks you *cannot* measure,
  with an explanation of why. That is the honest-gaps register, blessed by the
  framework. It is the reason WO-A14's mapping must have a non-empty "not
  satisfied" column.

**NIST AI 300-1 ipd** (30 Jul 2026) defines conformity-assessable **dataset
(7-field) and model (8-field) documentation templates** — the best free
template available, and what WO-A14's data-provenance record should follow.

### 4.3 ISO

42001:2023's **Annex B is normative** and is roughly half the standard; the
controls that map to this phase are A.6.2.8 (event logs), A.6.2.4
(verification and validation), A.7.5 (data provenance), A.5.2–A.5.5 (impact
assessment) and A.10.3 (suppliers). ISO/IEC 22989 is free and is 42001's only
normative reference.

**Certification is explicitly not for this project**: clause 9.2 requires
auditors who do not audit their own work, which is structurally unsatisfiable
at N=1; it is a recurring five-figure commitment; and the European harmonised
version is not harmonised, so it buys nothing under the AI Act.

**Watch item:** ISO/IEC FDIS **24970 — AI system logging** is at stage 50.20
and publishes shortly. It is likely to become the reference for exactly the
log schema WO-A03 is defining, which is why that work order keeps its field
names as constants in one place rather than as literals in a formatter.

### 4.4 The git-native argument, and the artifact set

ISO 7.5.2/7.5.3 want documented information to be identified, authored, dated,
reviewed, version-controlled, integrity-protected and retained. Reviewed pull
requests plus signed tags supply all seven, and NIST **MS-2.8-003** explicitly
credits version control.

⚠ **CI runs are not the record** — artifact retention is finite (90 days here).
The committed, dated summary is the record.

The artifact set that satisfies all three frameworks at once:

- **`docs/assurance/framework-mapping.md`** — the keystone crosswalk:
  framework | control id | how satisfied | artifact path | last reviewed SHA |
  Met / Partial / Out-of-reach.
- **A system card, not a model card.** This project does not train models; the
  honest artifact describes the *system*.
- Dataset cards on the NIST AI 300-1 field set.
- A documented log schema using `gen_ai.*` names where they exist.
- Dated evaluation and safety reports committed to the repository.
- An AI-incident issue template on the GV-4.3-002 fields.
- An SBOM — `pip-audit --format cyclonedx-json` produces SBOM and
  vulnerability audit from one PyPA tool.

## 5. Reliability engineering

### 5.1 The SRE canon already covers quality

The SRE Workbook's SLI menu lists **quality** as a first-class SLI type — the
proportion of responses served in an undegraded state. Once expressed as
good/valid events, error budgets, burn rates and the multiwindow alerting
tables apply unmodified. This matters because there is **no credible public
methodology specifically for LLM quality error budgets**; the 2026 "AI agent
SLO" content is overwhelmingly marketing that publishes thresholds with no
derivation. Composing from the SRE quality SLI plus `pass^k` is the defensible
route, and Phase A says so rather than citing a blog number.

**Compounding is the number to keep in front of you:** 95% per step across
five steps is 77.4% end to end.

### 5.2 Retries, timeouts, and the breaker question

- **Retry amplification is the dominant risk**: three retries at five levels
  of a stack is 243× load. The rule is **retry at a single point in the
  stack**, and this repository currently retries in the model SDK *and* in
  `urllib3.Retry` *and* in three hand-rolled loops.
- **Choose timeouts from a false-timeout rate**, not from a round number: pick
  the percentile you are willing to cut off (e.g. 0.1% ⇒ p99.9).
- **Full Jitter** is the backoff to use:
  `sleep = random(0, min(cap, base * 2**attempt))`.
- **Circuit breakers are contested, and the contest matters here.** AWS argues
  against them — they introduce modal behaviour that is hard to test — and
  prefers a **retry token bucket**: a shared budget that throttles *retries*
  during an outage without changing the success path's behaviour. Nygard and
  Fowler argue for breakers. For this repository the token bucket wins on
  three counts: it is roughly twenty lines against the Redis that already
  exists, it introduces no second mode to test, and it directly addresses the
  measured problem (paying a full retry envelope per job during an outage).
  **`03-ARCHITECTURE.md` §2.3 was revised on this finding**; the breaker is
  recorded as considered and rejected, with the reason.
- **Hedged requests are exactly wrong at zero budget** — they double tail
  spend. The useful idea from the same source is the *good-enough partial
  response*.
- Library note: `stamina` (MIT) is the healthiest retry library — jitter by
  default, both attempt-count and total-timeout budgets, type hints preserved,
  and a testing mode that removes backoff. `tenacity` is healthy;
  `aiobreaker`, `purgatory` and `hyx` are effectively dead. Phase A does not
  add a retry dependency, but records `stamina` as the choice if one is ever
  added.
- Set `max_retries=0` on the model client if the application owns retries; the
  SDK's defaults will otherwise blow any request deadline.

### 5.3 Degradation must be visible

The degradation ladder, cheapest first: cached/stale with a disclosed age →
reduced-tool mode → partial results with confidence → streaming partials →
model fallback → bounded queue → honest refusal.

**Every rung must emit a distinct marker.** Otherwise degradation makes the
dashboard look *better* while the product gets worse — the same trap as
counting shed requests in a latency SLI. This repository already has the
failure it predicts: the reader's abstract-only fallback is tallied and
logged, and never reaches the user.

## 6. Testing practice

| Practice | Verdict | Why |
|---|---|---|
| Deterministic isolation (no net, no key, no ambient env) | **adopt** | the single highest-value missing piece; makes accidental spend impossible rather than unlikely |
| Property-based testing (Hypothesis, MPL-2.0) | **adopt** | parsers and redaction are the ideal shape; set `deadline=None` in CI |
| Hypothesis `RuleBasedStateMachine` on the checkpointer | **adopt selectively** | rules `{start_run, append_message, checkpoint, crash_and_resume}` with the invariant that resuming from any checkpoint is consistent with messages appended before it — this is where stateful testing pays |
| Branch coverage with a ratcheting floor | **adopt** | line coverage over-reports on compound booleans |
| **Patch coverage** (`diff-cover`, Apache-2.0) | **adopt** | coverage gains are logarithmic; the value is in *new* code. Runs locally, no account or token |
| Pragma counting | **adopt** | pragma growth is the most reliable tell that a coverage gate is being gamed |
| Fault injection as a first-class tier | **adopt** | error-handling code is otherwise untested by construction |
| Flake policy: rerun only marked-flaky tests, only on environmental error classes | **adopt the policy** | roughly 1 in 6 newly-flaky tests masks a real production bug, which is the argument against blanket reruns. `--only-rerun 'ConnectionError\|TimeoutError'`, never `AssertionError` |
| `pytest-randomly` | **adopt later** | finds order-dependence rather than retrying it |
| Schemathesis | **skip this phase** | `from_asgi` drives FastAPI in-process with no server, which is genuinely attractive — but it hard-requires `pytest>=9`, so adopting it forces a pytest major bump as a side effect |
| Mutation testing (mutmut 3.x, BSD-3) | **skip as a gate** | Google does not gate on mutation score; it surfaces surviving mutants as review comments. Revisit as a nightly reading list on 3–4 high-consequence modules |
| VCR-style cassettes | **skip** | recording requires paid calls; mock mode is the existing zero-spend seam |
| Hosted eval/observability platforms | **skip** | costs money; free tiers evaporate under CI |

### 6.1 A dependency landmine to record now

The model SDK's 1.x line runs on **`httpx2`**, and as a direct consequence
`respx`, `pytest-httpx` and OpenTelemetry's HTTPX instrumentation **do not see
the SDK's requests** unless an aliasing call is made at startup; passing a
plain `httpx` client raises `TypeError`.

This repository's `anthropic>=0.39.0,<1.0` cap currently shields it — but that
same cap now **blocks the upgrade**, and the upgrade breaks HTTP mocking. The
clean path when it is taken is to inject a client with a mock transport rather
than to monkeypatch, which is also a better test seam than what exists today.
Recorded here so the next person to raise the cap does not discover it in CI.

## 7. What a repository this size should not adopt

- **ISO 42001 certification.** Clause 9.2 is structurally unsatisfiable at
  N=1, it is a recurring five-figure commitment, and it buys nothing under the
  AI Act.
- **EU AI Act high-risk compliance work.** Out of Annex III scope unless a
  school deploys the system for scoring. Do Art. 50(1); document the 50(2)
  infeasibility.
- **LLM-as-judge inside a CI gate.** Judge verdicts flip 57–100% under
  content-preserving wrappers. Deterministic predicates are cheaper and more
  defensible; judges belong on dashboards.
- **Judge ensembles** (effective sample size ≈ 2.2), **hedged requests**
  (doubles tail spend), **circuit breakers** (token bucket preferred here),
  **mutation-score gates**, **blanket test reruns**, **100% coverage targets**.
- **An external benchmark as the product objective.** Useful for comparability
  later; each carries licence and contamination homework.
- **Copying OWASP prose** (CC BY-SA is viral) or redistributing CC-BY-NC or
  field-of-use-restricted datasets.
