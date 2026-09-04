# 0064. One error taxonomy, one envelope, and boundary typing

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: kudratsingh
- **Follows**: [ADR 0025](0025-fastapi-async-job-model.md) (the job model and
  `job.error`), [ADR 0033](0033-safety-hardening-bundle.md) (API-key auth and
  the 429 body), [ADR 0036](0036-per-principal-store-scoping.md) (404-not-403
  on an ownership mismatch), [ADR 0049](0049-otel-metrics.md)
  (`research_jobs_total{error_type}`), [ADR 0051](0051-llm-cost-enforcement-and-visibility.md)
  (`CostBudgetExceeded` and the partial report), [ADR 0057](0057-job-kinds-and-awaiting-learner.md)
  (`session_turn_timeout`), [ADR 0062](0062-session-specific-cost-ceilings.md)
  (`session_cost_cap_refused`)
- **Implements**: WO-A01 in `planning/08-assurance/04-WORK-ORDERS.md`

## Context

A read-only recon pass over `main` measured four separate facts that turn out
to be one fact seen from four directions.

**There were no exception handlers at all.** `create_app` registered none;
`grep exception_handler src/` returned nothing. An unhandled exception became
an untyped Starlette 500 with no structured body and **no ERROR log on that
path** — the failure mode where a client sees a blank 500 and the operator
sees nothing.

**Raw exception text reached clients.** `src/api/runner.py` set
`job.error = f"{type(exc).__name__}: {exc}"`, surfaced through
`schemas.py` → `GET /research/{id}` and through the terminal SSE frame.
psycopg's message embeds the host, the port and the database user; redis and
httpx messages embed URLs. Length was unbounded.

**`error_type` was an internal class name.** The same
`type(exc).__name__` was simultaneously an API field, a job record field and
a metric attribute (`research_jobs_total{error_type}`). Renaming a class
silently broke client branching *and* forked a metric series — and any
exception class from any dependency could become a new attribute value, which
is unbounded cardinality on a counter.

**Three inconsistent error shapes shipped**: `{"detail": "job_not_found"}`,
the structured 429 object, and FastAPI's validation array — plus, since there
were no handlers, a fourth shape (nothing at all) for the unanticipated case.

Underneath all four: thirteen exception classes with no common ancestor,
against 122 `raise ValueError`. A caller could not write `except AppError`,
and nothing carried a stable machine-readable name.

Three later work orders in the same phase consume `AppError.code` — the log
contract, the fault-injection tier and the RED metrics all key on it — so
this had to land first, and it had to land as an identity rather than as
plumbing.

## Decision

### 1. `AppError` in `src/errors.py`, with four attributes

```python
class AppError(Exception):
    code: str             # stable, snake_case; part of the public contract
    http_status: int      # boundary mapping
    retryable: bool       # may the caller retry this exact request?
    public_message: str   # safe for a client; never upstream text
```

Instances additionally carry `log_detail` (the human-readable, possibly
sensitive explanation — it is `str(exc)` and reaches the log, never a
client), an optional per-instance `public_message`, an optional `wire_detail`
(see §3), and optional response `headers`.

The eleven families of `03-ARCHITECTURE.md` §2.1 are implemented as **base
classes**, because a family's content is exactly its HTTP status and its
retryability. `AppError` itself is the `internal_*` family: an error with no
more specific class is by definition unanticipated, so the base carries
`internal_unexpected` and a 500 and there is no separate `InternalError`
class to forget about.

`ERROR_CODES` is a closed `frozenset`. `__init_subclass__` refuses a
duplicate code at **import time**, and `tests/test_errors.py` ties the
declared set to the registry in both directions.

`JOB_ERROR_TYPES` is the subset a *run* can carry, as opposed to the codes a
route answers with. It exists because the frontend's failure-copy dictionary
must have a sentence for every value a job can show a reader, and demanding
one for `job_not_found` — which a run can never become — would be inventing
copy for an unreachable state.

### 2. Codes already on the wire keep their spelling

The families are prefixes for every *new* code (`upstream_arxiv`,
`not_found_papers`, `internal_unexpected`, `cancelled_job`). Codes that were
already published keep theirs: `job_not_found`, not `not_found_job`;
`timeout`, not `timeout_job`.

This is a deliberate deviation from the architecture page's illustrative
examples, and the reason is the thing this ADR is about. Those strings are
recorded in `web/contract/fixtures/*.json`, tabulated in
`docs/revamp/04-ARCHITECTURE.md` §3.4, named in `src/config.py`'s own setting
descriptions (`error_type=hitl_timeout`, `error_type=orphaned`), and three of
them are live `research_jobs_total{error_type}` series. Renaming a published
identifier for a cosmetic prefix is precisely the harm the taxonomy exists to
prevent, and it would have made a *must-not-touch* file
(`src/config.py`) wrong. A client that wants the family reads the HTTP status
and `retryable`.

### 3. One envelope, additive over `detail`

```json
{"error": {"code", "message", "retryable", "request_id"}, "detail": "<code>"}
```

Four handlers on `create_app`: `AppError`, `HTTPException` (registered on
Starlette's, so FastAPI's subclass is covered too), `RequestValidationError`,
and bare `Exception`. All four produce the envelope. Client errors log at
WARNING; 5xx logs at ERROR with `exc_info`.

`detail` is **retained, not replaced**, and this is load-bearing rather than
polite. `web/lib/api/errors.ts` reads structure out of it in three places:
`limit_per_hour` from the 429 object, the `[{loc, msg, type}]` array that
renders per-field form errors, and the `(status=running)` suffix it regexes
out to say "this action is no longer available: the run is still running".
Replacing any of those with a bare code would have passed every Python test
and silently downgraded three live surfaces to generic copy. So `detail`
defaults to the code and carries the legacy shape verbatim in exactly those
cases; the same facts are additionally in `error.message` and `error.code`
for a client that reads the envelope.

The `HTTPException` handler answers with the exception's **own** status, not
the family's. A 405 from the router borrows `invalid_request` for its code
and stays a 405.

### 4. Boundary typing, not a `ValueError` migration

Every `raise` in `src/api/routes.py`, `src/api/auth.py` and
`src/api/sessions.py` is an `AppError`. The runner's terminal paths and the
metric attribute draw from `ERROR_CODES`. The 122 ad-hoc `raise ValueError`
sites are **not** converted: internal invariants stay `ValueError`, and
converting them all would be a large, low-value, unreviewable diff.

Reachability was determined structurally, not by inspection:
`tests/test_errors.py::TestBoundaryTyping` parses the three boundary modules,
resolves every `raise` to a class, and fails if any is not an `AppError` with
a registered code — so the property holds for the paths no test happens to
walk, which is the set that matters.

### 5. `job.error` is the code

Every terminal path in the runner now writes the code into both `job.error`
and `job.error_type`. The sentence each one used to write —
`"Workflow exceeded 1s timeout"`, `"pending_review exceeded 1800s"`, a
`CostBudgetExceeded` message — moves into the log line beside it as
`error_detail`, with the `request_id`. One field, one contract: half a field
being a code and half being prose is how clients end up parsing prose.

The one exception is `cost_cap_message`, which keeps its own separate field:
it is deliberate learner-facing copy (ADR 0062), not an error string.

### 6. Four re-parented classes keep a `ValueError` mixin

`ProvenanceError`, `AnonymousPrincipalError`, `ProgressEventRejected` and
`ContentValidationError` become `(SomeAppError, ValueError)`. The mixin is
load-bearing, not conservatism:

- `src/api/routes.py`'s profile writer catches `ValueError` to turn a
  domain-rule breach into a 422;
- `src/learning/progress_store.py` and `src/learning/profile_store.py` catch
  `ValueError` around `datetime` parsing and re-raise as their own class;
- **Pydantic only converts a validator's `ValueError`** into a
  `ValidationError`, and `src/content/schema.py` unwraps exactly that to
  recover the rule id.

Dropping the mixin would have turned three 422s into 500s and broken one
manifest parser, all silently.

## Alternatives considered

- **An exception class per HTTP status.** Rejected in
  `03-ARCHITECTURE.md` §2.1 and not revisited: it puts transport concerns in
  domain modules and produces classes with no domain meaning.
- **Rename every code to its family prefix.** Rejected — see §2. It breaks
  recorded contract fixtures this work order cannot re-record, forks live
  metric series, and falsifies `src/config.py`, a file this work order must
  not touch.
- **Replace `detail` with the code everywhere.** Rejected — see §3. It is the
  change that looks cleanest and costs the most, because the damage is
  invisible from the Python side.
- **Convert the 122 `ValueError` sites.** Rejected: large, low-value, and it
  would make this PR unreviewable. Boundary typing gets the property that
  matters at a fraction of the diff.
- **Declare the error responses in the OpenAPI document.** Rejected for now:
  `tests/test_contract_openapi_snapshot.py` pins that no route documents
  401/404/409/429/502/503, and the frontend's hand-written overlay exists
  because of that gap. Closing it is a contract change with a frontend half,
  and belongs in its own work order. The snapshot is byte-identical after
  this change.

## Consequences

- **Positive.** A client can branch on `error.code` for the first time. The
  metric attribute is bounded. An unhandled exception now logs, with a
  `request_id` that is also in the client's hands. Three inconsistent shapes
  became one, additively — no client had to change. Driver messages, DSNs and
  class names no longer leave the process.
- **Negative.** Two response fields (`error`, `job.error`) now say the same
  word, which reads redundantly until the legacy `detail` is retired. A
  reader who used to see `"ValueError: corrupt checkpoint blob"` in the UI's
  diagnostics disclosure now sees `internal_unexpected` and must look up the
  `request_id` — better for privacy, worse for a developer poking at a local
  stack, and the reason `error_detail` is logged rather than dropped.
- **Follow-ups.**
  - `web/contract/fixtures/*.json` are still accurate for `detail` but do not
    yet carry the `error` object. They are recorded against a live server by
    `web/contract/record.sh` and should be re-recorded.
  - `docs/revamp/04-ARCHITECTURE.md` §3.4's error-shape table predates the
    envelope and now describes half of it.
  - The SLO half of `docs/reliability.md`.

## Seams left open

Two, both deliberate, both recorded so a later work order absorbs them rather
than colliding with them.

**`request_id` has no middleware.** There is no request-id infrastructure in
the process; a later work order in this phase adds the middleware and the
observability context. Until then `src/api/app.py::_request_id` mints one at
the moment of failure and reads `request.state.request_id` first — so when
the middleware lands, the function needs no edit and the locally-minted
fallback simply stops being reached. Building the middleware here would have
produced two competing identities.

**Two exception classes are mapped at the boundary rather than re-parented.**
`src/cancellation.py::JobCancelledError` and
`src/observability/costs.py::CostBudgetExceeded` live in files outside this
work order's ownership (`src/observability/**` is owned by a concurrent work
order). `src/api/runner.py::_as_app_error` maps both to `cancelled_job` and
`cost_budget_exceeded`, which is behaviourally identical for everything
downstream — the code, the job field and the metric attribute are the same
either way. A later work order that owns those files can re-parent them and
delete two branches; `tests/test_errors.py` asserts the mapping so the
deletion cannot silently change the codes.
