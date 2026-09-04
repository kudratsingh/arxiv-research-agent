# Phase A target architecture

Status: **PROPOSED — the design the work orders implement**

This page is the design. [`04-WORK-ORDERS.md`](04-WORK-ORDERS.md) is the
execution plan and cites section numbers from here rather than restating
them. Where a decision is contestable, the alternative and the reason for
rejecting it are recorded inline, because a work-order agent that disagrees
needs to know whether it is disagreeing with an oversight or with a choice.

## 1. Shape

Five pillars, one substrate. The substrate is **identity**: a run, a request,
a job, a principal and a failure each need one stable name that every pillar
uses. Most of the baseline's disconnected symptoms — logs that cannot be
joined to traces, metric series that fork on a class rename, API errors that
clients cannot branch on, eval rows that cannot be attributed to a model —
are the same missing thing seen from five directions.

```text
                    ┌──────────────────────────────────┐
                    │  identity: error codes, run/req  │
                    │  ids, model+rubric provenance    │
                    └───────────────┬──────────────────┘
        ┌───────────────┬───────────┼───────────┬───────────────┐
   error handling    testing    evaluation   logging      observability
   AppError +        harness    integrity +  context +    GenAI semconv +
   envelope +        that       statistics + allowlist +  RED/USE + SLOs
   resilience        cannot     adversarial  redaction    + readiness
   policy            lie        suite
        └───────────────┴───────────┼───────────┴───────────────┘
                                    │
                        assurance evidence (R10)
```

## 2. Error model

### 2.1 The taxonomy

One base class in a new `src/errors.py`:

```python
class AppError(Exception):
    code: str             # stable, snake_case; part of the public contract
    http_status: int      # boundary mapping
    retryable: bool       # may the caller retry this exact request?
    public_message: str   # safe for a client; never upstream text
```

`code` is the identity that replaces `type(exc).__name__` in three places at
once: the API error body, the `job.error` field, and the `error_type` metric
attribute. It is a closed set — a module-level frozenset that a test asserts
against — because an open string used as a metric attribute is unbounded
cardinality (baseline §5) and an open string used as a client field is an
unversioned contract (baseline §2).

Code families, one per boundary meaning:

| Family | HTTP | Retryable | Example |
|---|---|---|---|
| `invalid_*` | 422 | no | `invalid_query`, `invalid_plan` |
| `not_found_*` | 404 | no | `not_found_job` |
| `unauthorized` / `forbidden` | 401 / 403 | no | `forbidden_principal` |
| `conflict_*` | 409 | no | `conflict_job_state` |
| `rate_limited` | 429 | yes, after `Retry-After` | — |
| `budget_exceeded_*` | 409 | no | `budget_exceeded_run` |
| `upstream_*` | 502/503 | yes | `upstream_model`, `upstream_arxiv` |
| `timeout_*` | 504 | yes | `timeout_job`, `timeout_upstream` |
| `cancelled_*` | 409 | no | `cancelled_job` |
| `internal_*` | 500 | no | `internal_unexpected` |

The 13 existing exception classes (baseline §2) are re-parented onto this
base and keep their names, so no call site's `except` clause changes meaning.
The 122 ad-hoc `raise ValueError` sites are **not** a migration target for
this phase: converting them all is a large, low-value diff. The rule adopted
instead is *boundary typing* — anything that can reach the API surface, a job
record, or a metric attribute must be an `AppError`; internal invariants may
stay `ValueError`. WO-A01 converts the reachable set and adds a test that
walks the route handlers to prove there is no other path.

**Rejected alternative:** an exception per HTTP status. It puts transport
concerns in domain modules and produces classes with no domain meaning.

### 2.2 The envelope

```json
{"error": {"code": "upstream_model", "message": "The model provider is unavailable.",
           "retryable": true, "request_id": "01J…"},
 "detail": "upstream_model"}
```

`detail` is retained because it is what the current web client and the
OpenAPI snapshot already read; the envelope is additive. Four handlers are
registered on `create_app`: `AppError`, `HTTPException`,
`RequestValidationError`, and bare `Exception`. The last one is the important
one — it is the path that today produces an untyped Starlette 500 with no
ERROR log (baseline §2).

**Never in `message`:** upstream exception text, DSNs, hostnames, paths,
prompt fragments. `job.error` becomes `code`, and the human-readable detail
goes to the log with the request id, not to the client. This closes the
`runner.py:1832` leak.

### 2.3 Resilience policy

- **A retry token bucket, not a circuit breaker** (`src/resilience.py`). A
  shared budget throttles *retries* during an outage without introducing a
  second mode to the success path. Standard-practice guidance is genuinely
  split here — Nygard and Fowler argue for breakers, AWS argues against them
  because they introduce modal behaviour that is hard to test — and
  [`02-STANDARDS.md`](02-STANDARDS.md) §5.2 records why the bucket wins for
  this repository: it is roughly twenty lines against the Redis that already
  exists, it adds no untested mode, and it addresses the measured problem
  (paying a full retry envelope per job during an outage) directly. **The
  breaker is considered and rejected, not overlooked.**
- **Retry at exactly one level of the stack.** Retry amplification is
  multiplicative — three retries at five levels is 243× load — and this
  repository currently retries in the model SDK, in `urllib3.Retry`, and in
  three hand-rolled loops. Consolidating to one owning level is worth more
  than any new mechanism.
- **Full Jitter** for every backoff: `sleep = random(0, min(cap, base * 2**attempt))`.
- **Timeouts are chosen from a false-timeout rate**, not a round number: pick
  the percentile you are willing to cut off and say which, rather than
  writing `30`.
- **Every timeout is a setting.** The hardcoded arXiv `timeout=30` moves into
  `Settings`; the HTTP retry budget gets the same clamp treatment
  `llm.py:62-91` already applies, including the WARNING when it bites.
- **Redis gets connect/socket timeouts and a health check interval**, and the
  rate limiter degrades to its in-memory backend and emits a metric rather
  than raising through an unguarded `pipe.execute()`.
- **The redriver gets an attempt counter and a dead-letter terminal state.**
  An unbounded requeue of a job that reliably kills its worker is the classic
  poison-message loop, and `job_redrive_requeue_pending` currently enables it.
- **`check_cancelled()` inside the search pacing loop**, so a cancelled job
  does not sleep through its drain window.

## 3. Test architecture

### 3.1 The harness that cannot lie

`tests/conftest.py`, autouse, in this order:

1. **Env isolation.** `Settings` is constructed with the developer `.env`
   neutralized; the ambient environment is cleared of the variables
   `config.py` reads and re-seeded with declared test values.
2. **Network guard.** `socket.socket.connect` raises `NetworkAccessDenied`
   for any non-loopback address. Opt out per-test with `@pytest.mark.network`
   (there are currently no legitimate users; the marker exists so that an opt
   out is visible in a diff).
3. **Spend guard.** `src.llm._get_client` raises unless a test has installed a
   fake through the shared seam in §3.2. This is the structural version of
   the two ad-hoc patches that exist today.
4. **Determinism.** `random.seed` and `PYTHONHASHSEED` fixed; a `frozen_clock`
   fixture available for the ~9 files currently hand-patching time.

Plus configuration that makes silence impossible: `--strict-markers`,
`--strict-config`, `xfail_strict = true`, a per-test timeout, and
`filterwarnings` escalated to `error` with the two documented C-extension
ignores retained.

**Rejected alternative:** a `pytest` plugin package. A single conftest is
readable in one screen and needs no packaging story.

### 3.2 Markers: two orthogonal axes

Today's three markers conflate speed with purpose, and 38 files carry none.

- **Tier** (exactly one per test, enforced): `unit`, `integration`, `e2e`.
- **Purpose** (zero or more): `security`, `property`, `fault`, `contract`.

This makes `pytest -m security` a runnable gate — the baseline's finding that
the tenancy and injection boundaries cannot be selected on their own — while
leaving CI's `-m "not e2e"` filter working unchanged.

### 3.3 Coverage as a floor, not a score

`pytest-cov` with **branch coverage on**, measuring `src/`. The initial
threshold is the measured value at adoption, rounded down — not an
aspirational number — and the rule is **ratchet up only**. Per-package floors
for the packages where a low number is a real risk (`src/api`, `src/agents`,
`src/security`, `src/eval`). Exclusions are listed explicitly with a reason
each, never a blanket `pragma`.

The known gaming failure of coverage gates is tests that execute code without
asserting on it. The counter-pressure here is §3.4 and §3.5, not a higher
percentage.

### 3.4 Property-based tests

`hypothesis`, applied where the input space is large and the invariant is
crisp: the chunker (never loses text, never exceeds max size, boundaries are
stable), citation extraction, the redaction functions (the secret is never in
the output — the existing `test_log_redaction.py:25` already writes this
property by hand for six cases), config validation, and SSE frame encoding
round-trips. Profiles are pinned and a `derandomize` setting is used in CI so
a failure is reproducible from the report alone.

### 3.5 Fault injection

A `fault`-marked tier that asserts *behaviour under failure*, which is the
half of error handling that unit tests never reach: Redis unavailable mid-job,
Postgres pool exhausted, model provider 429/500/timeout, cancellation between
nodes, worker death with lease expiry and redrive, cost cap trip mid-run, SSE
terminal frame delivery failure, breaker open and recovery.

Each fault test asserts three things: the failure produces the right
`AppError.code`, the right log event, and the right metric. That triple is
what makes the error model, the log contract and the telemetry contract
mutually enforcing instead of independently claimed.

### 3.6 The e2e tier

`docs/testing.md` has carried "planned, not built" for the cassette tier. It
gets built, at zero spend, using the mock path the learning lane already
proves works: the full research workflow start-to-report, asserted on the
trajectory (nodes visited, iteration count, terminal status, cost exactly
zero) rather than on prose.

## 4. Evaluation architecture

### 4.1 Integrity before statistics

A number is only worth a confidence interval if it is attributable. Three
changes, in this order:

1. **Pin the judges.** A dedicated `eval_judge_model` setting, passed
   explicitly at every judge call site, so the judge does not silently move
   when the product model is upgraded.
2. **Version the rubrics.** Each judge prompt gets a version constant beside
   it; changing the prompt without bumping the version fails a test.
3. **Record provenance on every row.** Judge model, product model, rubric
   versions, code commit, dataset version, seed, tier. A row that cannot say
   what produced it cannot participate in a comparison.

### 4.2 Statistics that match the claim

- **Pairing before power.** Detecting a 5-point gain against an 80% baseline
  needs roughly 906 items per arm unpaired and roughly 77 paired (McNemar) at
  low discordance. Always score the baseline and the candidate on the same
  items. At this repository's N, pairing is not an optimization — it is the
  difference between a measurable gate and an unmeasurable one.
- `src/eval/stats.py`: McNemar for paired binary outcomes; paired bootstrap
  confidence intervals over tasks with hierarchical resampling when repeats
  exist; Wilson intervals for binary rates; and the **rule of three** for a
  clean suite (zero failures in n supports an upper bound near 3/n, not
  "zero risk").
- **A minimum-N guard, and an explicit CLT caveat.** Below a few hundred
  datapoints the central-limit approximation materially *underestimates*
  uncertainty — which is exactly the regime of a 20-query benchmark. The gate
  reports that its interval is approximate at this N rather than quoting a
  falsely narrow one.
- **`pass^k`, not `pass@1`**, wherever a success rate is reported: the
  probability that *all* k trials succeed is what a user of a repeated
  workflow experiences.
- The research lane gains `--repeats`, and both lanes **aggregate** repeats by
  task before diffing rather than comparing `r1` to `r1`.
- The gate reports an interval and a decision, and is explicit that with
  today's N most single-metric moves are *not* separable from noise. Saying
  so in the report is the honest version of the flat ±0.10 band, which
  `docs/decisions/0044` already admits is "priors, not statistics".
- The two metrics whose quantization makes ±0.10 inoperative
  (completeness, retrieval recall) get their band derived from their actual
  quantum instead of a shared constant.
- `citation_accuracy` stops returning 1.0 for zero citations; the gate reads
  the corrected metric rather than relying on the README's compensating
  exclusion.
- `critic_score` is demoted from the gate to a reported diagnostic. A
  product component grading itself is not a gate, and its parse-failure `0.0`
  coercion makes it actively misleading.

**Bias controls, corrected by measurement.** Verbosity bias has collapsed in
current judges (below 0.011 across a 21-judge study), so effort spent
controlling for it is effort in the wrong place. **Position bias has not**
(0.002–0.192) and is controlled by swap/AB+BA averaging — prompt-based
debiasing has near-zero effect. And when judge quality is ever reported, it is
reported as **φ/MCC with both positive rates**, never as raw agreement, which
overstates chance-corrected agreement by 33–41 points; how abstentions are
counted must be stated, because it swings measured accuracy by 10–34 points.
See [`02-STANDARDS.md`](02-STANDARDS.md) §2.2.

**Note the boundary:** measuring judges against *human* labels is deferred to
the agent-engineering program's calibration work orders and to owner-approved
spend. Phase A does the part that costs nothing — pinning, versioning,
provenance, determinism, and position-bias probes on recorded fixtures.

### 4.3 Adversarial suite

A first-class corpus (`tests/fixtures/safety/`) with a scored gate, replacing
"5 regexes and a canary substring":

- **Categories mapped primarily to the OWASP Top 10 for Agentic Applications
  (ASI01–ASI10)** and secondarily to the LLM Top 10 — for a tool-using agent
  the agentic list is the relevant one ([`02-STANDARDS.md`](02-STANDARDS.md)
  §3.2). Cite category **codes** and write our own descriptions: OWASP prose
  is CC BY-SA 4.0, which is viral.
- **Attack success rate with its denominator, gated as a regression-delta
  against a fixed baseline — not as an absolute threshold.** ASR is a property
  of the deployment surface rather than of the model, and at n=100 an observed
  3% has a Wilson interval of roughly 1.0–8.5%, so an "ASR < 5%" gate flips on
  noise. Absolute zero is reserved for **categorical hard violations**: a
  secret exfiltrated, an unauthorised tool called, egress to a non-allowlisted
  host.
- **A three-state PROMOTE / HOLD / ROLLBACK decision**, safety veto evaluated
  first, advisory-by-default until the baseline is trusted, and **zero model
  calls inside the gate logic** — content-preserving wrappers flip 57–100% of
  LLM-judge verdicts, so a judge in a gate is an attack surface, not a
  control.
- **Judged by deterministic checks first** — behavioural assertions on what
  the agent *did* (which tools ran, which fields changed, what left the
  process), not only on whether a canary string appeared. A model that obeys
  an injection while paraphrasing must fail.
- The pedagogy deny-list becomes a campaign metric in `summary.jsonl`, not
  only a pytest assertion.

### 4.4 Groundedness without a judge

The domain hands this repository an accuracy signal most systems cannot have.
Because the corpus is arXiv papers, two of the most valuable checks are
**deterministic**:

- does every cited arXiv identifier resolve to a real paper?
- does every quoted span appear **verbatim** in the fetched PDF?

That is hallucination measurement with **zero model calls**, and it is more
defensible than any judge because it cannot be argued with. It also composes
with §4.2: a deterministic per-claim outcome is a paired binary variable,
which is precisely what McNemar needs.

WO-A16 builds it. It is the single highest-value evaluation item available at
zero spend, and it exists only because of the domain.

## 5. Telemetry architecture

### 5.1 One context

`src/observability/context.py` holds a single frozen dataclass in one
ContextVar: `run_id`, `job_id`, `request_id`, `job_kind`, `principal_hash`,
`worker_id`, plus `service` and `version` resolved once at startup. It
replaces the lone `_run_id` ContextVar, propagates across the thread-pool
boundary the way `propagate_run_context` already does, and is the single
source for both the log payload and span attributes.

`principal_hash` is a salted hash, never the key id — the metric layer
already made that call deliberately (`metrics.py:521`) and the log layer
should not undo it.

### 5.2 Log contract

- The formatter gains an **allowlist** and a **size cap** for `extra` fields.
  Anything not on the list is dropped with a counter, not silently merged.
- User content (query text, report bodies, learner text) is redacted by
  default and emitted only under an explicit opt-in setting, with the
  standard's content-capture flag as the model
  ([`02-STANDARDS.md`](02-STANDARDS.md) §1).
- `trace_id` and `span_id` join every record when a span is active, which is
  what makes exemplars and log-to-trace navigation possible.
- Event names become a closed set with a test, the same discipline as error
  codes.

### 5.3 Traces and metrics

- **LLM calls become spans**, with the GenAI conventional attributes and
  token/cost values, wrapped around the existing `record_llm_call` accounting
  so cost stays single-sourced.
- **Trace context is injected at job submission and extracted in the worker**,
  so an API request, its queued job, its nodes and its model calls are one
  trace instead of N roots.
- **Names follow the OpenTelemetry GenAI semantic conventions** where they
  exist, with the repository's existing names retained as aliases for one
  release so dashboards do not break silently. Exact names are fixed in
  [`02-STANDARDS.md`](02-STANDARDS.md) §1, not invented here — note that the
  provider attribute is `gen_ai.provider.name`, **not** the older
  `gen_ai.system`, and that the conventions have moved to their own repository
  with no tagged release, so the ADR pins a commit SHA.
- **The graph nodes become conventional agent spans**, not bespoke ones:
  `invoke_agent` (INTERNAL) per node, `plan` for the planner, `execute_tool`
  for arXiv/Semantic Scholar/PDF/embedding calls, `invoke_workflow` for a run.
  The conventions also define `gen_ai.invoke_agent.inference_calls` and
  `.tool_calls` — exactly the per-invocation process counters an agent system
  needs, already named for us.
- **`gen_ai.evaluation.result` is a defined event** and is the target shape for
  emitting eval verdicts onto traces later; WO-A08/A09 record it rather than
  inventing a shape.
- **MCP has conventions in the same repository** (`mcp.method.name`,
  `mcp.session.id`, `mcp.client.operation.duration`, …). Adopting `gen_ai.*`
  now makes the owner's stated next step a continuation rather than a second
  convention to reconcile.
- **RED for the HTTP surface** via one middleware: request count by
  route-template/method/status, duration histogram, in-flight gauge. Route
  *template*, never the raw path, or the cardinality bound is lost.
- **USE for the queue**: depth, wait time, and saturation against the
  concurrency ceiling — the baseline notes saturation is currently only
  visible after the ceiling is hit.
- **`kind` on job metrics**, and `degraded_close` stops reporting as
  `succeeded` with `error_type="none"`.
- **Tracer flush on shutdown**, matching the existing `shutdown_metrics`.
- **Sampling exposed in `Settings`** so tracing can be turned up without
  knowing OTel environment variables.

### 5.4 SLIs and SLOs

Defined in `docs/reliability.md`, instrumented by the above, and stated as
objectives with an error budget rather than as vibes:

| SLI | Definition | Initial objective |
|---|---|---|
| API availability | non-5xx / total on `/api/*` | 99.5% over 28d |
| Submit latency | p95 of `POST /api/research` | < 500 ms |
| Job success | `succeeded` / (terminal − user-cancelled) | ≥ 95% |
| Job latency | p95 job wall time by `kind` | research < 600 s |
| Model call error rate | `upstream_model` / total calls | < 2% |
| Cost per job | p95 `cost_usd` by `kind` | within cap, no cap trips ≥ 1% |
| Injection containment | contained / attempted | 100% (zero-tolerance) |
| Cross-principal leakage | observed leaks | 0 (zero-tolerance) |

Initial objectives are **declared, not yet earned**. The doc says so, and the
first honest job of the SLO is to be revised against measurement.

Three framing points, from [`02-STANDARDS.md`](02-STANDARDS.md) §5.1:

- The SRE Workbook already lists **quality** as a first-class SLI type — the
  proportion of responses served in an undegraded state. Expressed as
  good/valid events, error budgets and burn-rate alerting apply unmodified.
  There is no credible published methodology specific to LLM quality budgets,
  so this is the defensible anchor rather than a number from a vendor blog.
- **Degraded and shed requests are excluded from the latency SLI** and counted
  against quality instead. Otherwise degradation makes the dashboard look
  better while the product gets worse.
- **Compounding is the number to keep visible**: 95% per step across five
  steps is 77.4% end to end.

## 6. Operability

- `/healthz` becomes liveness (always cheap, always truthful about the
  process) and `/readyz` becomes readiness, returning **503 when degraded** so
  an orchestrator can drain. The current always-200 behaviour is retained on
  `/healthz` deliberately, and the split is what makes that safe.
- Runbooks for the incidents the instruments now make visible: model provider
  outage, Redis loss, Postgres loss, cost-cap storm, queue saturation, poison
  job, injection alarm. Each one names the signal, the first three commands,
  the containment action, and the rollback.
- Alert rules and a dashboard definition ship as reviewable files under
  `deploy/observability/`. Nothing is stood up; the owner decides that later.

## 7. Seams left open for the agent-engineering program

Phase A deliberately stops short in four places so the later contract set can
absorb this work instead of colliding with it.

| Seam | Phase A does | That program will |
|---|---|---|
| Run identity | keeps `run_id` as the single correlation key and records provenance fields on eval rows | replace with a sealed `RunManifest` identity |
| Trajectory | fault and e2e tests assert on node sequence; no event store is built | define `TrajectoryEvent` and its append-only store |
| Datasets | adds provenance/license/version metadata to the sets that exist | build the versioned registry with splits and contamination records |
| Judges | pins, versions, and mechanically bias-probes them | calibrate them against human labels under approved spend |

## 8. What Phase A deliberately does not build

- **Mutation testing.** `mutmut`/`cosmic-ray` on a 36k-line codebase with a
  35-second suite is a multi-hour job with no CI home, and the repository
  already has 24 hand-written "Mutation-check" notes. Recorded as a candidate
  for a later, out-of-CI cadence rather than half-done now.
- **Schemathesis against the OpenAPI schema.** More attractive than first
  assessed — `from_asgi` drives the FastAPI app in-process with no server or
  port. Rejected for this phase on a concrete blocker: it hard-requires
  `pytest>=9`, so adopting it forces a pytest major bump for the whole
  repository as a side effect of a testing PR. Revisit deliberately, not
  incidentally.
- **A hosted collector, Grafana, or any running observability service.** Costs
  money and is an owner decision.
- **Converting all 122 `ValueError` sites.** See §2.1.
- **Re-enabling either nightly workflow.** Out of scope by §5 of the charter.
