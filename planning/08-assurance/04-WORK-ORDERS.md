# Phase A work orders

Status: **READY FOR EXECUTION**

Sixteen work orders in three waves. Each is one branch, one PR, one
reviewable diff, executed by a dedicated agent in its own worktree.

> **Revised 2026-09-04** after the standards research pass returned. WO-A04
> swapped its circuit breaker for a retry token bucket, WO-A09 and WO-A11
> gained the pairing and gating designs their evidence actually supports, and
> WO-A16 was added because the arXiv domain permits deterministic groundedness
> measurement. [`02-STANDARDS.md`](02-STANDARDS.md) carries the reasoning; the
> corrections were material, not cosmetic.

## 0. Conventions every work order inherits

Read this section before reading your work order. It is not boilerplate; it
is the set of mistakes this repository has already made once.

### 0.1 Non-negotiable

1. **Zero model spend.** `ANTHROPIC_API_KEY=local-preview-disabled` in every
   command you run. If a change would make any gate require a paid call, stop
   and report instead of implementing it.
2. **You do not merge.** Open the PR, report, stop. The coordinator merges.
3. **Do not touch another work order's owned files.** The `Owns` list is
   exhaustive. If you believe you need a file owned by someone else, stop and
   report — that is a planning bug, and working around it silently creates a
   merge conflict for a peer.
4. **Do not write under `docs/agent-engineering/`, and do not modify
   `planning/README.md`.** A second session owns that program.
5. **No new dependency** unless your work order says so. Exactly one work
   order (WO-A02) moves `requirements-lock.txt`.
6. **No secrets**, no `.env` values, no real API keys in code, tests,
   fixtures, or docs.
7. **Do not re-enable `nightly-eval` or `nightly-lighthouse`.**

### 0.2 The local gate, run before you open the PR

```bash
OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false ANTHROPIC_API_KEY=local-preview-disabled \
  .venv/bin/python -m pytest -m "not e2e" -q
.venv/bin/python -m mypy src/
.venv/bin/ruff check src/ tests/
```

Baseline to beat: **2042 passed, 52 skipped**. A drop in passed count without
an explanation in your PR body is a failure, not a detail.

If your diff touches anything under `web/`, you must additionally run
`npm test -- --run` in `web/`. This is not optional and it is not covered by
typecheck+lint: a comment-only web change has already failed CI in this
repository because `web/tests/tokens.test.ts` reads `#159` as a colour
literal. **Never write `#<number>` in a `web/` file** — write `PR 159`.

### 0.3 House style

- Comments explain **why**, not what. Match the density of the file you are
  editing; this codebase carries long rationale comments at decision points
  and that is deliberate.
- Every non-trivial design choice gets an ADR. Your work order pre-assigns
  your ADR number so concurrent agents cannot collide. Use
  `docs/decisions/TEMPLATE.md`.
- Doc drift is a bug: code and docs land in the same PR.
- Tests are named as sentences describing the behaviour, matching the
  surrounding files.
- Type annotations are mandatory (`mypy --strict` runs on `src/`).

### 0.4 Your PR body must state

- what you ran and the exact result lines (test counts, mypy, ruff);
- every acceptance criterion with a ✅/❌ and the evidence for it;
- anything you found that is out of scope, as a numbered list — do not fix it;
- the trailer:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

### 0.5 Config anchors (collision avoidance)

`src/config.py` is edited by two work orders in the same wave. To keep the
merge clean they insert in different regions, hundreds of lines apart:

- **WO-A04** inserts a `# ------ Resilience (Phase A, ADR 0068) ---` section
  immediately **after** the existing `# ------ HTTP retry` block (~line 147).
- **WO-A08** inserts a `# ------ Evaluation integrity (Phase A, ADR 0070) ---`
  section immediately **after** the existing `# ------ Telemetry` block
  (~line 585).

Neither may append at the end of the class.

## 1. Dependency graph

```text
wave 1   A01 errors ──┬─────────────► A04 resilience ──► A09* (stats, w3)
                      ├─────────────► A06 fault
                      └─────────────► A10 middleware (w3)
         A02 harness ─┬─────────────► A05 property
                      ├─────────────► A06 fault
                      ├─────────────► A15 e2e tier
                      └─────────────► A11 safety (w3)
         A03 context ───────────────► A07 telemetry ──► A10, A12 (w3)

wave 2   A04  A05  A06  A07  A08  A15
wave 3   A09  A10  A11  A12  A16  A13 (CI, last)  A14 (evidence, last)
```

`A13` and `A14` are last by construction: A13 wires the new tiers into CI and
must see them all merged; A14 assembles evidence from what actually landed.

## 2. Summary

| WO | Title | Wave | ADR | Pillar |
|---|---|---|---|---|
| A01 | Error taxonomy, envelope, boundary typing | 1 | 0064 | error handling |
| A02 | The harness that cannot lie + coverage floor | 1 | 0065 | testing |
| A03 | Observability context and the log contract | 1 | 0067 | logging |
| A04 | Resilience policy: retry budget, timeouts, dead-letter | 2 | 0068 | error handling |
| A05 | Property-based tests | 2 | 0069 | testing |
| A06 | Fault-injection tier | 2 | — | testing / error handling |
| A07 | GenAI conventions, trace continuity, RED/USE | 2 | 0066 | observability |
| A08 | Eval integrity: pinned judges, versioned rubrics, provenance | 2 | 0070 | evaluation |
| A15 | The end-to-end tier | 2 | — | testing |
| A09 | Eval statistics and aggregate gates | 3 | 0071 | evaluation |
| A10 | API middleware, request ids, readiness split | 3 | — | observability |
| A11 | Adversarial safety suite and the safety gate | 3 | 0072 | evaluation / safety |
| A12 | Operability: SLOs, runbooks, alerts, dashboard | 3 | 0073 | observability |
| A13 | CI wiring for the new tiers | 3 | — | all |
| A14 | Assurance evidence pack and framework mapping | 3 | — | compliance |
| A16 | Deterministic groundedness — hallucination measurement with no judge | 3 | 0074 | evaluation |

---

# Wave 1 — foundations

## WO-A01 — Error taxonomy, envelope, and boundary typing

**ADR:** 0064. **Branch:** `assurance/wo-a01-errors`.

### Objective

Give every failure that can reach a client, a job record, or a metric a
stable machine-readable identity, and stop leaking raw exception text out of
the process. Today there are zero FastAPI exception handlers, three
inconsistent error shapes, and `job.error = f"{type(exc).__name__}: {exc}"`
handing psycopg and httpx messages — which embed DSNs, hostnames and paths —
straight to API clients. Three later work orders consume `AppError.code`, so
this lands first.

### Owns

- `src/errors.py` (new)
- `src/api/app.py` — **exception handlers only**; do not add middleware (A10)
- `src/api/routes.py`, `src/api/schemas.py`, `src/api/runner.py`,
  `src/api/auth.py`, `src/api/sessions.py`
- `src/agents/*.py`, `src/tools/*.py`, `src/learning/*.py`, `src/content/*.py`
  — **only** to re-parent the 13 existing custom exception classes
- `tests/test_errors.py`, `tests/test_api_error_envelope.py` (new), plus
  existing tests that assert on the old error shapes
- `web/contract/openapi.json` (regenerate only)
- `docs/reliability.md` (new — create the file with the **error contract**
  section only; A12 adds the SLO section later)
- `docs/decisions/0064-error-taxonomy-and-envelope.md`

### Must not touch

`src/config.py`, `src/observability/**`, `tests/conftest.py`, `pyproject.toml`,
`.github/workflows/**`, any `web/` file other than the regenerated
`openapi.json`.

### Deliverables

1. `src/errors.py` defining `AppError` with `code: str`, `http_status: int`,
   `retryable: bool`, `public_message: str`, and the code families in
   `03-ARCHITECTURE.md` §2.1. `ERROR_CODES: frozenset[str]` is the closed set;
   a test asserts every `AppError` subclass's code is in it and that no two
   subclasses share a code.
2. The 13 existing custom exceptions (`JobCancelledError`,
   `CostBudgetExceeded`, `HitlTimeoutError`, `HitlCancelledError`,
   `SessionTurnTimeoutError`, `ArxivUnavailableError`,
   `AllPaperAnalysesFailedError`, `NoPapersFoundError`,
   `SynthesizerOutputError`, `ProvenanceError`, `AnonymousPrincipalError`,
   `ProgressEventRejected`, `ContentValidationError`) re-parented onto
   `AppError`, keeping their names and their current `except` semantics.
   Where one currently inherits `ValueError` and a caller relies on that,
   keep the `ValueError` mixin rather than breaking the caller — and say so
   in a comment.
3. **Boundary typing.** Every `raise` reachable from a route handler, the job
   runner's terminal path, or a metric attribute is an `AppError`. Internal
   invariant `ValueError`s stay as they are — this is a deliberate scope
   limit (see §2.1 of the architecture), and your PR body must state how you
   determined reachability.
4. Four handlers registered in `create_app`: `AppError`, `HTTPException`,
   `RequestValidationError`, `Exception`. All four produce the envelope in
   §2.2 and log at ERROR (`Exception`) or WARNING (client errors) with
   `exc_info`. The bare-`Exception` handler is the one that must exist:
   today an unhandled error produces an untyped Starlette 500 with no log on
   that path.
5. `job.error` becomes the stable `code`; the human-readable detail goes to
   the log, never to the client. `error_type` (metric attribute and job
   field) is drawn from `ERROR_CODES`.
6. `detail` is retained alongside the envelope for compatibility with the
   current web client, carrying the code string.
7. `web/contract/openapi.json` regenerated so
   `tests/test_contract_openapi_snapshot.py` passes. Find the regeneration
   path from that test — do not hand-edit the JSON.

### Acceptance

- `pytest -m "not e2e" -q` ≥ 2042 passed; mypy strict clean; ruff clean.
- A test proves an unhandled internal exception yields HTTP 500 with the
  envelope, a stable `internal_unexpected` code, an ERROR log, and **no**
  upstream text in the body.
- A test enumerates the route handlers and asserts every declared error
  response uses a code from `ERROR_CODES`.
- A test proves `job.error` never contains `:` -joined exception text for a
  simulated psycopg failure.
- `npm test -- --run` green in `web/` if `openapi.json` changed.

### Rollback

Revert the PR. Nothing else depends on it until A04/A06/A10 merge.

### Traps

- The web client reads `detail`. Check `web/lib/api/` before changing shapes.
- `test_contract_sse_events.py` pins the SSE event set by regex over emit
  sites; a changed terminal frame shape can trip it.
- Do not "improve" the 122 unrelated `ValueError` sites. That is explicitly
  out of scope and would make this PR unreviewable.

## WO-A02 — The harness that cannot lie, and a coverage floor

**ADR:** 0065. **Branch:** `assurance/wo-a02-harness`.

### Objective

The suite currently has no `tests/conftest.py` at all. As a direct
consequence it can read a developer's `.env`, reach the network, construct a
real Anthropic client if a monkeypatch is misplaced, and run 38 of 98 files
outside every marker filter — while `make test` reports green. This work
order makes those failures impossible rather than unlikely, and adds the only
missing quantitative floor: Python coverage, which is measured on the web
half and not on the Python half.

This work order is also the phase's **single dependency diff**. Four dev
packages are added here so no other work order touches the lock.

### Owns

- `tests/conftest.py` (new)
- `pyproject.toml` (`[project.optional-dependencies].dev`, `[tool.pytest]`,
  new `[tool.coverage.*]`)
- `requirements-lock.txt`, `requirements-runtime-lock.txt`
- `Makefile`
- `docs/testing.md`
- Marker additions across existing `tests/test_*.py` files — **markers only**,
  no behavioural edits to existing tests
- `docs/decisions/0065-test-isolation-and-coverage-floor.md`

### Must not touch

Anything under `src/`.

### Deliverables

1. **`tests/conftest.py`** with autouse fixtures, in this order:
   - **env isolation** — the developer `.env` cannot influence a test;
     `Settings()` constructed in a test sees a declared, deterministic
     environment. (`src/config.py:53` sets `env_file=".env"` and 30+ files
     construct a bare `Settings()`.)
   - **network guard** — non-loopback `socket.connect` raises with a message
     naming the test; opt out via a new `network` marker (expected users:
     none).
   - **spend guard** — `src.llm._get_client` raises unless a fake is
     installed; make the existing per-module monkeypatch style keep working.
   - **determinism** — seeded `random`, fixed `PYTHONHASHSEED`, and a
     `frozen_clock` fixture offered to the ~9 files that hand-patch time (do
     not rewrite them in this PR).
2. **Strictness**: `--strict-markers`, `--strict-config`, `xfail_strict`,
   per-test timeout via `pytest-timeout` (choose a ceiling well above the
   slowest current test and say why), and `filterwarnings = ["error", ...]`
   keeping the two documented C-extension ignores. **Known trap:** a local run
   surfaces a Starlette `HTTP_422_UNPROCESSABLE_ENTITY` deprecation from
   FastAPI's own routing code — an ignore for that one is acceptable, with a
   comment recording that it is upstream and what would let us drop it.
3. **Markers, two axes** (`03-ARCHITECTURE.md` §3.2): tier
   (`unit`/`integration`/`e2e`, exactly one, enforced by a test that walks
   `tests/` and fails on a file with none) and purpose (`security`,
   `property`, `fault`, `contract`, `network`). Tag the 38 unmarked files.
   Classify honestly — a test that starts an ASGI app is `integration`.
4. **Coverage**: `pytest-cov` with `branch = true` over `src/`. Set
   `fail_under` to the **measured** value rounded down to the nearest whole
   percent, plus per-package floors for `src/api`, `src/agents`,
   `src/security`, `src/eval`. Record the measured numbers in
   `docs/testing.md`. State the ratchet rule: floors only go up, and a PR that
   lowers one must say why in its body.
5. **Dependencies** added to `dev` and to both locks: `pytest-cov`,
   `coverage`, `pytest-timeout`, `hypothesis`. Follow ADR 0045's procedure in
   `docs/development.md`; then `python -m pip check` and
   `python scripts/derive_runtime_lock.py --check` must both pass. `hypothesis`
   is added here but used by WO-A05.
6. **Makefile**: a `test-cov` target, and `test-security` / `test-property` /
   `test-fault` selectors. `make test` keeps its current meaning.
7. **`docs/testing.md`** updated: the two-axis marker model, the harness
   guarantees, the coverage policy and its numbers, and a correction of the
   stale collected-test count the file currently reports.

### Acceptance

- `pytest -m "not e2e" -q` ≥ 2042 passed with the guards active.
- A test proves the network guard fires on a non-loopback connect.
- A test proves `_get_client` raises without a fake.
- A test proves every test file carries exactly one tier marker.
- `pip check` and `derive_runtime_lock.py --check` both clean.
- `pytest --cov` reports ≥ the new `fail_under`, and the number appears in
  `docs/testing.md`.

### Rollback

Revert. A05/A06/A15/A11 depend on the markers and on `hypothesis`, so a
rollback after they merge requires reverting them first.

### Traps

- The local venv is Python 3.13 while `.python-version` and the lock are 3.14.
  Add pins that are valid for both; verify with `pip check` and by reading the
  wheel availability, not by assuming.
- Escalating warnings to errors can surface failures in dependencies. Fix ours,
  scope-ignore theirs with a reason, never blanket-ignore.
- Tagging 38 files is mechanical but not thoughtless: an incorrectly tagged
  `unit` test that touches Redis will start failing in a filtered run.

## WO-A03 — Observability context and the log contract

**ADR:** 0067. **Branch:** `assurance/wo-a03-log-context`.

### Objective

There is exactly one ContextVar in the logging layer (`_run_id`) and no
request id, trace id, span id, principal, worker id, service name or version
anywhere in a log record. At the same time the formatter merges **every**
`extra` field verbatim with no allowlist and no size cap, and callers log raw
user queries and, on a store failure, whole report bodies. This work order
makes a log line joinable and bounded.

### Owns

- `src/observability/context.py` (new)
- `src/observability/logging.py`
- `src/observability/__init__.py` (exports only)
- `tests/test_log_redaction.py`, `tests/test_health_logging.py`,
  `tests/test_log_contract.py` (new)
- `docs/observability.md` (new)
- `docs/decisions/0067-correlation-context-and-log-contract.md`

### Must not touch

`src/observability/metrics.py`, `src/observability/tracing.py` (A07),
`src/api/**` (A01 this wave, A10 later), `src/config.py`.

### Deliverables

1. `RequestContext` — a frozen dataclass in one ContextVar carrying
   `run_id`, `job_id`, `request_id`, `job_kind`, `principal_hash`,
   `worker_id`; `service` and `version` resolved once at import from existing
   settings and package metadata. Bind/get/clear helpers, and propagation
   across the thread-pool boundary, extending the mechanism
   `propagate_run_context` already uses.
2. `principal_hash` is a salted hash. Never log the key id — the metrics layer
   already made that call deliberately and this must not undo it.
3. Formatter emits the context fields, plus `trace_id`/`span_id` **read from
   the active OTel span if one exists** (import the API only; do not create
   spans — that is A07).
4. **Allowlist + size cap** for `extra`. Unknown keys are dropped and counted
   rather than merged; oversized values are truncated with a marker. The
   allowlist lives beside the closed event-name set.
5. **Closed event-name set** with a test, mirroring the error-code discipline.
   The ~31 existing event names are the starting set.
6. **User-content redaction by default**: query text, report bodies and
   learner text are redacted unless an explicit opt-in setting is set — model
   the flag on the GenAI content-capture convention
   (`02-STANDARDS.md` §1). Because you may not edit `src/config.py`, read the
   flag through an environment-backed helper in your own module and record in
   the ADR that A12 folds it into `Settings` later.
7. Redaction extended beyond `redact_url`: bearer tokens, `sk-`-style keys,
   email addresses, and long base64-ish blobs. Keep `redact_url`'s existing
   property — the secret never appears in the output — and add a test per rule.

### Acceptance

- A test asserts a log line emitted inside a bound context carries `run_id`,
  `job_id`, `request_id` and `principal_hash`, and that `principal_hash` is not
  the key id.
- A test asserts an un-allowlisted `extra` key is dropped and counted.
- A test asserts a 100 KB value is truncated.
- A test asserts a report body passed as `extra` does not appear in output.
- Existing redaction tests still pass; new rules each have a test.
- mypy strict, ruff, full suite green.

### Rollback

Revert. A07 and A10 depend on `context.py`.

### Traps

- `propagate_run_context` is used by the runner's thread pools; changing its
  signature breaks callers you do not own. Extend, do not replace.
- uvicorn runs with `log_config=None`, so access lines arrive as unparsed
  text. Do **not** fix that here — it is A10's.

---

# Wave 2 — behaviour and instruments

Wave 2 starts only after A01, A02 and A03 are merged to `main`. Every wave-2
agent branches from the merged `main`, not from a wave-1 branch.

## WO-A04 — Resilience policy: retry budget, timeouts, dead-letter

**ADR:** 0068. **Branch:** `assurance/wo-a04-resilience`. **Depends:** A01.

### Objective

During an upstream outage every job pays its full retry envelope before
failing, and retries compound: the model SDK retries, `urllib3.Retry` retries,
and three hand-rolled loops retry — retry amplification is multiplicative, and
three retries at five levels is 243× load. The Redis client has no connect
or socket timeout, the rate limiter raises through an unguarded
`pipe.execute()` when Redis is down, the arXiv timeout is a hardcoded literal
outside `Settings`, the HTTP retry budget is never clamped against the job
budget the way the LLM envelope is, the redriver can requeue a poison job
forever, and the search pacing loop sleeps three seconds per query without a
cancellation check.

### Owns

- `src/resilience.py` (new)
- `src/config.py` — **only** a new section inserted after the `HTTP retry`
  block (see §0.5)
- `src/tools/http_session.py`, `src/tools/arxiv_search.py`
- `src/api/redis_store.py`, `src/api/auth.py`, `src/api/redriver.py`
- `src/agents/search.py` — the pacing loop only
- `tests/test_resilience.py` (new) and the tests of the files above
- `docs/decisions/0068-resilience-policy.md`, `docs/architecture.md`
  (cross-cutting section)

### Deliverables

1. **A retry token bucket in `src/resilience.py` — not a circuit breaker.**
   A shared, refilling budget that throttles *retries* during an outage while
   leaving the success path unchanged. Read
   [`02-STANDARDS.md`](02-STANDARDS.md) §5.2 before you start: the choice is
   deliberate and contested (Nygard/Fowler favour breakers; AWS argues they
   introduce modal behaviour that is hard to test), and the reasoning is that
   the bucket is ~20 lines against the Redis that already exists, adds no
   second mode, and addresses the measured problem directly. **Do not
   implement a breaker.** If you conclude the bucket cannot work here, stop
   and report rather than substituting one.
2. **Consolidate retries to one owning level.** Decide which level owns retry
   for each dependency, disable it at the others, and write the decision down.
   This is worth more than any new mechanism. Note that the model client's SDK
   retry envelope (`src/llm.py:62-91`) is already clamped and is the reference
   implementation — prefer keeping it and removing duplication elsewhere.
3. **Full Jitter** on every backoff:
   `sleep = random(0, min(cap, base * 2**attempt))`.
4. Every timeout becomes a setting, including arXiv's hardcoded `30` — and each
   one is justified by a **false-timeout rate** (the percentile you are willing
   to cut off), stated in a comment, rather than by a round number.
4. The HTTP retry budget gets the clamp treatment `src/llm.py:62-91` applies:
   bound `(retries+1) × timeout` against the job budget, and WARN when the
   clamp bites. Copy that code's shape deliberately; it is the reference.
5. Redis client: connect timeout, socket timeout, `health_check_interval`,
   and retry-on-timeout. The `wait_for` workaround at `app.py:435` may then be
   simplified — but `src/api/app.py` is not yours, so record it as a follow-up
   instead of editing it.
6. Rate limiter degrades to the in-memory backend on a Redis failure and
   increments a rejection/degradation counter, rather than raising. Fail-open
   vs fail-closed is a real decision: default to **degrade and serve**, and
   write the reasoning in the ADR.
7. Redriver: an attempt counter on the job record and a terminal dead-letter
   state after a configured number of requeues, so an enabled
   `job_redrive_requeue_pending` cannot loop forever.
8. `check_cancelled()` inside the `search.py` pacing loop.

### Acceptance

- Token-bucket unit tests: exhaustion, refill, and that an exhausted bucket
  fails fast with an `upstream_*` code instead of retrying.
- A test proves a healthy path is unchanged — the bucket is a pass-through
  when it is full.
- A test proves retries now happen at one level only for at least one
  dependency.
- A test proves a Redis outage yields a degraded rate-limit decision and a
  counter increment, not a 500.
- A test proves the Nth requeue of a failing job dead-letters it.
- A test proves a cancelled job leaves the pacing loop promptly.
- Full suite, mypy, ruff green.

### Traps

- Do not put the bucket inside `src/llm.py`'s client singleton; wrap the call
  site so per-job behaviour stays possible. `src/llm.py` belongs to a peer
  work order this wave — coordinate through the coordinator, do not edit it.
- `auth.py`'s 429 body shape is A01's contract now — keep it.

## WO-A05 — Property-based tests

**ADR:** 0069. **Branch:** `assurance/wo-a05-property`. **Depends:** A02.

### Objective

The repository has zero property-based tests and its parsers are exactly the
shape that fuzzing finds bugs in. `tests/test_log_redaction.py:25` already
writes a property by hand — "the secret is never in the output" — for six
cases. Generalize that instinct.

### Owns

- `tests/property/` (new directory, all files)
- `docs/decisions/0069-property-based-testing.md`
- `docs/testing.md` — the property-tier paragraph only (A02 wrote the file
  this wave; keep your edit to one section)

### Deliverables

1. Properties, each with the invariant stated in its docstring:
   - **chunker**: no text is lost, no chunk exceeds the configured size,
     chunking is idempotent, section boundaries are stable under whitespace
     perturbation;
   - **citation extraction**: extracted ids are a subset of ids present; never
     raises on arbitrary text;
   - **redaction** (from A03): for any generated secret, the secret does not
     appear in the output, and non-secret text survives;
   - **config validation**: any value outside a declared `Literal`/range is
     rejected; any accepted value round-trips;
   - **SSE frame encoding**: encode→decode is identity for every event in the
     closed set;
   - **plan/schema validation**: a valid plan always validates; the validator
     never raises an unexpected exception type.
2. A pinned Hypothesis profile with `derandomize` in CI so a failure is
   reproducible from the report; a local profile with more examples.
3. All tests marked `property` plus a tier marker.

### Acceptance

- `pytest -m property` green, and green again on a second run with the same
  seed.
- Your PR body records one **seeded-mutant check**: introduce a deliberate
  bug locally, show the property catches it, revert it. Do not commit the
  mutant.
- Runtime of the property tier under 60 s; state the measured number.

### Traps

- Hypothesis plus the network/spend guards can interact badly if a strategy
  triggers real I/O. Keep strategies pure.
- Do not chase coverage with properties; a property that asserts nothing
  falsifiable is worse than no test.

## WO-A06 — Fault-injection tier

**Branch:** `assurance/wo-a06-fault`. **Depends:** A01, A02.

### Objective

Error-handling code is the least-tested code in most systems because unit
tests exercise the happy path. This tier asserts what happens when
dependencies fail, and it is the mechanism that keeps A01's error contract,
A03's log contract and A07's telemetry contract mutually honest: **every
fault test asserts the triple — the right error code, the right log event,
the right metric.**

### Owns

- `tests/fault/` (new directory, all files)
- `docs/testing.md` — the fault-tier paragraph only

### Deliverables

Fault scenarios, each asserting the triple:

1. Redis unavailable at submit; mid-job; during SSE fan-out.
2. Postgres pool exhausted and connection dropped mid-query.
3. Model provider 429, 500, and timeout — including that the retry envelope
   is respected and the job terminates with `upstream_model`.
4. Cancellation requested between nodes, and during a node.
5. Worker death: lease expiry, redrive claim, and the at-most-once rule for
   `running` jobs.
6. Cost cap tripped mid-run: the partial report survives and the terminal
   status is what the ADR says it is.
7. SSE terminal-frame delivery failure: the job row is still correct and the
   failure is visible.
8. Breaker open (from A04 if merged; otherwise mark `xfail(strict=False)`
   with a comment naming A04 — do not stub A04's behaviour).

### Acceptance

- `pytest -m fault` green, no network, no spend, deterministic.
- Each test names the code, the event and the instrument it asserts.
- Runtime under 90 s; state the measured number.

### Traps

- Use the existing fakes (`fakeredis`, `pytest-postgresql`) rather than
  inventing new doubles.
- A fault test that only asserts "an exception was raised" is not acceptable;
  the point is the *observable* contract.

## WO-A07 — GenAI semantic conventions, trace continuity, RED/USE

**ADR:** 0066. **Branch:** `assurance/wo-a07-telemetry`. **Depends:** A03.

### Objective

Model calls are not spans, node spans are all roots, no trace context crosses
the job boundary, and no name in the repository follows the OpenTelemetry
GenAI semantic conventions — so no off-the-shelf GenAI dashboard can read this
system's telemetry. Queue saturation is invisible until the ceiling is hit,
`degraded_close` reports as `succeeded`, job metrics carry no `kind`, and the
tracer never flushes on shutdown.

### Owns

- `src/observability/metrics.py`, `src/observability/tracing.py`
- `src/llm.py` — span wrapping only, around the existing accounting
- `src/graph/workflow.py`, `src/graph/session_workflow.py` — span attributes
  and context propagation
- `src/api/runner.py` — **only** trace-context extraction and the `kind` /
  `degraded_close` attribute fixes
- `tests/test_otel_metrics.py`, `tests/test_tracing.py`,
  `tests/test_genai_conventions.py` (new)
- `docs/observability.md` — the telemetry sections (A03 created the file)
- `docs/decisions/0066-genai-semantic-conventions.md`

### Deliverables

1. **Exact conventional names** from `02-STANDARDS.md` §1 — do not invent them
   and do not rely on memory; that section was verified against the
   specification sources. Three things it will tell you that commonly go
   wrong: the provider attribute is **`gen_ai.provider.name`**, not the older
   `gen_ai.system`; the conventions have **moved to their own repository with
   no tagged release**, so your ADR pins a commit SHA rather than a version;
   and `OTEL_SEMCONV_STABILITY_OPT_IN` has nothing to do with GenAI content
   capture.
1b. **Map the graph onto the conventional agent spans** rather than inventing
   names: `invoke_agent` (INTERNAL) per node, `plan` for the planner,
   `execute_tool` for arXiv / Semantic Scholar / PDF / embedding calls,
   `invoke_workflow` for a whole run. Emit
   `gen_ai.invoke_agent.inference_calls` and `.tool_calls` — the conventions
   already define exactly the per-invocation counters this system needs.
2. LLM calls become spans carrying the conventional request/response/usage
   attributes, wrapped **around** `record_llm_call` so cost stays
   single-sourced.
3. Token-usage and operation-duration histograms.
4. Trace context injected at job submission and extracted in the worker, so
   submit → node → model call is one trace. This is the highest-value item in
   the work order.
5. `kind` attribute on job metrics; `degraded_close` stops reporting
   `status="succeeded", error_type="none"`.
6. Queue depth and queue-wait instruments.
7. Tracer provider shutdown/flush matching `shutdown_metrics`.
8. Sampling exposed as configuration (read it the way A03 reads its flag —
   `src/config.py` belongs to A04 this wave; record the fold-in as a
   follow-up).
9. Old instrument names retained as aliases for one release, with a comment
   stating when they may be dropped.

### Acceptance

- A test asserts each conventional attribute and metric name literally.
- A test asserts a single trace id spans submit → node → model call.
- A test asserts a cardinality bound: no attribute takes an unbounded value.
- Full suite, mypy, ruff green.

### Traps

- `configure_metrics()`'s only caller is the API lifespan, so CLI and eval
  runs emit nothing. Widening that is **out of scope** — record it.
- Aliasing doubles instrument count; make sure the export path can carry both
  and say what the cost is.

## WO-A08 — Eval integrity: pinned judges, versioned rubrics, run provenance

**ADR:** 0070. **Branch:** `assurance/wo-a08-eval-integrity`.

### Objective

The eval harness cannot currently support a comparison. Judges are not
pinned — `metrics.py:283,546,731` pass no model, so `llm.py:217` falls
through to `settings.anthropic_model`, meaning a product-model upgrade
silently changes the judge and the system grades itself with a moving ruler.
No summary row records the model, the rubric, or the commit that produced it,
so a regression diff cannot distinguish a quality change from a
configuration change. Statistics (WO-A09) are worthless on top of
unattributable rows, which is why integrity lands first.

### Owns

- `src/eval/metrics.py`, `src/eval/learning_metrics.py`, `src/eval/runner.py`,
  `src/eval/simulate_learner.py`, `src/eval/scripted_tier_check.py`,
  `src/eval/benchmark_queries.py`
- `src/config.py` — **only** a new section after the `Telemetry` block (§0.5)
- `tests/test_eval_*.py`, `tests/test_metrics_*.py`,
  `tests/test_learning_metrics.py`, `tests/test_scripted_tier_check.py`
- `docs/eval.md`
- `docs/decisions/0070-eval-integrity-provenance.md`

### Deliverables

1. **`eval_judge_model` setting**, passed explicitly at every judge call site.
   The judge no longer inherits the product model. Default it to the model the
   judges are calibrated against today and say in the ADR that changing it
   invalidates baselines.
2. **Rubric versioning**: a version constant beside each judge prompt
   (`COMPLETENESS_SYSTEM_PROMPT`, `SHAME_FREE_COPY_SYSTEM_PROMPT`, the
   faithfulness and recall prompts, the plan-coherence rubric). A test hashes
   each prompt and fails when the text changes without a version bump — that
   is the mechanism, not the honour system.
3. **Provenance on every summary row**, both lanes: judge model, product
   model, rubric versions, code commit, dataset version, tier, seed, and the
   harness version. `scripted_tier_check` asserts the fields are present and
   non-empty.
4. **Dataset provenance** on `BenchmarkQuery`: author, created date, license,
   and a `notes` field. Populate honestly for the 20 existing queries —
   including preserving the existing annotation that one is "well-covered by
   the built-in mock papers", which is a contamination note and must survive.
5. `docs/eval.md` updated: what provenance now guarantees, and an explicit
   statement that judge–human calibration remains unmeasured and deferred.

### Acceptance

- A test proves a judge call uses `eval_judge_model` and not
  `settings.anthropic_model`.
- A test proves editing a rubric prompt without bumping its version fails.
- A test proves every row in a scripted-tier `summary.jsonl` carries the full
  provenance block.
- `make simulate-learner` still produces `$0.0000` on all 15 scenarios, and
  the CI scripted-tier check still passes.
- Full suite, mypy, ruff green.

### Traps

- The scripted tier is the only gate this repository has that has ever caught
  anything. Do not change what it asserts; only add.
- Row schema changes ripple into `regression_diff.py` (A09's file) — add
  fields, never rename or remove, and tell A09's agent what you added by
  writing it in your PR body.

## WO-A15 — The end-to-end tier

**Branch:** `assurance/wo-a15-e2e`. **Depends:** A02.

### Objective

`docs/testing.md` has a section titled "Planned, not built: the e2e cassette
tier", the `e2e` marker has zero members, the `Makefile` has a `test-e2e`
target that runs nothing, and CI filters on `-m "not e2e"` — a filter that
currently excludes an empty set. The agent's full-workflow behaviour has no
end-to-end test. Build the tier, at zero spend, using the mock path the
learning lane already proves works.

### Owns

- `tests/e2e/` (new directory, all files)
- `tests/fixtures/e2e/` (new)
- `docs/testing.md` — replace the "planned, not built" section
- `Makefile` — the `test-e2e` target only

### Deliverables

1. A full research-workflow e2e test in mock mode: submit → plan → search →
   read → synthesize → critic → report, asserted on the **trajectory**
   (nodes visited in order, iteration count, terminal status, citations
   present, cost exactly `$0.0000`) rather than on prose.
2. A guided-read session e2e test through the session graph, including the
   `awaiting_learner` pause and resume.
3. An HTTP-surface e2e test: submit through the API, consume the SSE stream to
   its terminal frame, fetch the result, and export it — the path a real
   client takes.
4. A HITL e2e test: plan review, revise, approve, terminal.
5. Every test marked `e2e`; the tier runs in well under the CI job budget and
   you state the measured wall time.
6. `Makefile`'s `test-e2e` pins the same zero-spend environment the
   `simulate-learner` target does — mock mode plus the disabled-key sentinel —
   so the target cannot spend by accident.

### Acceptance

- `pytest -m e2e` green from a clean checkout with no network and the disabled
  key.
- A test asserts the recorded trajectory, not just a non-empty report.
- Total cost asserted as exactly zero on every e2e run.
- `pytest -m "not e2e"` count unchanged from baseline.

### Traps

- Do not record LLM cassettes. Mock mode is already the zero-spend seam, and
  cassettes would need a paid recording session to create.
- The session graph pauses on `awaiting_learner`; drive it, do not disable it.

---

# Wave 3 — completion, gates, evidence

Wave 3 starts after wave 2 merges and `main` is re-verified as a whole.

## WO-A09 — Eval statistics and aggregate gates

**ADR:** 0071. **Branch:** `assurance/wo-a09-eval-stats`. **Depends:** A08.

### Objective

The regression gate compares exactly two records with a flat ±0.10 band that
ADR 0044 already calls "priors, not statistics". Two of the four research
metrics quantize at 0.20–0.25, so the band filters nothing and one flipped
judge decision is a guaranteed red. `--repeats` on the learning lane produces
`r1/r2/r3` ids that are then compared pairwise instead of aggregated, so
three repeats cost triple and buy nothing; the research lane has no
`--repeats` at all while `REPEATS_FOR_CONFIDENCE = 3` is advertised in code.

### Owns

- `src/eval/stats.py` (new), `src/eval/regression_diff.py`,
  `src/eval/runner.py` (the `--repeats` flag and aggregation only)
- `tests/test_regression_diff.py`, `tests/test_eval_stats.py` (new)
- `docs/eval.md` — the statistics and gate sections
- `docs/decisions/0071-eval-statistics-and-gates.md`

### Deliverables

1. `stats.py`: **McNemar for paired binary outcomes**, paired bootstrap
   confidence intervals over tasks with hierarchical resampling when repeats
   exist, Wilson intervals for binary rates, and the **rule of three** for a
   clean suite. All pure, seeded, and unit-tested against hand-computed
   values.
1b. **Pairing is the headline, not the bootstrap.** Detecting a 5-point gain
   against an 80% baseline needs ~906 items per arm unpaired and ~77 paired.
   Make paired comparison the default path and score baseline and candidate on
   the same items.
1c. **A minimum-N guard with an explicit CLT caveat.** Below a few hundred
   datapoints the normal approximation underestimates uncertainty — which is
   this repository's regime at 20 queries. The report must say its interval is
   approximate at this N rather than print a falsely narrow one.
1d. Report **`pass^k`** alongside any success rate.
2. Repeat **aggregation** by task before diffing, on both lanes; `--repeats`
   added to the research runner.
3. Per-metric epsilon derived from each metric's quantum rather than a shared
   constant, so completeness and retrieval recall get bands that can actually
   filter.
4. `citation_accuracy` stops returning 1.0 for zero citations; the gate reads
   the corrected metric.
5. `critic_score` demoted from gate to reported diagnostic, with the
   reasoning in the ADR: it is the product grading itself, and its
   parse-failure `0.0` coercion reads as a full-scale regression.
6. The report prints an interval and a **three-state decision — PROMOTE /
   HOLD / ROLLBACK** — and states plainly when N is too small to separate a
   move from noise. No model call may occur inside the gate logic. That sentence is the deliverable —
   an honest gate that says "cannot distinguish" is worth more than a
   confident one that cannot.

### Acceptance

- Statistical functions tested against hand-computed values.
- A test proves three repeats of identical rows produce a zero-width interval
  and no regression.
- A test proves a single flipped quantized judge decision no longer trips the
  gate on its own.
- ADR 0044 is superseded in the index rather than silently contradicted.

## WO-A10 — API middleware, request ids, RED metrics, readiness split

**Branch:** `assurance/wo-a10-api-observability`. **Depends:** A01, A03, A07.

### Objective

`create_app` adds CORS and nothing else, so there are no HTTP RED metrics,
no request id, and no place where inbound trace context is extracted.
`/healthz` always returns 200 even when it reports `status: degraded`, and
there is no `/readyz`, so an orchestrator cannot drain a worker whose Redis is
dead. uvicorn runs with `log_config=None`, so access lines land in the JSON
stream as unparsed text.

### Owns

- `src/api/app.py` (middleware), `src/api/routes.py` (health endpoints only),
  `src/api/serve.py`
- `tests/test_api_middleware.py` (new), `tests/test_health_logging.py`
- `docs/observability.md`, `docs/architecture.md` (API section)

### Deliverables

1. One middleware that: accepts or mints a `request_id`, binds A03's
   `RequestContext`, extracts inbound W3C trace context, records RED metrics
   keyed on the **route template** (never the raw path), and emits one
   structured access line replacing uvicorn's.
2. `/healthz` = liveness: cheap, always truthful about the process, keeps its
   current always-200 semantics **because** readiness now exists.
3. `/readyz` = readiness: 503 when a required dependency is down or the queue
   is saturated, with the same body shape.
4. The `request_id` is echoed in the response header and in A01's error
   envelope.

### Acceptance

- A test proves `/readyz` returns 503 with Redis down and 200 when healthy.
- A test proves the RED metric uses the route template for a parameterized
  route.
- A test proves an inbound `traceparent` is adopted rather than replaced.
- A test proves the response carries the request id that appears in the log.

## WO-A11 — Adversarial safety suite and the safety gate

**ADR:** 0072. **Branch:** `assurance/wo-a11-safety`. **Depends:** A02.

### Objective

The entire adversarial evidence base today is five regexes in
`security/prompt_isolation.py:83` tested against ~6 synthetic payloads, plus a
literal-canary substring check on 2 of 15 learning scenarios. A model that
*obeys* an injection while paraphrasing the canary scores as contained. Before
MCP and additional tools widen the attack surface, the measurement has to be
real.

### Owns

- `tests/fixtures/safety/` (new), `tests/test_safety_suite.py` (new)
- `src/eval/safety_suite.py` (new)
- `src/security/prompt_isolation.py` (extend only)
- `src/eval/simulate_learner.py` — **only** to add the pedagogy metric to the
  row (coordinate with A08's schema; add, never rename)
- `docs/security.md`
- `docs/decisions/0072-adversarial-safety-suite.md`

### Deliverables

1. A corpus under `tests/fixtures/safety/` mapped **primarily to the OWASP Top
   10 for Agentic Applications (ASI01–ASI10)** and secondarily to the LLM Top
   10 — read `02-STANDARDS.md` §3.2 first; for a tool-using agent the agentic
   list is the relevant one. Cover: goal hijack, tool misuse, identity and
   privilege abuse, memory and context poisoning, indirect injection via
   retrieved content, exfiltration, source laundering, poisoned metadata,
   cross-principal probing. Each case carries an id, category code, payload,
   expected behaviour, and a provenance note.
1b. **Licensing is a hard constraint.** OWASP prose is CC BY-SA 4.0 and viral:
   cite category **codes** and write your own descriptions — do not paste
   OWASP text into this repository. Author the payloads yourself; you may
   model the record *schema* on the CC-BY-4.0
   `nvidia/Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1` set. Do **not**
   vendor BeaverTails (CC-BY-NC) or AgentHarm (field-of-use clause).
2. **Behavioural assertions, not canary substrings**: assert what the agent
   *did* — which tools ran, which fields changed, what left the process, what
   the profile store contains afterwards. A paraphrasing obedient model must
   fail.
3. **Attack success rate with its denominator, gated as a regression-delta
   against a fixed baseline — not as an absolute threshold.** ASR is a
   property of the deployment surface, not the model, and at n=100 an observed
   3% carries a Wilson interval of roughly 1.0–8.5%, so an absolute "ASR < 5%"
   gate flips on noise. Absolute zero is reserved for **categorical hard
   violations**: secret exfiltrated, unauthorised tool called, egress to a
   non-allowlisted host.
3b. A three-state **PROMOTE / HOLD / ROLLBACK** decision with the safety veto
   evaluated first, advisory-by-default behind a flag until the baseline is
   trusted, and **zero model calls inside the gate logic** — content-preserving
   wrappers flip 57–100% of LLM-judge verdicts, so a judge in a gate is an
   attack surface.
4. The pedagogy deny-list becomes a campaign metric in `summary.jsonl` — today
   it fails pytest but is invisible to the gate.
5. Everything runs at zero spend in mock mode and is marked `security`.

### Acceptance

- `pytest -m security` green and runnable as a standalone gate.
- A test proves an obedient-but-paraphrasing response fails containment.
- Attack success rate is reported with its denominator, and the
  zero-tolerance classes are enumerated in the doc.
- The pedagogy metric appears in a scripted-tier row.

### Traps

- Do not weaken any existing assertion to make a new one pass.
- Payloads are fixtures, not live exploits: no network, no real credentials,
  nothing that would be harmful outside the test harness.

## WO-A12 — Operability: SLOs, runbooks, alert rules, dashboard

**ADR:** 0073. **Branch:** `assurance/wo-a12-operability`. **Depends:** A07, A10.

### Objective

Every instrument in the repository exports to nothing by default, and
`docs/runbooks/` contains exactly one page, about pilot credentials. There are
no SLOs, no alert rules, no dashboards, and no documented response to the
incidents the new instruments will surface.

### Owns

- `docs/reliability.md` — the SLO sections (A01 created the file)
- `docs/runbooks/*.md` (new pages)
- `deploy/observability/` (new: alert rules, dashboard definition, collector
  compose overlay — **not** wired into the default stack)
- `tests/test_operability_docs.py` (new)
- `docs/README.md` — index entries
- `docs/decisions/0073-slos-and-operational-readiness.md`

### Deliverables

1. SLI/SLO table per `03-ARCHITECTURE.md` §5.4, with error budgets and an
   explicit statement that the initial objectives are declared, not earned.
   Anchor it on the SRE Workbook's **quality** SLI — the proportion of
   responses served undegraded — because there is no credible published
   methodology specific to LLM quality budgets and a number from a vendor blog
   is not evidence (`02-STANDARDS.md` §5.1). **Exclude degraded and shed
   requests from the latency SLI** and count them against quality instead.
   State the compounding arithmetic: 95% per step over five steps is 77.4%.
1b. A **degradation ladder** (cached/stale with disclosed age → reduced-tool →
   partial with confidence → streaming partials → model fallback → bounded
   queue → honest refusal) in which **every rung emits a distinct marker**.
   Without distinct markers degradation makes the dashboard look better while
   the product gets worse — and this repository already has that failure: the
   reader's abstract-only fallback is tallied and logged and never reaches the
   user.
2. Runbooks: model-provider outage, Redis loss, Postgres loss, cost-cap storm,
   queue saturation, poison job, injection alarm. Each names the signal, the
   first three commands, the containment action, and the rollback.
3. Alert rules referencing the **actual** instrument names from A07, and a
   dashboard definition.
4. **A test that asserts every metric name referenced in the alert rules
   exists in `src/`.** This is what stops the alerting from rotting silently,
   and it is the deliverable that makes this work order more than prose.
5. A collector overlay that is present, documented, and **not** enabled by
   default — standing one up costs money and is the owner's call.

### Acceptance

- The name-consistency test fails when an instrument is renamed.
- Every runbook names a signal that an instrument actually emits.
- Nothing in the default `docker compose` path changes.

## WO-A13 — CI wiring for the new tiers

**Branch:** `assurance/wo-a13-ci`. **Depends:** every other work order.

### Objective

Wire the tiers into CI so they gate, without turning a 9-check PR into a
20-check PR or adding minutes that buy nothing.

### Owns

- `.github/workflows/ci.yml`
- `web/tests/ci.test.ts`
- `docs/development.md`, `docs/testing.md` — the CI sections

### Deliverables

1. Coverage gate in the existing `tests` job (not a new job) with the artifact
   uploaded.
2. `property`, `fault` and `security` tiers running per PR. Prefer adding them
   to the existing `pytest` invocation over new jobs; if a tier needs
   isolation, justify the new job in the workflow comment the way the
   `web dependency audit` split is justified.
3. The `e2e` tier running per PR if it fits the budget, nightly-style
   otherwise — but **do not enable either disabled nightly workflow**.
4. The safety gate reporting its attack-success-rate as a build artifact.
5. `web/tests/ci.test.ts` updated to pin the new shape. It pins the workflow
   as raw text, so keep the edits it asserts on stable and readable.
6. State the new total check count in the PR body — the coordinator's merge
   gate counts checks and must be updated.

### Acceptance

- CI green on the PR with the new steps active.
- Added wall-clock time stated per job and justified.
- `web/tests/ci.test.ts` passes and reflects reality.

## WO-A14 — Assurance evidence pack and framework mapping

**Branch:** `assurance/wo-a14-evidence`. **Depends:** every other work order.

### Objective

Close R10. A reviewer should be able to open one index and follow every claim
this repository makes about reliability, safety, accuracy and compliance to
the artifact that enforces it — and see plainly what is *not* yet proven.

### Owns

- `docs/assurance/` (new): `README.md`, `model-card.md`,
  `data-provenance.md`, `framework-mapping.md`
- `planning/08-assurance/evidence/gate-a3/`
- `docs/README.md` — index entry
- `README.md` — one short pointer paragraph only

### Deliverables

1. **A system card, not a model card.** This project does not train models, so
   the honest artifact describes the *system*: intended use, out-of-scope use,
   the models used and their routing, evaluation results **as measured** (never
   aspirational), known limitations, safety measures, and the explicit
   statement that judge–human calibration is unmeasured.
2. **Data provenance record** following the **NIST AI 300-1 ipd dataset
   template field set** (`02-STANDARDS.md` §4.2) — it is the best free
   conformity-assessable template available. Cover the benchmark query set,
   learning scenarios, recorded mock sessions, safety corpus and content packs:
   origin, author, licence, date, and contamination notes, including the
   "well-covered by the built-in mock papers" annotation.
3. **Framework mapping** (`02-STANDARDS.md` §4) as the keystone crosswalk:
   framework | control id | how satisfied | artifact path | last reviewed SHA |
   Met / Partial / **Out-of-reach**. Map NIST AI RMF (MEASURE 2.1 especially),
   the **OWASP Agentic (ASI) codes** as primary with the LLM Top 10 secondary,
   and ISO 42001's A.6.2.8 / A.6.2.4 / A.7.5 controls. NIST **MS-1.1-009**
   explicitly sanctions recording risks you cannot measure with a reason why —
   so an empty "out-of-reach" column is a mapping nobody checked.
3b. **EU AI Act, carefully.** The position to document: Article 50(1)
   disclosure is satisfiable and is the only live obligation; high-risk scope
   almost certainly does not apply, because Annex III's education entry is
   bounded by *"in educational and vocational training institutions"*; and
   Art. 50(2) machine-readable marking is not currently feasible for text —
   say why. **Re-verify every date before asserting it**: the research pass
   could not read EUR-Lex directly and annex-level detail is contested between
   secondary sources. Describe obligations without asserting a schedule if
   verification fails.
3c. An **SBOM**: `pip-audit --format cyclonedx-json` produces the SBOM and a
   vulnerability audit from one PyPA tool. Commit the output, dated.
4. **Claim → enforcement index**: for each claim in `README.md` and
   `docs/architecture.md`, the test, gate or instrument that fails when the
   claim stops being true. Claims with no enforcement are listed as such.
5. **Gate A3 evidence pack** assembled from CI artifacts and runner-verified
   locally — never a number typed by hand. Note that **CI runs are not the
   record**: artifact retention is finite, so the committed dated summary is
   the durable artifact.

### Acceptance

- Every artifact reference in the mapping resolves to a real path.
- The "not satisfied" column is non-empty and honest.
- The claim index cites `file:line` or a test name for each enforced claim.
- No claim in the model card is stated more strongly than its evidence.


## WO-A16 — Deterministic groundedness: hallucination measurement with no judge

**ADR:** 0074. **Branch:** `assurance/wo-a16-groundedness`. **Depends:** A08.

### Objective

This repository can measure hallucination **without a model call**, and does
not. Because the corpus is arXiv papers, two of the most valuable accuracy
signals are deterministically checkable: whether every cited arXiv identifier
resolves to a real paper, and whether every quoted span appears **verbatim**
in the fetched PDF.

That is strictly more defensible than a judge — it cannot be argued with, it
costs nothing, it does not drift when a model is upgraded, and it produces a
per-claim binary outcome, which is exactly the paired variable WO-A09's
McNemar path needs. Today `citation_accuracy` is a regex over identifiers that
returns **1.0 for a report with zero citations**, and faithfulness is a judge
call against abstracts only.

This is the single highest-value evaluation item available at zero spend, and
it exists only because of the domain.

### Owns

- `src/eval/groundedness.py` (new)
- `tests/test_groundedness.py` (new), `tests/fixtures/groundedness/` (new)
- `docs/eval.md` — the groundedness section only (coordinate with A09, which
  owns the statistics sections)
- `docs/decisions/0074-deterministic-groundedness.md`

### Must not touch

`src/eval/metrics.py` (A08), `src/eval/regression_diff.py`,
`src/eval/stats.py`, `src/eval/runner.py` (A09), `src/tools/**`.

### Deliverables

1. **Identifier resolution**: every cited arXiv id in a report is checked for
   well-formedness and for existence **against the papers actually retrieved
   in that run** — not against the live network, which the harness forbids.
   A citation to a paper the run never fetched is the interesting failure and
   must be reported distinctly from a malformed id.
2. **Verbatim quote checking**: every quoted span in a report is located in the
   parsed text of the cited paper, with normalization that is documented and
   tested (whitespace, ligatures, hyphenation across line breaks, unicode
   quotes). Normalization is where this kind of check quietly becomes useless —
   state exactly what is normalized and prove each rule with a test.
3. **Metrics with honest denominators**: `citation_resolution_rate`,
   `quote_verbatim_rate`, and an `unsupported_claim_count`. Each reports its
   denominator, and **zero citations is not a perfect score** — it is reported
   as `None` with a distinct reason code, fixing the failure mode
   `citation_accuracy` has today.
4. **Per-claim binary outcomes** emitted in a form WO-A09 can pair on.
5. Runs offline, at zero spend, over the existing recorded fixtures.

### Acceptance

- A test proves a report citing a paper the run never retrieved is flagged.
- A test proves a near-miss quote (one word changed) fails, and that a quote
  differing only by hyphenation across a line break passes.
- A test proves zero citations yields `None` with a reason, not `1.0`.
- Every metric reports its denominator.
- Full suite, mypy, ruff green; no network; `$0.0000`.

### Traps

- Do not fetch anything from the network to resolve an identifier. The harness
  forbids it and the check is more useful scoped to the run's own corpus.
- PDF text extraction is lossy; a quote check that is too strict measures the
  parser, not the agent. Calibrate against the existing fixtures and record
  what you found.
