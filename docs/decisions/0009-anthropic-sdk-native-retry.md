# 0009. Use the Anthropic SDK's built-in retry over a custom loop or tenacity

- **Status**: accepted
- **Date**: 2026-07-06

## Context

The eval runner (ADR
[0008](0008-eval-runner-sequential-per-query-isolation.md)) exposed
Anthropic 429s as the dominant failure mode in real eval runs: a
single benchmark run fires ~300 Claude calls (10 queries × ~30 per
query with the full-text reader). A single unretried 429 aborts the
whole run.

We need retry-with-backoff on transient Anthropic errors (429, 408,
409, 5xx) and a saner request timeout than the SDK default of 10
minutes.

## Decision

Configure retries and timeout on the `Anthropic` client at construction:

```python
_client = anthropic.Anthropic(
    api_key=api_key,
    max_retries=MAX_RETRIES,        # 4 retries -> up to 5 attempts
    timeout=REQUEST_TIMEOUT_SEC,     # 120s per request
)
```

- `MAX_RETRIES = 4` — retries after the first attempt. Chosen for the
  eval workload; 5 total attempts absorbs multi-second rate-limit
  windows without unbounded retry storms.
- `REQUEST_TIMEOUT_SEC = 120.0` — enough for a 4096-token synthesis
  response, low enough that hung requests fail loudly and hand off to
  retry rather than blocking the sequential eval loop for minutes.

The SDK's retry uses exponential backoff (0.5s → 1s → 2s → 4s → 8s,
capped) with jitter and retries on 408 / 409 / 429 and 5xx — exactly
what we want.

## Alternatives considered

- **`tenacity` decorator around `call_llm`.** Rejected. Adds a
  dependency and a second retry layer duplicating what the SDK already
  provides. `tenacity` is only worth reaching for when we need
  application-level retry semantics the SDK can't express (e.g. retry
  on malformed JSON response). Revisit if we hit that.
- **Custom retry loop in `call_llm`.** Rejected for the same reason —
  the SDK already implements backoff-with-jitter correctly, and
  wrapping it means we'd need to introspect exception types the SDK
  already knows how to interpret.
- **No timeout override.** Rejected. The SDK's 10-minute default lets
  a stuck TCP connection block a query for 10 minutes — a nightmare
  for sequential eval runs. 120s is a reasonable ceiling.
- **Per-call retry configuration.** The SDK supports passing
  `max_retries` on individual `messages.create` calls too. Rejected
  for now — no call site currently needs a different policy from the
  default. Revisit if we want, e.g., zero-retry on the critic to keep
  iteration counts predictable.
- **Application-level retry with structured logging on each retry.**
  Attractive for observability, but requires wrapping the SDK's
  behavior (which retries silently) with a custom layer. Deferred to
  `feat/observability-structured-logging` where we build the logging
  substrate anyway.

## Consequences

- **Positive**:
  - Eval runs survive multi-second 429 windows without human
    intervention. Real regression signal is no longer drowned out by
    transient rate limits.
  - No new dependency. `tenacity` avoided.
  - Retry policy is one place, one configuration surface. Every
    call site (planner, reader, synthesizer, critic, eval judges)
    inherits it for free.
- **Negative**:
  - Retries are silent — we don't see when they happen. If a call
    retries three times before succeeding, the caller doesn't know it
    was fragile. Mitigation: `feat/observability-structured-logging`
    (upcoming) will add retry-hook logging.
  - No jitter observability. If retry timing becomes a bottleneck we
    won't know without instrumenting the SDK's httpx transport.
- **Follow-ups**:
  - Retry / backoff for arXiv PDF downloads (`feat/arxiv-download-retry`).
    Currently `tools/arxiv_search.py` has an ad-hoc retry loop; unify
    with a shared retry helper when the observability layer lands.
  - Retry-hook logging via structured logs when the observability
    piece lands.
  - Consider per-call `max_retries=0` on the critic if we find its
    iteration counts drift due to hidden retries.
