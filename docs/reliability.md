# Reliability

How this service fails, and what a client is entitled to assume about it.

> This page currently documents the **error contract** only. The service
> level objectives, the error budget and the runbook index are added by a
> later work order in the same assurance phase; until they land, this
> page describes exactly one thing and says so rather than implying a
> completeness it does not have.

## The error contract

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
