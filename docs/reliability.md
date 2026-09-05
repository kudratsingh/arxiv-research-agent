# Reliability

How this service fails, what a client is entitled to assume about it,
and what "working" is defined to mean.

| § | What it holds |
|---|---|
| [1](#1-the-error-contract) | **The error contract** — the envelope, the closed code set, and what a job record says when a run fails |
| [2](#2-what-an-slo-is-here) | **What an SLO is here** — the anchor, the compounding arithmetic, and why the objectives below are declared rather than earned |
| [3](#3-the-slis-and-their-objectives) | **The SLIs**, each with the exact instrument that measures it |
| [4](#4-error-budgets-and-burn-rate-alerting) | **Error budgets** and the burn-rate arithmetic |
| [5](#5-the-degradation-ladder) | **The degradation ladder** — every rung, its marker, and whether the user is told |
| [6](#6-the-runbooks) | **The runbooks** |
| [7](#7-what-is-not-measurable-today) | **What is not measurable today**, and the instrument each gap needs |

## 1. The error contract

### One envelope

Every error response from the API — every status, every route,
including the ones no handler anticipated — has this body:

```json
{
  "error": {
    "code": "job_not_found",
    "message": "That job is not available.",
    "retryable": false,
    "request_id": "5b1f0f7a1c0e4b0a9c6f0f2a5d8e3b41"
  },
  "detail": "job_not_found"
}
```

| Field | Meaning |
|---|---|
| `error.code` | The stable, machine-readable identity of the failure. Branch on this. Drawn from a closed set (`ERROR_CODES` in [`src/errors.py`](../src/errors.py)). |
| `error.message` | A sentence safe to show a person. Never contains upstream exception text, connection strings, hostnames or file paths. |
| `error.retryable` | Whether retrying **this same request** could succeed. `true` on 429 (after `Retry-After`), on `upstream_*` and on `timeout_*`; `false` on everything a client has to change something to fix. |
| `error.request_id` | Correlates the response with the server log record for it. Also returned as the `X-Request-Id` response header. |
| `detail` | The legacy field, retained. |

`detail` carries the code, with two deliberate exceptions where a shape
predates the envelope and a client parses it for structure:

- **429** — an object: `{"error": "rate_limited", "key_id", "limit_per_hour"}`.
- **422 from request validation** — FastAPI's `[{loc, msg, type}, ...]`
  array, which is what renders per-field form errors.
- **Two conflicts** — `job_not_awaiting_review (status=running)` and
  `session_not_awaiting_learner (status=awaiting_learner)` keep the
  parenthesised state. The same fact is in `error.message` in words.

The envelope is **additive**: nothing that was in `detail` before has
moved or changed. A client written against the old shape keeps working;
a new one reads `error.code` and never has to parse prose.

### Codes are a closed set

`error.code` is not a free string. Every value comes from a class in
[`src/errors.py`](../src/errors.py), and
[`tests/test_errors.py`](../tests/test_errors.py) proves in both
directions that the declared set and the implemented classes agree, and
that no two classes share a code.

That closure is what makes the code usable in three places at once:

1. the API body, where an open string would be an unversioned contract;
2. `JobDetail.error_type` and the `job_failed` SSE frame;
3. the `research_jobs_total{error_type}` metric attribute, where an open
   string is unbounded cardinality.

The families, and what each means for a client:

| Family | HTTP | Retryable | What it says |
|---|---|---|---|
| `invalid_*` | 422 | no | The request is malformed. Change it. |
| `not_found_*` | 404 | no | No such resource — **or** it belongs to another principal. The API answers identically for both, on purpose. |
| `unauthorized*` | 401 | no | No acceptable credential. |
| `forbidden*` | 403 | no | Real credential, disallowed action. |
| `conflict_*` | 409 | no | Well-formed, but the state moved. Re-read and decide again. |
| `rate_limited` | 429 | yes | After `Retry-After`. |
| `budget_exceeded_*` | 409 | no | A spend ceiling stopped the work. |
| `upstream_*` | 502 / 503 | usually | A dependency outside this process failed. |
| `timeout_*` | 504 | yes | Something exceeded its time budget. |
| `cancelled_*` | 409 | no | Stopped deliberately, not by a fault. |
| `internal_*` | 500 | no | Unanticipated. The traceback is in the log under `request_id`. |

Codes that were already on the wire before the taxonomy existed keep
their exact spelling — `job_not_found`, not `not_found_job` — because
renaming a published identifier is the harm the taxonomy exists to
prevent. The family is still readable from the HTTP status and the
`retryable` flag. See [ADR 0064](decisions/0064-error-taxonomy-and-envelope.md).

### Nothing internal leaves the process

`error.message` and `job.error` are written by us, from a fixed set of
sentences and codes. They never carry:

- exception text from a driver or a client library (psycopg messages
  embed the host, port and user; redis and httpx messages embed URLs),
- exception **class names** (an internal identifier, and one that
  changes under refactoring),
- file paths, prompt fragments, or anything of unbounded length.

The human-readable half is not discarded — it moves. Every handled
failure logs `error_code`, `error_detail` and the `request_id` that the
client was given, so an operator goes from a screenshot to the traceback
with one search.

### What a job record says when a run fails

`GET /research/{job_id}` returns `error` and `error_type`. Since
ADR 0064 both carry the same stable code, drawn from `JOB_ERROR_TYPES` —
the subset of `ERROR_CODES` a *run* can end up in, as opposed to the
codes a route answers with:

| `error_type` | What happened |
|---|---|
| `timeout` | The run exceeded the deployment's job wall clock. |
| `hitl_timeout` | A plan sat unreviewed past `api_hitl_timeout_sec`. |
| `session_turn_timeout` | A guided-read session waited too long for a learner reply. |
| `cost_budget_exceeded` | The run crossed `max_cost_usd`. A partial report may still be attached. |
| `session_cost_cap_refused` | A session hit its own ceiling before another model call. |
| `orphaned` | The worker running the job exited without publishing a terminal state; the redriver reclaimed it. |
| `cancelled_job` | A cooperative cancel fired. |
| `not_found_papers` | arXiv answered, and matched nothing. |
| `upstream_arxiv` | arXiv could not be reached. |
| `upstream_model` | The model provider refused the call or never answered it, after the SDK spent its clamped retry envelope. |
| `upstream_paper_read` | Papers were found and none could be read — for a reason other than the provider being down. |
| `upstream_model_output` | The model's output was unusable after a retry. |
| `internal_unexpected` | Anything else. Look up the `request_id` in the logs. |

`upstream_model` and `upstream_model_output` are the two halves of "the
model let us down" and the distinction is the actionable part: the first
means the provider did not answer and the run is worth retrying, the
second means it answered and what it said could not be used, which
retrying does not fix. Before WO-A17 the first had no code at all —
a provider outage arrived as `internal_unexpected` from most nodes and
as `upstream_paper_read` from the reader, so the same incident carried
two names and neither of them was its own.

### Where the contract is enforced

| Check | Proves |
|---|---|
| `tests/test_errors.py` | The closed set is closed, families match the table, and every `raise` in `routes.py` / `auth.py` / `sessions.py` is an `AppError` with a registered code. |
| `tests/test_api_error_envelope.py` | All four handlers produce the envelope; an unhandled exception yields 500 + `internal_unexpected` + an ERROR log and none of the exception's text; the legacy `detail` shapes survive. |
| `web/tests/copy/errorTypeDrift.test.ts` | The frontend has a sentence for every `error_type` the backend can produce — derived from `src/errors.py`, not transcribed. |

---

## 2. What an SLO is here

### The anchor, and why it is not a vendor number

There is **no credible published methodology specific to LLM quality
error budgets**. The 2026 "AI agent SLO" literature is overwhelmingly
marketing: thresholds published with no derivation, no denominator, and
no statement of what population they were measured over. A number
lifted from one of those posts would be a number this repository could
not defend, and defending its numbers is the whole point of the
assurance phase.

What *is* defensible is older and duller. The SRE Workbook's SLI menu
already lists **quality** as a first-class SLI type: *the proportion of
responses served in an undegraded state.* Nothing about that definition
requires the response to have been produced deterministically. Once
quality is expressed the way every other SLI is — as good events over
valid events — error budgets, burn rates and the multiwindow alerting
tables apply to it unmodified, with no new theory and no vendor.

So: quality is an SLI type, degradation is what makes an event bad, and
everything below is built from those two sentences.

### The exclusion that makes it honest

**Degraded and shed requests are excluded from the latency SLI and
counted against quality instead.**

This is not fastidiousness. A latency SLI that includes shed requests
gets *better* when the system sheds harder, because a 429 is fast. A
latency SLI that includes degraded responses gets better when the reader
gives up on full text and uses the abstract, because reading an abstract
is quick. In both cases the dashboard improves while the product gets
worse, and an operator watching the dashboard is being actively
misinformed by their own instruments.

Concretely, in this repository:

- `SubmitLatencyP95High` excludes `http.response.status_code` 429 and
  503. Those are the two shed classes: the rate limiter refusing, and
  readiness declining.
- `ResearchJobLatencyP95High` is cut to `status="succeeded"`, because a
  timeout kill lands in the histogram at exactly `API_JOB_TIMEOUT_SEC`
  and including it makes the p95 converge on the timeout and stop
  measuring anything.
- The job-success SLI counts `degraded_close` in its denominator and not
  its numerator, even though the job row says `succeeded`.

### The compounding arithmetic

The number to keep in front of you, because it calibrates expectations
better than any target on this page:

> **95% per step across five steps is 77.4% end to end.**
> (`0.95⁵ = 0.774`)

The linear research graph is exactly five agent nodes — planner, search,
reader, synthesizer, critic — so that is not a textbook example here, it
is the shape of the product. The supervised graph adds a supervisor and
up to two more optional nodes and re-enters them in a loop, which makes
it worse, not better.

Run it the other way and the consequence is sharper. To hold **95%
end to end** across five steps, each step has to hold

> `0.95^(1/5) = 0.9898` — **99.0% per step.**

Which is to say: a per-node reliability that sounds excellent produces
an end-to-end number that sounds poor, and the only two levers that
change that are fewer steps or per-step recovery. This repository uses
the second — the supervisor re-enters a failed node, the reader falls
back to abstract-only, the synthesizer re-prompts once on an unparseable
response — and every one of those recoveries is a rung on §5's ladder
that has to stay visible for the arithmetic to remain honest.

### The objectives are declared, not earned

Every number in §3 was chosen, not measured. No deployment of this
system has yet produced 28 days of traffic, and the pilot that will is
bounded to five people. Publishing them anyway is still worth doing —
an objective is a statement about what would count as a problem, and
having one is what makes the burn-rate alerting in §4 meaningful — but
they carry no evidentiary weight, and a reader must not treat them as
measurements.

**The first honest job of an SLO is to be revised against
measurement.** When the pilot produces data, the expected outcome is
that some of these numbers move, and moving them is the mechanism
working rather than an admission that this page was wrong.

## 3. The SLIs and their objectives

Every row names the instrument that measures it. A row whose instrument
does not exist is in §7 instead of here, because an objective with no
measurement behind it is a slogan.

| SLI | Good events / valid events | Instrument | Objective |
|---|---|---|---|
| **API availability** | non-5xx / all requests, health probes excluded | `http.server.request.duration` count, by `http.response.status_code` and `http.route` | **99.5%** over 28d |
| **Submit latency** | p95 of `POST /research`, 429 and 503 excluded | `http.server.request.duration` histogram, `http.route="/research"` | **< 500 ms** |
| **Job success** | `succeeded` / (terminal − cancelled) | `research_jobs_total`, by status, error type and kind | **≥ 95%** |
| **Job latency** | p95 wall clock of successful jobs, by kind | `research_job_duration_seconds` (conventional alias: `gen_ai.invoke_workflow.duration`) | research **< 600 s** |
| **Model call error rate** | calls with `error.type != "none"` / all calls | `gen_ai.client.operation.duration` count | **< 2%** |
| **Model call latency** | p95 of one provider call, retries included | `gen_ai.client.operation.duration` histogram | **< 60 s** |
| **Queue wait** | p95 seconds between acceptance and start | `research_job_queue_wait_seconds` | **< 60 s** |
| **Tool success** | tool executions with `error.type = "none"` | `gen_ai.execute_tool.duration` count, by `gen_ai.tool.name` | **≥ 95%** |
| **Spend, no cap trips** | jobs not ending at a ceiling / terminal jobs | `research_jobs_total{error_type="cost_budget_exceeded"}` and `{status="degraded_close"}` | cap trips **< 1%** |
| **Refusal rate** | 429s / accepted requests | `rate_limit_rejections_total`, by limiter backend | **< 1%**, and `backend="memory"` is **0** while configured for Redis |
| **Quality** | jobs served with no degradation / terminal jobs | `research_degradations_total`, cut by rung and component, against `research_jobs_total` | **≥ 97%** of jobs take no rung of §5, **declared** — and since CAP-08 computed over the whole ladder, see below |

### The quality row is the anchor, and it is the newest

§2 builds every objective on this page on the SRE Workbook's quality SLI
— *the proportion of responses served in an undegraded state* — and
until ADR 0081 there was no instrument for it, so it sat in §7 with the
other gaps. `research_degradations_total` is that instrument.

Two honesty notes belong on the row rather than under it.

**The denominator is jobs, the numerator is rungs, and they are not the
same shape.** One job can take several rungs, so
`sum(rate(research_degradations_total[5m]))` can exceed the job rate
during a bad interval. Read the ratio as *degradations per job*, and cut
by `rung` to get the per-rung rate that is actually comparable across
weeks. A true good-events / valid-events form would need a per-job
degraded flag on the terminal record; that is §7 item 9, and it is a
change to the job record rather than to this instrument.

**All six rungs that belong on this counter are now in it.** Rungs 2, 3
and 5 spent one wave log-only, because every one of their call sites is
in `src/agents/` and the work order that built the instrument held no
fence exception for that directory; CAP-08 wired them. The number is
therefore no longer a lower bound *by construction*, and the reader's
abstract-only fallback — the row §5 calls the named failure of this
document, and the one likeliest to fire often — is in the numerator.
Rungs 6 and 7 are in the ladder but on their own counters, so a complete
query is still a sum over three instruments:

```promql
sum(rate(research_degradations_total[5m]))
  + sum(rate(rate_limit_rejections_total[5m]))
  + sum(rate(research_jobs_total{status="degraded_close"}[5m]))
```

Two things still keep the measured number below the true one, and they
are narrower than the gap they replace. A degradation taken under `make
eval` or `make run` is counted nowhere, because those entry points
install no meter provider (§7 item 6) — a property of where the code
runs rather than of which rungs are wired. And the ladder is the set of
degradations somebody has *named*; a new one is invisible until it gets
a rung, which is what §5's table and `tests/test_degradation_ladder.py`
exist to force.

The 97% is **declared, not earned**, on the same terms as every other
objective in this table — but it is now declared against a numerator
that counts every rung of the published ladder, which is the difference
between an objective that could be missed and one that could not.

`03-ARCHITECTURE.md` §5.4 writes that first row as "on `/api/*`". The
routes are mounted at the root and it is the *web tier* that serves them
under `/api`, so the instrument sees `/research` rather than
`/api/research`. Measuring at the app is the right choice anyway — it is
the process that emits the metric, and a proxy hop that failed would
otherwise be counted as the API failing.

Two zero-tolerance objectives sit outside that table because they are
not runtime measurements:

| Objective | Target | How it is actually established |
|---|---|---|
| **Injection containment** | 100% | `pytest -m security` against a fixed adversarial corpus, at zero spend. A **build-time** gate, not a runtime SLI — nothing counts injection attempts in production. See [`runbooks/injection-alarm.md`](runbooks/injection-alarm.md). |
| **Cross-principal leakage** | 0 | `_check_ownership` on every request, asserted by `tests/test_per_principal_scoping.py`. The API answers identically for "does not exist" and "belongs to somebody else", which is deliberate and also means a leak attempt leaves no distinguishable runtime signal. |

Calling those two "SLOs" would be a category error. They are invariants
with tests, and a 100% target with no error budget is exactly what an
invariant is.

### The alias, and the one name that is not one

`research_job_duration_seconds` and `gen_ai.invoke_workflow.duration`
are a name and its conventional alias, and so are `llm_calls_total` and
`gen_ai.client.operation.duration`'s count. Both pairs are emitted for
one release, which doubles the series on those families — a real cost,
paid because a renamed metric does not error, it renders a flat zero,
and a flat zero reads as "the fleet is idle".

Neither pair is *exactly* the same measurement, and both differences
matter when reading a panel:

- The job histogram runs from acceptance through the terminal write; the
  workflow histogram bounds the workflow span. The gap between them is
  the queue wait plus the terminal persistence — a useful difference
  rather than a discrepancy.
- `llm_calls_total` counts calls that **returned**, because it is bumped
  from the cost choke point. `gen_ai.client.operation.duration`'s count
  includes failures and carries `error.type`, which is why every rule on
  this page that needs a denominator uses the conventional one.

`llm_cost_usd_total` is **not** an alias for anything. The GenAI
conventions define no cost metric, so that is the only name it has, and
it is estimated from token counts against a pinned price table rather
than billed by the provider. Treat it as the shape of the spend.

## 4. Error budgets and burn-rate alerting

An objective states what counts as a problem. A **budget** states how
much of it is allowed before the problem is one, and a **burn rate**
states how fast it is being spent. One is unusable without the others.

| SLO | Budget | Over 28 days that is |
|---|---|---|
| API availability 99.5% | 0.5% of requests | 3h 21m of total unavailability, or 1 request in 200 |
| Job success 95% | 5% of terminal jobs | 1 job in 20 |
| Model call error rate < 2% | 2% of calls | 1 call in 50 |

### The burn-rate arithmetic

A burn rate of **B** sustained for a window **W** consumes
`B × W / 28d` of the budget. That single line generates the whole
alerting table, so the constants below are checkable rather than copied:

| Burn rate | Long window | Budget consumed | Action |
|---|---|---|---|
| 14.4× | 1h | `14.4 × 1 / 672` = **2.1%** | page |
| 6× | 6h | `6 × 6 / 672` = **5.4%** | page |
| 3× | 24h | `3 × 24 / 672` = **10.7%** | ticket |
| 1× | 72h | `1 × 72 / 672` = **10.7%** | ticket |

Each rule pairs its long window with a **short window one twelfth its
length** and requires both to be burning. The short window is what makes
the alert *reset* promptly once the burn stops; without it, a rule that
fired on a five-minute outage keeps firing for the length of its long
window, and an operator learns to ignore it.

[`deploy/observability/alerts.yml`](../deploy/observability/alerts.yml)
implements the first two rows. The third and fourth need a ticket queue
to land in, and this repository has none; they are written down so that
adding them later is uncommenting rather than rederiving.

### The volume floor, which is not optional here

A burn rate is a ratio, and a ratio over a small denominator is noise.
At a 99.5% objective the expected number of errors in a healthy hour
only exceeds one at roughly **200 requests/hour**; below that, a single
failure produces a burn rate of 30× or more and pages.

This deployment's expected volume is a five-person pilot. So every
burn-rate rule carries an `and` clause requiring a floor of events in
its long window — 200 requests for the API SLO, **10 jobs** for the job
SLO, because a job is a minutes-long unit of work and a fleet serving
five people will never produce 200 of them in an hour. A rule that waits
for volume it will never see is a rule that never fires, which is
indistinguishable from no rule at all.

## 5. The degradation ladder

The ladder, cheapest first: **cached/stale with a disclosed age →
reduced-tool mode → partial results with confidence → streaming
partials → model fallback → bounded queue → honest refusal.**

**Every rung must emit a distinct marker.** Otherwise degradation makes
the dashboard look better while the product gets worse — the same trap
as counting shed requests in a latency SLI, and the reason for §2's
exclusion rule.

This repository already contains the failure that principle predicts,
and it is row 3.

Since ADR 0081 each rung also has a **rung token** — the closed value it
carries on `research_degradations_total{rung}`. The token is what a
PromQL selector and a runbook name, so it is in the table rather than
only in the code.

| Rung | Token | What it does here | Marker | On a metric? | User told? |
|---|---|---|---|---|---|
| **1. Cached / stale** | `cache_stale` | Paper text and embeddings served from the Postgres caches | `paper_cache_selected`, `embedding_cache_selected` at startup; `paper_cache_get_failed` / `embedding_cache_get_failed` on failure | **yes** — `research_degradations_total{rung="cache_stale"}`, by `component` | no — **and no age is disclosed** |
| **2. Reduced tool** | `reduced_tool` | Search proceeds on partial arXiv results, keeps prior papers, or serves the labelled fixture set | `search_partial_arxiv_failure`, `search_empty_keeping_prior_papers`, `search_mock_data_served`, `search_query_cap_applied` | **yes** — `research_degradations_total{rung="reduced_tool", component="search"}`, once per reduction (CAP-08) | only for the fixture path, whose banner says so |
| **3. Partial with confidence** | `partial_results` | **The reader falls back to abstract-only when full text cannot be read** | `reader_degraded_to_abstract_only`, `reader_paper_abstract_only` | **yes** — `research_degradations_total{rung="partial_results", component="reader"}`, once **per paper** (CAP-08) | **no** |
| **4. Streaming partials** | `streaming_partial` | SSE delivers what exists when the stream deadline arrives | `sse_stream_deadline_reached`, `sse_terminal_frame_flushed_at_deadline` | **yes** — `research_degradations_total{rung="streaming_partial"}`, on the deadline only | implicitly, by what arrives |
| **5. Model fallback** | `model_fallback` | Planner, supervisor, verifier and synthesizer substitute a default when the model's output is unusable — a plan, a route, an abstention, a corrective retry. **Not a cheaper-model fallback — there is no such path** | `supervisor_llm_failed_fallback_to_default`, `verifier_llm_failed_fallback`, `planner_plan_fallback_to_query`, `synthesizer_retrying_malformed_response` | **yes** — `research_degradations_total{rung="model_fallback"}`, by `component` — `planner`, `supervisor`, `verifier`, `synthesizer` (CAP-08) | no |
| **6. Bounded queue** | `bounded_queue` | Work waits behind `API_MAX_CONCURRENT_JOBS`; `/readyz` returns 503 so an orchestrator can drain | `research_queue_depth`, `research_queue_saturation_ratio`, `research_job_queue_wait_seconds` | **yes**, on its own instruments — deliberately not also on the degradation counter | no, but the wait is real |
| **6b. Weakened guarantee** | `weakened_guarantee` | The Redis rate limiter fails open to a per-worker fallback, so the fleet-wide cap becomes N × the configured limit | `resilience_degraded` with `component`, `reason` | **yes** — `research_degradations_total{rung="weakened_guarantee"}`, alongside the in-process counter and the log line (ADR 0068, ADR 0081) | no |
| **7. Honest refusal** | `refusal` | 429 from the rate limiter; 503 from readiness; a cost ceiling refusing or closing politely | `rate_limit_rejections_total`, `research_jobs_total{error_type="cost_budget_exceeded"}`, `{status="degraded_close"}`, `{error_type="session_cost_cap_refused"}` | **yes**, on its own instruments — deliberately not also on the degradation counter | **yes** — this is the one rung that is honest by construction |

### Read that table's fifth column

**Every rung on this ladder is on a metric**, where two were when this
page was written. Six of them are on `research_degradations_total`
(ADR 0081, then CAP-08); the other two were always instrumented on
counters of their own, and are excluded from this one deliberately —
see below.

It got there in two steps, and the second one is the part worth keeping
on the page. ADR 0081 built the counter and reached five rungs. The
remaining three — 2, 3 and 5 — stayed log-only for a fence rather than
for a design: every one of their call sites lives in `src/agents/`,
which belonged to another lane, and the work order declined to cross
rather than take them. What made that a deferral instead of a
disappearance was that
[`tests/test_degradation_ladder.py`](../tests/test_degradation_ladder.py)
named all three with their owning file and lane, and asserted the set in
**both** directions. So when CAP-08 wired the nine call sites, the suite
went red on the same commit and the failure message said which column of
this table to correct. The gap closed itself, which is what that
declaration is for; it is empty now and kept, because it is the shape
the next unmeasured rung gets declared in.

The rungs are counted at different granularities, and the table says
which. Rung 3 counts **per paper**, at the same granularity
`paper_cache` already counts at, because the run-level WARNING fires
only past `ABSTRACT_ONLY_WARN_THRESHOLD` and a rung counted only when it
is loud is a lower bound again. Rung 5 counts once per substitution:
the supervisor's three fallback branches converge on one function and
are counted there, so three distinct log events describe one event and
one number counts it.

### Why rungs 6 and 7 are not on the degradation counter too

They already have counters, and a second counter at a site that already
has one can disagree with the first about a single event —
`src/observability/metrics.py` declines to instrument the semaphore for
exactly that reason. The cost is that a quality query is a sum over
three instruments rather than one, which §3's Quality row writes out.

### Row 3 is the named failure

`02-STANDARDS.md` §5.3 predicts a system in which degradation is tallied
and logged and never reaches the user. The reader's abstract-only
fallback is that system: the report ships, the job-success SLI stays
green, `research_job_duration_seconds` *improves* because reading an
abstract is faster than reading a paper, and nobody is told that the
analysis was made from abstracts.

Fixing it means disclosing the degradation in the report itself, which
is a product change and not this document's. What this document can do
is refuse to let it be invisible, which is why it is row 3 of a table
rather than a line in a log nobody reads — and since CAP-08 it is also
a number: `research_degradations_total{rung="partial_results",
component="reader"}`, one per paper. The **User told?** column on that
row still says **no**, and it is the last one that does for a reason
this page can act on. Measured and undisclosed is a strictly better
position than unmeasured and undisclosed, and it is not the finished
one.

## 6. The runbooks

[`runbooks/README.md`](runbooks/README.md) is the index. One page per
incident the instruments make visible; each names the signal, the first
three commands, the containment action and the rollback.

| Runbook | For |
|---|---|
| [model-provider-outage](runbooks/model-provider-outage.md) | The Anthropic API failing, slow, or refusing the credential |
| [redis-loss](runbooks/redis-loss.md) | Jobs, events, leases and rate-limit counters unreachable |
| [postgres-loss](runbooks/postgres-loss.md) | Checkpoints, conversations, profiles and caches unreachable |
| [cost-cap-storm](runbooks/cost-cap-storm.md) | Runs repeatedly hitting their spend ceilings |
| [queue-saturation](runbooks/queue-saturation.md) | Every concurrency permit held, or leaked |
| [poison-job](runbooks/poison-job.md) | A job that reliably kills the worker that takes it |
| [injection-alarm](runbooks/injection-alarm.md) | Ingested content that may be steering the loop |
| [pilot](runbooks/pilot.md) | Not an incident — the bounded-pilot procedure |

The alert rules that fire them ship as reviewable files under
[`deploy/observability/`](../deploy/observability/README.md) and are
**not** wired into the default stack. Standing up a collector costs
money and is the owner's decision.

## 7. What is not measurable today

NIST AI RMF **MS-1.1-009** explicitly sanctions recording a risk you
cannot measure, with the reason why. These are those, each with the one
instrument that would close it.

1. ~~**The quality SLI has no instrument for most of the ladder.**~~
   **Closed — by WO-D5 (ADR 0081) and CAP-08 together.**
   `research_degradations_total{rung,component}` exists, is bumped from
   `record_degradation` and from the cache, streaming and rate-limiter
   rungs directly, and §3 carries a Quality row computed from it. The
   attributes are a closed set for the third time in this repository
   (`ERROR_CODES`, `KNOWN_EVENTS`, and now `DEGRADATION_RUNGS`), because
   an open string used as a metric attribute is unbounded cardinality.
   CAP-08 wired the last three rungs — §5's 2, 3 and 5, nine call sites
   in `src/agents/` — so the numerator now covers the whole published
   ladder and the SLI is no longer a lower bound by construction.

   Two things are worth keeping on the page rather than deleting with
   the entry. The instrument was specified here as `{component,reason}`
   and shipped as `{rung,component}`: `reason` stays on the log line,
   because the metric's job is "how much, at which rung" and the log's
   is "why" — the same split `record_rate_limit_rejection` makes for
   `key_id`. And the way the last three rungs closed is the part worth
   copying: `tests/test_degradation_ladder.py` named them with their
   owning lane and asserted the set in both directions, so the wiring
   turned the suite red and the failure said which column of §5 to
   correct. This entry did not shrink because somebody remembered it.
   Item 6 below is what still bounds the number: an eval campaign
   installs no meter provider, so a rung taken under `make eval` is a
   real degradation counted nowhere.

2. **Cost per job cannot be computed.** `03-ARCHITECTURE.md` §5.4 lists
   "p95 `cost_usd` by kind" as an SLI, and no instrument supports it:
   `llm_cost_usd_total` is a process-wide counter by model, and
   `record_job_terminal` is not passed the job's cost. **Needed:** a
   `research_job_cost_usd{kind,status}` histogram, recorded at the same
   terminal choke point that already records duration and queue wait.
   Until it exists, the spend row in §3 measures **cap trips**, which is
   a different and much coarser question, and that substitution is
   stated in the table rather than hidden.

3. **Injection containment has no runtime measurement.** §3 says so in
   its own table. The offline gate measures a fixed corpus, which is a
   property of the corpus as much as of the system. **Needed:** a
   counter on the sanitizers in `src/security/prompt_isolation.py` —
   they already know when they blanked a control field, and today they
   return silently.

4. **Connection-pool saturation is invisible.** The Postgres pool can be
   exhausted while `SELECT 1` still passes, so `/readyz` reports ready
   and every job stalls. **Needed:** pool-waiter and pool-size gauges.

5. **`kind` is `"unknown"` on redriver terminals.** The redriver has
   `job.kind` in hand and does not pass it, so orphan and dead-letter
   rates cannot be cut by workflow. A test pins the current value so the
   fix is visible when it lands.

6. **Metrics exist only inside API workers.** `configure_metrics()` has
   one caller — the API lifespan — so `make run` and `make eval` install
   no meter provider and every record helper returns on its `None`
   check. Deliberate for the server-shaped instruments; it means an eval
   campaign contributes nothing to any SLI on this page.

7. **Nothing polls `/readyz`.** The shipped compose healthcheck polls
   `/healthz`, which is always 200 by design. So the readiness signal
   exists, is correct, and is read by nobody on the default deployment —
   which is why §3's availability SLI is built on request outcomes
   rather than on probe results.

8. ~~**The sampling and content-capture flags are not in
   `Settings`.**~~ **Closed by WO-B4.** `TRACE_SAMPLE_RATIO` is
   `Settings.trace_sample_ratio`, a float bounded to `[0.0, 1.0]`; the
   two content-capture variables are the validation aliases of
   `Settings.log_capture_user_content`. Both environment variables
   still work unchanged and both defaults are unchanged. Why it
   outlived two waves is kept on the page, because it was a planning
   error rather than a design choice: `docs/observability.md` named
   WO-A12 as the work order that would fold them in, and WO-A12's
   owned-file list did not include `src/config.py`, which two other
   work orders edited in the same phase.

9. **The quality SLI is a rate, not a proportion.**
   `research_degradations_total` counts *rungs taken*, and one job can
   take several, so the §3 row divides rungs by jobs and gets
   degradations per job rather than the good-events / valid-events form
   every other row on that table uses. It is comparable with itself
   over time, which is what a burn rate needs, and it is *not*
   comparable with the other SLIs. **Needed:** a per-job degraded flag
   written at the terminal choke point that already records duration
   and queue wait — one boolean on the job record, so
   `research_jobs_total` could carry a `degraded` attribute and the
   proportion would fall out of the counter that already exists. That
   is a change to the job record rather than to the instrument, which
   is why ADR 0081 did not make it.

None of these is a reason to withhold the objectives in §3. They are the
reason those objectives are marked **declared, not earned** — a
distinction this page would rather make loudly than quietly.
