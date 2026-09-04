"""Shared Anthropic Claude LLM client.

All tunables (model, retry policy, timeout) come from `src.config.settings`
so runtime behavior is one env-var away rather than a code edit. Every
successful call records into the per-run cost accumulator (ADR 0012);
see ADR 0009 for the SDK-native retry choice and ADR 0011 for the
config approach.

ADR 0051 makes this module the enforcement and visibility choke point
for spend, because it is the one place *every* entry point — CLI,
eval campaign, API job — funnels its LLM calls through:

- **Ceiling.** `call_llm` checks the run's accumulated spend against
  `settings.max_cost_usd` before issuing a call. The API runner's
  between-nodes check (ADR 0033) stays as the earlier, coarser stop;
  this one binds on the sync paths that had no ceiling at all, and
  stops a single node's parallel fan-out from overshooting by its
  whole spend.
- **Retry visibility.** Calls go through `with_raw_response`, whose
  `retries_taken` is the SDK's own count of attempts it threw away
  before the one that returned. No app-level retry loop is added — the
  SDK's is still the only one — but its work is now logged and
  counted.
- **Bounded call chain.** `max_retries x timeout` is clamped so one
  flaky call cannot eat a whole API job's timeout budget.

ADR 0066 adds the fourth thing this choke point is good for: it is the
only place a model call can become a **span**. Before it did, the
largest latency contributor in the system was invisible to tracing —
this module recorded a call but opened no span, so a node that spent 90
seconds waiting on Anthropic showed only as a node that spent 90
seconds. The span is wrapped *around* `record_llm_call` rather than
replacing any part of it, so cost stays single-sourced in
`src.observability.costs` and this module still owns none of it.
"""

from __future__ import annotations

import re
import time
from typing import Any, Final, cast

import anthropic

from src.cancellation import check_cancelled
from src.config import settings
from src.observability import record_llm_call
from src.observability.costs import current_costs, effective_cost_cap, enforce_cost_cap
from src.observability.logging import get_logger
from src.observability.metrics import (
    record_genai_client_call,
    record_llm_upstream_error,
)
from src.observability.semconv import (
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_ID,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    GEN_AI_USAGE_CACHE_WRITE_INPUT_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
)
from src.observability.tracing import llm_span, note_inference_call

log = get_logger(__name__)

#: Sampling temperature every call is issued with. A constant rather
#: than a literal inside the request body because
#: `gen_ai.request.temperature` on the span has to report what was
#: actually sent — a span attribute that can drift from the request it
#: describes is worse than no attribute at all.
_TEMPERATURE: Final = 0.3

#: `server.address` when the client cannot be asked for one. The
#: fallback exists because the client singleton is replaced wholesale
#: by test doubles that emulate `messages.with_raw_response.create` and
#: nothing else — an observability attribute must not be able to fail a
#: test that has no opinion about it. Every real deployment resolves
#: the host from the SDK client, including one pointed at a proxy.
_DEFAULT_SERVER_ADDRESS: Final = "api.anthropic.com"


def _server_address(client: anthropic.Anthropic) -> str:
    """The provider host this client talks to, for `server.address`."""
    host = getattr(getattr(client, "base_url", None), "host", None)
    return host if isinstance(host, str) and host else _DEFAULT_SERVER_ADDRESS


def _describes(source: object, field: str) -> str | None:
    """Read a field that only *describes* the call, never one it needs.

    The line this draws is the point. `usage.input_tokens` and
    `content` are read directly and must be there: cost accounting and
    the returned text depend on them, so a response missing either is
    genuinely broken and should fail loudly. `id`, `model` and
    `stop_reason` are read only to put `gen_ai.response.*` on a span —
    nothing the caller receives depends on them — and an observability
    read must never be able to fail the call it is observing. An SDK
    upgrade that renames `stop_reason` should cost one absent span
    attribute, not every model response in the fleet.

    Args:
        source: The parsed response.
        field: Attribute name.

    Returns:
        The value when it is a non-empty string, else `None`.
    """
    value = getattr(source, field, None)
    return value if isinstance(value, str) and value else None

# Back-compat re-exports so existing callers (`from src.llm import DEFAULT_MODEL`)
# keep working while we migrate to `settings.anthropic_model` at call sites.
DEFAULT_MODEL = settings.anthropic_model
MAX_RETRIES = settings.anthropic_max_retries
REQUEST_TIMEOUT_SEC = settings.anthropic_timeout_sec

# Fraction of `api_job_timeout_sec` that one LLM call chain may claim.
# A job makes tens of calls, so letting a single one consume the whole
# budget guarantees the job dies with nothing to show; at 0.75 the
# default settings give 3 attempts x 120s = 360s of request time plus at
# most 2 x 60s of `retry-after` backoff = 480s, inside the 600s job
# timeout with room for the rest of the graph (ADR 0051).
_CALL_CHAIN_BUDGET_FRACTION = 0.75

_client: anthropic.Anthropic | None = None


def _retry_envelope() -> tuple[int, float]:
    """Return `(max_retries, timeout_sec)` whose worst case fits a job.

    The SDK applies `timeout` **per attempt**, not per call chain
    (`_base_client._build_request` rebuilds the request, timeout and
    all, on every retry), so the worst-case request time for one
    logical call is `(max_retries + 1) * timeout`. At the shipped
    defaults that is 5 x 120s = 600s — exactly `api_job_timeout_sec`,
    meaning one unlucky call could consume an entire job's budget and
    the job would fail with no report (ADR 0051).

    Attempts are trimmed rather than the per-attempt timeout, because a
    shorter timeout would abandon *slow but healthy* generations —
    which costs money twice, since an abandoned attempt is billed by
    Anthropic and reported by nobody (`usage` exists only on a 2xx).

    Returns:
        The retry count and per-attempt timeout to construct the client
        with. Never returns fewer than 0 retries, and never changes the
        configured timeout.
    """
    timeout_sec = settings.anthropic_timeout_sec
    configured_retries = settings.anthropic_max_retries
    budget_sec = settings.api_job_timeout_sec * _CALL_CHAIN_BUDGET_FRACTION
    # At least one attempt always survives: a timeout larger than the
    # whole budget is an operator's explicit choice and refusing to call
    # at all would be a worse answer than one long attempt.
    affordable_attempts = max(1, int(budget_sec // timeout_sec))
    max_retries = min(configured_retries, affordable_attempts - 1)
    return max_retries, timeout_sec


def _get_client() -> anthropic.Anthropic:
    """Get or create the shared Anthropic client (module-level singleton).

    Retry policy and timeout are baked in at construction from
    `settings` (clamped by `_retry_envelope`); call sites don't need to
    know about them.
    """
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        max_retries, timeout_sec = _retry_envelope()
        _client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            max_retries=max_retries,
            timeout=timeout_sec,
        )
        # Logged once per process, at client construction: the worst
        # case is a number an operator needs when reading a timed-out
        # job, and it is not derivable from the env vars alone once the
        # clamp has been applied. WARNING rather than INFO when the
        # clamp actually bites — silently ignoring an explicit
        # `ANTHROPIC_MAX_RETRIES` is the kind of override that costs an
        # afternoon to discover (ADR 0051).
        payload = {
            "model": settings.anthropic_model,
            "timeout_sec": timeout_sec,
            "max_retries": max_retries,
            "configured_max_retries": settings.anthropic_max_retries,
            "worst_case_request_sec": (max_retries + 1) * timeout_sec,
            "api_job_timeout_sec": settings.api_job_timeout_sec,
        }
        if max_retries < settings.anthropic_max_retries:
            log.warning("llm_retry_budget_clamped", extra=payload)
        else:
            log.info("llm_client_configured", extra=payload)
    return _client


def _check_cost_budget() -> None:
    """Raise `CostBudgetExceeded` when this run has already hit its cap.

    No accumulator bound means no run is being tracked (a unit test, an
    ad-hoc script) — there is nothing to measure against, so behaviour
    is unchanged for those callers, exactly as `record_llm_call`
    already no-ops for them.

    Checked *before* the call, not after: the point is to not spend the
    next dollar, and the accumulator can only ever be behind by calls
    that are still in flight.
    """
    costs = current_costs()
    if costs is None:
        return
    enforce_cost_cap(costs, effective_cost_cap(settings.max_cost_usd))


def _build_system_param(
    system_prompt: str, cache_system: bool
) -> Any:
    """Return the `system` argument for the Anthropic Messages API.

    Plain-string path preserves Sprint 1 behavior exactly. Cache path
    (ADR 0022) wraps the prompt in a single content block with an
    `ephemeral` cache marker so Anthropic caches the tokens for 5
    minutes and bills subsequent hits at 10% of the input rate. The
    5-minute TTL is a fit for the reader's per-run parallel fan-out
    and the supervisor's per-run loop; longer-lived caching would
    need the `1h` beta which we're not opting into here.
    """
    if not system_prompt:
        return anthropic.NOT_GIVEN
    if not cache_system:
        return system_prompt
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def call_llm(
    prompt: str,
    system_prompt: str = "",
    model_name: str | None = None,
    max_tokens: int = 4096,
    cache_system: bool = False,
) -> str:
    """Call Claude and return the text response.

    Args:
        prompt: The user message.
        system_prompt: System instruction for the model.
        model_name: Claude model to use. Defaults to `settings.anthropic_model`.
        max_tokens: Maximum output tokens.
        cache_system: When True, mark the system prompt for Anthropic's
            ephemeral prompt cache (ADR 0022). Content below the
            per-model cache minimum silently doesn't cache; content
            above it is billed at 10% on subsequent hits within 5
            minutes. Default False preserves Sprint 1 baseline.

    Returns:
        The model's text response, with any markdown code fences stripped.

    Raises:
        JobCancelledError: When the calling job's cancel token is
            already set. This is the checkpoint that actually stops the
            spend on a timed-out job (ADR 0047) — a node thread cannot
            be killed, so the abort has to happen between calls, and
            this is the only place every agent's calls funnel through.
        CostBudgetExceeded: When the run's accumulated spend has
            reached `settings.max_cost_usd` (ADR 0051). Only when a
            cost accumulator is bound: an untracked caller has no
            budget to exceed and is left alone.
    """
    # Before `_get_client`, not after: a cancelled job must not even
    # construct the client on a cold process. Cancellation outranks the
    # budget — an abandoned job's spend does not matter.
    check_cancelled()
    _check_cost_budget()
    client = _get_client()
    resolved_model = model_name or settings.anthropic_model

    # The span opens here, not around the whole function: everything
    # above it is a local guard that spends nothing and reaches no
    # provider, and a `chat` span covering a cancellation check would
    # report latency the model never took.
    with llm_span(
        model=resolved_model,
        max_tokens=max_tokens,
        temperature=_TEMPERATURE,
        server_address=_server_address(client),
    ) as span:
        # Counted before the call, so an attempt that raises still
        # counts against the enclosing agent invocation — the
        # conventions are explicit that failed inference calls count,
        # because an agent that burned four attempts did four
        # inferences whatever came back.
        note_inference_call()
        started = time.monotonic()
        try:
            # `with_raw_response` rather than a plain `create`: the parsed
            # `Message` carries no retry information, while the raw
            # response exposes the SDK's own `retries_taken` and the
            # `request-id`. That is the whole retry-visibility fix — it
            # reports what the SDK already did rather than adding a second
            # retry loop on top of it (ADR 0051).
            raw = client.messages.with_raw_response.create(
                model=resolved_model,
                max_tokens=max_tokens,
                temperature=_TEMPERATURE,
                system=_build_system_param(system_prompt, cache_system),
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIStatusError as exc:
            # The SDK has already exhausted `max_retries` by the time this
            # escapes, so every one of those attempts is otherwise
            # invisible: no usage to record (`usage` exists only on a 2xx
            # body) and, before ADR 0051, no line and no metric either.
            _log_upstream_error(
                resolved_model,
                status=str(exc.status_code),
                request_id=exc.request_id,
                started=started,
            )
            _record_failed_call(resolved_model, exc, started)
            raise
        except anthropic.APIConnectionError as exc:
            # Includes `APITimeoutError` — a client-side timeout is a
            # subclass, and the SDK retries it like any connection error.
            _log_upstream_error(
                resolved_model,
                status="connection",
                request_id=None,
                started=started,
                detail=type(exc).__name__,
            )
            _record_failed_call(resolved_model, exc, started)
            raise

        elapsed_sec = time.monotonic() - started
        latency_ms = elapsed_sec * 1000
        response = raw.parse()

        # Anthropic's SDK exposes cache-token buckets on `usage`. They're 0
        # (or absent) when caching wasn't requested or the request missed
        # the cache. `input_tokens` from the SDK already excludes cached
        # tokens on a hit — the three buckets are additive.
        cache_read = int(getattr(response.usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(
            getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        )

        # Conventional response and usage attributes, on the span that
        # measured the call. Anthropic's two prompt-cache buckets
        # (ADR 0022) have conventional names of their own, so nothing
        # here needs a private one.
        #
        # The three *descriptive* fields go through `_describes`; the
        # token counts do not. See `_describes` for why that line is
        # where it is.
        response_id = _describes(response, "id")
        response_model = _describes(response, "model")
        finish_reason = _describes(response, "stop_reason")
        if response_id is not None:
            span.set_attribute(GEN_AI_RESPONSE_ID, response_id)
        if response_model is not None:
            span.set_attribute(GEN_AI_RESPONSE_MODEL, response_model)
        if finish_reason is not None:
            span.set_attribute(GEN_AI_RESPONSE_FINISH_REASONS, [finish_reason])
        span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, response.usage.input_tokens)
        span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, response.usage.output_tokens)
        span.set_attribute(GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS, cache_read)
        span.set_attribute(GEN_AI_USAGE_CACHE_WRITE_INPUT_TOKENS, cache_write)
        record_genai_client_call(
            request_model=resolved_model,
            response_model=response_model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            duration_sec=elapsed_sec,
            error_type=None,
        )

        return _finish_call(
            response,
            resolved_model,
            cache_read=cache_read,
            cache_write=cache_write,
            latency_ms=latency_ms,
            retries=raw.retries_taken,
        )


def _record_failed_call(
    model: str, exc: BaseException, started: float
) -> None:
    """Record the conventional duration histogram for a failed call.

    `usage` exists only on a 2xx body, so a failed call has no tokens
    to report — but it very much has a duration, and it is the duration
    an on-call engineer cares most about, because a call that spent
    eight minutes exhausting retries before failing is a different
    incident from one that failed instantly.
    """
    record_genai_client_call(
        request_model=model,
        response_model=None,
        input_tokens=None,
        output_tokens=None,
        duration_sec=time.monotonic() - started,
        error_type=type(exc).__name__,
    )


def _finish_call(
    response: anthropic.types.Message,
    model: str,
    *,
    cache_read: int,
    cache_write: int,
    latency_ms: float,
    retries: int,
) -> str:
    """Record the call's cost and return its text, fences stripped.

    Split out of `call_llm` so the span body above reads as one
    sequence — issue, observe, account, return — rather than nesting
    the whole accounting and parsing tail one level deeper inside the
    `with`.
    """
    record_llm_call(
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        latency_ms=latency_ms,
        # Read off the typed SDK surface by the caller rather than
        # `getattr`, so an upgrade that removes the field fails mypy
        # there instead of quietly reporting zero retries forever
        # (ADR 0051).
        retries=retries,
    )

    text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    return stripped


def _log_upstream_error(
    model: str,
    *,
    status: str,
    request_id: str | None,
    started: float,
    detail: str | None = None,
) -> None:
    """Log + count one LLM call that failed after the SDK gave up.

    Deliberately does not swallow anything — the caller re-raises. Its
    only job is to make sure the failure leaves a structured trace with
    the fields an on-call engineer needs to take it to Anthropic: the
    status, the request id, and how long the whole chain burned before
    giving up.

    Args:
        model: Model id the failed call targeted.
        status: HTTP status as a string, or `"connection"`.
        request_id: Anthropic's `request-id`, when the call got a
            response at all.
        started: `time.monotonic()` from before the first attempt.
        detail: Exception class name, for the connection case where
            there is no status to distinguish a timeout from a reset.
    """
    record_llm_upstream_error(model=model, status=status)
    log.warning(
        "llm_upstream_error",
        extra={
            "model": model,
            "status": status,
            "request_id": request_id,
            "detail": detail,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        },
    )


def call_llm_json(
    prompt: str,
    system_prompt: str = "",
    model_name: str | None = None,
    max_tokens: int = 4096,
    cache_system: bool = False,
) -> dict[str, Any]:
    """Call Claude and parse the response as JSON.

    Handles markdown fences and unescaped control characters in string values.

    Args:
        prompt: The user message.
        system_prompt: System instruction for the model.
        model_name: Claude model to use. Defaults to `settings.anthropic_model`.
        max_tokens: Maximum output tokens.
        cache_system: When True, mark the system prompt for Anthropic's
            ephemeral prompt cache (ADR 0022). See `call_llm`.

    Returns:
        Parsed JSON dict.
    """
    import json

    raw = call_llm(
        prompt, system_prompt, model_name, max_tokens, cache_system=cache_system
    )

    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        return cast(dict[str, Any], json.loads(raw, strict=False))
