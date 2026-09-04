# 0068. Retry at one level, on a budget, with Full Jitter

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: Phase A assurance program (WO-A04)

## Context

`planning/08-assurance/01-BASELINE.md` §2 measured what this service does
when a dependency is unwell, and the answer was: multiply.

**Retries happened at five levels of one stack.** The Anthropic SDK
retried; `urllib3.Retry` retried under every `requests` call; and three
hand-rolled loops retried on top of those. Retry amplification is
multiplicative — three retries at five levels is 243x the load on a
dependency that is already failing — so the first failure of an upstream
was, by construction, the start of the second.

Around that, five smaller holes, each of which turns a dependency's bad
minute into this product's bad minute:

1. **The arXiv timeout was a hardcoded `timeout=30`** — the one
   un-tunable timeout in a codebase that centralises every other knob —
   and nothing clamped `(retries + 1) * timeout` against the job budget.
   `src/llm.py:62-91` has clamped the model's envelope since ADR 0051;
   the HTTP side had the same arithmetic and none of the guard. At the
   shipped values one search node could issue 12 queries x 4 attempts x
   30s and exceed a 600s job on pacing and retries alone.
2. **The Redis client had no connect timeout, no socket timeout, no
   health check and no retry policy** — `from_url(url,
   decode_responses=False)` was the whole configuration. An unreachable
   Redis did not fail a request, it hung one, which is why `create_app`
   wraps its startup sweep in an `asyncio.wait_for`.
3. **The rate limiter 500'd on a Redis outage.** `pipe.execute()` was
   unguarded, so a blip in the shared counter answered every submit with
   an opaque error. A defence that converts a dependency's blip into a
   total outage costs more than the burst it prevents.
4. **The redriver could requeue a poison job forever.** With
   `job_redrive_requeue_pending` on, a job that reliably kills its
   worker looks to every sweep like an orphaned `pending` row that
   deserves another chance.
5. **The search pacing loop slept three seconds per query with no
   cancellation check**, so a cancelled job could spend its whole 30s
   drain window asleep between queries it was never going to issue.

`planning/08-assurance/02-STANDARDS.md` §5.2 is the research pass behind
the choices below, and it settled one contested question in advance: a
retry token bucket rather than a circuit breaker.

## Decision

### 1. One owning level of retry per dependency

Written down, and asserted, rather than left implicit across five files:

| Dependency | Owning level | Everything else |
|---|---|---|
| Anthropic API | the SDK's clamped envelope, `src/llm.py:62-91` | no application loop |
| arXiv / Semantic Scholar / PDFs | `urllib3.Retry`, `src/tools/http_session.py` | no per-call loop |
| Redis | `redis-py`'s own `Retry`, `src/api/redis_store.py` | no application loop |

`tests/test_resilience_transport.py` proves the arXiv row against a
loopback server that counts requests: a failing query costs
`http_max_retries + 1` requests, and the count tracks the setting rather
than a constant, so a second retrying level anywhere in the stack fails
the test as an 8 or a 16.

Two loops survive the consolidation because they are **not transport
retries**, and calling them retries is what made the count five:

- `src/agents/synthesizer.py:281` re-prompts once on an unparseable
  model response. That is a semantic retry — a different prompt, not the
  same request — and removing it would lose a real recovery. It does,
  however, multiply against the SDK envelope, and that is recorded as a
  follow-up rather than fixed here (`src/agents/synthesizer.py` belongs
  to no work order this wave).
- `src/api/runner.py:440` and `:1071` re-attempt a terminal *write* to
  the job store. No upstream is involved and no load is amplified.

### 2. A retry token bucket, not a circuit breaker

`src/resilience.RetryBudget`. A refilling budget that a **retry** spends
and a **first attempt** never consults, so a healthy caller cannot tell
it is there. Tokens return two ways: continuously with time
(`retry_budget_refill_per_sec`), and per successful call
(`retry_budget_success_refund`, defaulting to the AWS SDKs' five
successes per retry). The time refill is what lets a fully drained
bucket recover during an outage that is denying it successes; the
success refund is what couples the budget to the retry/success *ratio*
rather than to an absolute rate.

It is enforced in `BudgetedRetry.increment`, which is the one place
urllib3 decides that a retry will happen — so the bucket is charged once
per retry taken, never per request and never per connection. An
exhausted budget raises the same `MaxRetryError` the attempt count
raises, which `requests` maps to `RetryError`, which every existing
`except RequestException` already handles. A budget-exhausted arXiv
search therefore still fails as `upstream_arxiv`: the budget changes
*when* an outage is reported, never *what* it is.

The bucket is **per process**, not shared through Redis. That is the AWS
design and the right one for a retry guard: a budget that had to ask
Redis for permission would be unavailable in exactly the outage it
exists for, and would put a network round trip on the failure path. The
cost is that N workers hold N budgets, so the fleet-wide ceiling is
`N x retry_budget_capacity`.

### 3. Full Jitter on every backoff

`sleep = random(0, min(cap, base * 2**attempt))`, in
`src/resilience.full_jitter_delay`, overriding
`urllib3.Retry.get_backoff_time` and passed to redis-py as
`FullJitterBackoff`. urllib3's own `backoff_jitter` adds a small uniform
term *on top of* the full exponential delay, which leaves a synchronised
fleet waking inside the same narrow window. Drawing from zero is what
decorrelates it. `backoff_max` now comes from `http_backoff_max_sec`
(20s) instead of urllib3's 120s default, which is a fifth of a job
budget spent asleep inside one request.

### 4. Every timeout is a setting, chosen from a false-timeout rate

`arxiv_timeout_sec` (25.0), `redis_connect_timeout_sec` (5.0),
`redis_socket_timeout_sec` (5.0), `arxiv_pacing_sec` (3.0),
`redis_health_check_interval_sec` (30).

The arXiv value is the one that changed, and it deserves an honest note.
The standard says: pick the percentile you are willing to cut off rather
than a round number. This deployment declares a **0.1% false-timeout
budget** — it accepts abandoning the slowest ~1 in 1000 arXiv responses
and paying for the rest. What it does *not* have is a measured arXiv
latency distribution to fit that percentile against, so 25.0 is a
**declared** target rather than a fitted one, and replacing the
declaration with a measurement is a follow-up below. Moving off 30 is
deliberate: leaving the round number would have made "this is now
derived" a claim with no visible consequence.

`retry_after_max` is also bounded now, at the call chain's whole budget.
urllib3 honours a server-supplied `Retry-After` of up to six hours by
default; a delay longer than the chain's budget cannot help the job,
which times out first, so sleeping a worker thread through it is the
worst of both outcomes.

### 5. The HTTP retry envelope gets the clamp `src/llm.py` already had

`src/resilience.clamped_retry_envelope`, copied deliberately from
`_retry_envelope`. urllib3 applies its timeout per attempt exactly as
the Anthropic SDK does, so one logical request costs
`(retries + 1) * timeout`; the clamp trims retries until that fits
`api_job_timeout_sec * http_call_chain_budget_fraction`, and logs
`retry_envelope_clamped` at WARNING when it bites. The fraction is 0.25
rather than the model's 0.75 because a job is mostly model calls and one
search node issues up to twelve HTTP requests.

Attempts are trimmed rather than the per-attempt timeout, for
`src/llm.py`'s reason: a shorter timeout abandons *slow but healthy*
responses, which is the failure that looks like an outage while the
dependency is fine.

### 6. The rate limiter degrades and serves

On any Redis failure `RedisRateLimiter` falls back to a real per-worker
`InMemoryRateLimiter` — one instance, kept for the limiter's lifetime,
so a degradation spanning several requests accumulates in one window —
and calls `resilience.record_degradation`.

**Fail-open is the deliberate choice.** The counter exists to stop one
key bursting past a courtesy quota, not to protect a secret; refusing
every request because the counter is unavailable trades a small
over-serve for a total one. The fallback is a weaker guarantee, not an
absent one: a fleet of N workers still caps a key at
`N x api_key_hourly_limit`, which is exactly the pre-ADR-0037 behaviour.

The `except` is deliberately wide. Narrowing it would mean enumerating a
client library's exception tree — connection errors, timeouts, a `MOVED`
from a resharded cluster, a decode error from a key another tenant
wrote — and being wrong about it during an incident. The response is the
same for all of them, and the 429 is raised outside the guard so the
width can never swallow the answer the limiter exists to produce.

### 7. The redriver dead-letters a poison job

An `INCR` counter per job (`redriveattempts:{job_id}`, TTL matching the
job's retention) is bumped **before** each requeue; past
`job_redrive_max_attempts` the job is failed with the new code
`internal_dead_letter` instead of being put back in flight.

The counter is a separate key rather than a field on the `Job` row for a
correctness reason, not an ownership one: `JobRedriver._requeue` resets
the row to a clean submit state — status, timestamps, `error`,
`error_type` — and a counter living on the thing being reset is one
future line away from being zeroed by the very write it bounds. `INCR`
is also atomic, which matters because the redrive lock is a
de-duplication optimisation and not mutual exclusion (ADR 0048).

`internal_dead_letter` is a distinct code rather than a fourth
`orphaned` because the two tell an operator opposite things. `orphaned`
means "a worker died under this job; resubmitting is expected to work",
which is what its message advises. A dead-lettered job has already been
resubmitted its full allowance and stopped its worker every time, so
repeating that advice would be a lie — and a dashboard that could not
separate them would render a poison-message loop as a healthy reclaim
rate. `02-STANDARDS.md` §5.3: every rung of the degradation ladder gets
a distinct marker.

### 8. The pacing loop is interruptible

`resilience.interruptible_sleep` slices the wait and calls
`check_cancelled()` between slices, bounding the delay before a cancel
is noticed at 50ms instead of a full pacing interval per remaining
query.

## Alternatives considered

- **A circuit breaker** (Nygard, Fowler) — the mainstream answer, and
  the one `01-BASELINE.md` itself asks for ("No circuit breaker
  anywhere"). Rejected on AWS's argument, which `02-STANDARDS.md` §5.2
  records: a breaker introduces a second mode to the success path, and
  modal behaviour is hard to test — a half-open state that mis-probes
  fails *requests that would have succeeded*. The bucket is a fraction
  of the code, adds no mode, and addresses the measured problem (paying
  a full retry envelope per job during an outage) head on. **The breaker
  is considered and rejected, not overlooked.**
- **A Redis-backed shared retry budget.** More accurate across a fleet,
  and unavailable in the outage it exists for. Rejected: a retry guard
  must not have a network dependency on its failure path.
- **Adding `stamina` or `tenacity`.** `02-STANDARDS.md` §5.2 names
  `stamina` as the healthiest retry library and records it as the choice
  *if one is ever added*. Not added here: the retry machinery this
  service needs already exists in urllib3 and redis-py, and the work
  order's finding is that the problem is too many retry mechanisms, not
  too few.
- **Hedged requests.** Exactly wrong at zero budget — they double tail
  spend. The useful idea from the same source is the good-enough partial
  response, which the search agent already implements by proceeding on
  the queries that succeeded.
- **Shortening timeouts instead of trimming attempts.** Rejected for
  `src/llm.py`'s reason: abandoning slow-but-healthy responses is the
  failure that looks like an outage while the dependency is fine.
- **Fail-closed on a Redis outage** (refuse submits when the shared rate
  limiter is unavailable). Defensible if the limiter were protecting a
  secret or a hard cost ceiling. It is protecting a courtesy quota, and
  the cost ceiling is enforced separately and per-run by `call_llm`
  (ADR 0051), so failing closed would buy nothing and cost everything.
- **A `dead_letter` `JobStatus`** rather than `failed` plus a code.
  Rejected: a new terminal status ripples through the SSE contract, the
  OpenAPI snapshot, the web state machine and the retention TTL, for a
  distinction that `error_type` already carries.
- **An OpenTelemetry counter for degradations.** The right long-term
  home. `src/observability/metrics.py` builds its instruments as one
  frozen bundle and belongs to WO-A07 this wave, so the counter is
  in-process for now and the fold-in is a follow-up. The WARNING log
  lands either way, which is what an operator alerts on today.

## Consequences

- **Positive.** An upstream outage now costs a bounded number of retries
  per worker instead of a full envelope per job. A Redis outage
  degrades the rate limiter instead of 500-ing every submit, and cannot
  hang a request. A poison job stops after
  `job_redrive_max_attempts`. A cancelled job leaves the pacing loop in
  50ms. Every timeout on these paths is a setting with a written
  justification, and the retry policy for each dependency is one place
  with a test that says so.
- **Negative.** Thirteen new settings, and a fleet-wide retry ceiling
  that scales with worker count rather than being a single number. The
  budget is another thing that can be misconfigured — a capacity too
  small throttles retries a healthy deployment needs — which is why
  `enable_retry_budget` exists as a kill switch, and why the default
  capacity (100 retries, refilling at one per second) is generous enough
  that no healthy deployment should reach it. The degradation counter is
  not yet on the metrics pipeline. The arXiv timeout moved from 30 to 25
  without a measured distribution behind it.
- **Follow-ups**, none of them fixed here because each is in a file this
  work order does not own:
  1. Measure the arXiv latency distribution and replace
     `arxiv_timeout_sec`'s declared p99.9 with a fitted one.
  2. Fold `record_degradation` into `src/observability/metrics.py`'s
     instrument bundle (WO-A07 owns that file this wave).
  3. `src/agents/synthesizer.py:281` re-prompts once on unparseable
     output, and that second attempt multiplies against the SDK's
     clamped envelope: worst case 2 x 5 x 120s against a 600s job.
     Either clamp the pair together or bound the re-prompt.
  4. `src/tools/pdf_parser.py`'s `DOWNLOAD_TIMEOUT_SEC` and
     `src/content/linkcheck.py`'s pacing sleep are still module
     constants, and neither declares its timeout to
     `build_retrying_session`, so neither gets the clamp.
  5. `create_app`'s `asyncio.wait_for` around the startup redrive sweep
     was a workaround for the missing Redis connect timeout and can now
     be simplified (`src/api/app.py` is not this work order's).
  6. `InMemoryRateLimiter` raises `IndexError` rather than 429 when
     `limit_per_hour` is 0. Unreachable through `Settings` (`ge=1`), so
     it is a latent trap rather than a live bug.
  7. `urllib3.Retry.sleep()` is still a plain blocking sleep, so an HTTP
     backoff holds a node thread through a cancel the way the pacing
     loop used to. `interruptible_sleep` is the fix; applying it there
     changes behaviour for call sites this work order does not own.
