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
- **A typed failure.** When the SDK gives up, the exception leaves this
  module as `errors.UpstreamModel` (`upstream_model`) rather than as an
  `anthropic.*` class that the runner's generic handler could only
  record as `internal_unexpected`. A provider outage is the most likely
  upstream failure this system has and it now says so in
  `research_jobs_total{error_type}` (WO-A17).

ADR 0066 adds the fourth thing this choke point is good for: it is the
only place a model call can become a **span**. Before it did, the
largest latency contributor in the system was invisible to tracing —
this module recorded a call but opened no span, so a node that spent 90
seconds waiting on Anthropic showed only as a node that spent 90
seconds. The span is wrapped *around* `record_llm_call` rather than
replacing any part of it, so cost stays single-sourced in
`src.observability.costs` and this module still owns none of it.

ADR 0077 makes the request itself model-aware, and for the same reason
everything else here is centralised: this is the one place a request
body is built. Before it, `temperature=0.3` went out on every call to
every model — correct for `claude-sonnet-4-6`, an HTTP 400 on every
call the day the model id moves to Opus 4.7 or later. What may be sent
now comes from `src.llm_models`' capability table and the operator's
`Settings`, resolved into a frozen `RequestProfile` per call; a feature
is sent only when it is *both* enabled and supported. Every one of
those settings defaults to what this module already did, so a default
deployment sends the request body `tests/test_llm_request_golden.py`
pinned before any of this landed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Final, cast

import anthropic
import pydantic

from src.cancellation import check_cancelled
from src.config import settings
from src.errors import UpstreamModel, UpstreamModelOutput
from src.llm_models import capabilities_for
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

    This is the one place in `src/` that unwraps
    `settings.anthropic_api_key`. The field is a `SecretStr` (WO-C4),
    and the rule `src/config.py` states is followed here literally:
    `get_secret_value()` once, into a local, straight into the SDK
    constructor. The unwrapped string is never logged, never
    interpolated and never put in `payload` below — an `api_key` that
    reached that dict would be one `log.info` away from the stream.
    Testing the local rather than the wrapper also keeps the emptiness
    check honest: `bool(SecretStr(...))` happens to answer correctly
    today via `__len__`, but that is pydantic's implementation detail
    and not something a spend guard should rest on.
    """
    global _client
    if _client is None:
        api_key = settings.anthropic_api_key.get_secret_value()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        max_retries, timeout_sec = _retry_envelope()
        _client = anthropic.Anthropic(
            api_key=api_key,
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


@dataclass(frozen=True, slots=True)
class RequestProfile:
    """What one call is allowed to send, after settings meet the model.

    Every field is already the *answer*, not an input to one: `None` and
    `""` mean "do not send this field at all", so the kwargs builder
    below is a transcription rather than a second place where the
    enabled-and-supported logic could drift. Frozen so a profile cannot
    be edited between being resolved and being sent — the span reports
    it, and an attribute that can drift from the request it describes is
    worse than no attribute at all.
    """

    #: The model id this profile was resolved against.
    model: str
    #: `temperature` to send, or `None` to send none.
    temperature: float | None
    #: Whether to send `thinking={"type": "adaptive"}`.
    adaptive_thinking: bool
    #: `output_config.effort` to send, or `""` to send none.
    effort: str
    #: Whether a caller-supplied schema may be sent as
    #: `output_config.format`. False either because the operator has not
    #: enabled structured outputs or because this model does not take
    #: them — the caller cannot tell the two apart, and does not need
    #: to: both mean "parse the text yourself, as before".
    structured_outputs: bool


def resolve_profile(model: str, agent: str = "") -> RequestProfile:
    """Resolve what may be sent to `model` on behalf of `agent`.

    The conjunction is the whole point: a feature is sent only when the
    operator enabled it **and** the capability row allows it. Enabled
    but unsupported resolves to off here rather than failing at the
    provider — and for thinking and effort it cannot even get this far,
    because `Settings._check_request_profile_is_supported` refuses that
    combination at load (ADR 0077). The redundancy is deliberate: this
    function is also reached with a `model_name` a caller passed
    directly, which no settings validation has ever seen.

    Args:
        model: The resolved model id the request will name.
        agent: One of `src.config.EFFORT_AGENTS`, selecting that
            agent's effort override. Empty takes the deployment-wide
            `llm_effort`.

    Returns:
        The frozen profile for this call.
    """
    caps = capabilities_for(model)
    effort = settings.effort_for(agent)
    return RequestProfile(
        model=model,
        temperature=settings.llm_temperature if caps.sampling_params else None,
        adaptive_thinking=(
            settings.llm_thinking == "adaptive" and caps.adaptive_thinking
        ),
        effort=effort if caps.supports_effort(effort) else "",
        structured_outputs=(
            settings.enable_structured_outputs and caps.structured_outputs
        ),
    )


def _build_request_kwargs(
    *,
    profile: RequestProfile,
    prompt: str,
    system_prompt: str,
    cache_system: bool,
    max_tokens: int,
    schema: type[pydantic.BaseModel] | None,
) -> dict[str, Any]:
    """Assemble the body for `messages.create`, and nothing more.

    Optional fields are *absent* rather than `None`: the SDK
    distinguishes an omitted key from an explicit null, and
    `"temperature": null` is a different request from no temperature at
    all. Building a plain dict rather than threading `anthropic.omit`
    through five call sites also makes the golden fixture a direct
    reading of the wire body.

    `output_config` carries two unrelated things — `effort` and
    `format` — so it is built once from whichever of them applies and
    omitted entirely when neither does.
    """
    kwargs: dict[str, Any] = {
        "model": profile.model,
        "max_tokens": max_tokens,
    }
    if profile.temperature is not None:
        kwargs["temperature"] = profile.temperature
    if profile.adaptive_thinking:
        # `{"type": "adaptive"}` and not the deprecated
        # `{"type": "enabled", "budget_tokens": N}`: the budget form is
        # rejected outright by every model whose row says
        # `adaptive_thinking`, and `display` is left at the API default
        # so no thinking text is requested that this gateway would then
        # have to be careful not to log.
        kwargs["thinking"] = {"type": "adaptive"}

    output_config: dict[str, Any] = {}
    if profile.effort:
        output_config["effort"] = profile.effort
    if schema is not None and profile.structured_outputs:
        # The SDK's own schema transform, reached through the public
        # `anthropic.transform_schema` re-export. It is the same
        # function `client.messages.parse` uses to build this field, so
        # what goes on the wire is what the SDK would have sent — see
        # `call_llm_json` for why `parse` itself is not called.
        output_config["format"] = {
            "type": "json_schema",
            "schema": anthropic.transform_schema(schema),
        }
    if output_config:
        kwargs["output_config"] = output_config

    kwargs["system"] = _build_system_param(system_prompt, cache_system)
    kwargs["messages"] = [{"role": "user", "content": prompt}]
    return kwargs


def call_llm(
    prompt: str,
    system_prompt: str = "",
    model_name: str | None = None,
    max_tokens: int = 4096,
    cache_system: bool = False,
    *,
    agent: str = "",
    schema: type[pydantic.BaseModel] | None = None,
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
        agent: Which agent is calling, for its `<agent>_effort`
            override (ADR 0077). Empty — the default, and what every
            caller passes today — takes the deployment-wide
            `llm_effort`.
        schema: Constrain the model's output to this pydantic model,
            when `enable_structured_outputs` is on and the resolved
            model supports it. The returned text is then JSON matching
            the schema; validating it is `call_llm_json`'s job, not
            this function's.

    Returns:
        The model's text response, with any markdown code fences
        stripped. `thinking` blocks are skipped: the text is the
        concatenation of the `text` blocks only, so enabling thinking
        does not turn every response into an empty string.

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
        UpstreamModel: When the provider refused the call or never
            answered it, after the SDK exhausted its clamped envelope.
            The `anthropic` exception is chained as `__cause__`.
        UpstreamModelOutput: When the response carries no `text` block
            at all — a thinking-only answer, or an empty body. Before
            ADR 0077 that returned `""` and every caller treated the
            silence as content.
    """
    # Before `_get_client`, not after: a cancelled job must not even
    # construct the client on a cold process. Cancellation outranks the
    # budget — an abandoned job's spend does not matter.
    check_cancelled()
    _check_cost_budget()
    client = _get_client()
    resolved_model = model_name or settings.anthropic_model
    profile = resolve_profile(resolved_model, agent)
    request_kwargs = _build_request_kwargs(
        profile=profile,
        prompt=prompt,
        system_prompt=system_prompt,
        cache_system=cache_system,
        max_tokens=max_tokens,
        schema=schema,
    )

    # The span opens here, not around the whole function: everything
    # above it is a local guard that spends nothing and reaches no
    # provider, and a `chat` span covering a cancellation check would
    # report latency the model never took.
    with llm_span(
        model=resolved_model,
        max_tokens=max_tokens,
        # `gen_ai.request.temperature` should be *absent* when no
        # temperature was sent, and it cannot be: `llm_span` takes a
        # required `float` (`src/observability/tracing.py:642`) and sets
        # the attribute unconditionally (`:676`), and
        # `src/observability/**` is fenced for another lane's work
        # orders. So the attribute is truthful on every model that
        # accepts sampling — which is every model this deployment can
        # reach today — and reports the configured-but-unsent value on
        # one that does not. Recorded in ADR 0077's follow-ups; the fix
        # is `float | None` in that signature and a guarded
        # `set_attribute`, and this line becomes
        # `temperature=profile.temperature`.
        temperature=(
            profile.temperature
            if profile.temperature is not None
            else settings.llm_temperature
        ),
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
            raw = client.messages.with_raw_response.create(**request_kwargs)
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
            raise UpstreamModel(
                log_detail=_upstream_detail(exc, status=str(exc.status_code))
            ) from exc
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
            raise UpstreamModel(
                log_detail=_upstream_detail(exc, status="connection")
            ) from exc

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


def _upstream_detail(exc: Exception, *, status: str) -> str:
    """Log-side detail for the `UpstreamModel` an SDK failure becomes.

    The conversion itself is spelled out at both `raise` sites rather
    than returned from here, so the class name is visible in the source
    — `tests/test_errors.py::TestTheJobVocabulary` derives the job's
    error vocabulary by reading `raise` statements, and a code that
    reached the taxonomy through a helper's return type would be
    invisible to it. That is the same reason ADR 0068's dead-letter is a
    separate assignment rather than a defaulted argument.

    Why the conversion happens in this module at all: it is the one
    place every entry point's model calls funnel through, the property
    that already makes it the spend and retry choke point (ADR 0051).
    Before it, an `anthropic.APIStatusError` travelled to the runner's
    generic handler and became `internal_unexpected` — a provider outage
    filed under the code reserved for exceptions nobody predicted.

    Args:
        exc: The SDK exception that escaped the client's own retries.
        status: HTTP status as a string, or `"connection"`.

    Returns:
        The detail string. It names the SDK class and its message, which
        is where the provider's own text is allowed to go: `log_detail`
        reaches the log and `str(exc)` and never a client, while
        `public_message` is the class's fixed sentence.
    """
    return f"{type(exc).__name__}({status}): {exc}"


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

    text = _text_of(response)

    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    return stripped


def _text_of(response: anthropic.types.Message) -> str:
    """Join the response's `text` blocks, and refuse a response with none.

    Two behaviours, and the second is the one ADR 0077 adds.

    **Thinking blocks are skipped, never logged.** With adaptive
    thinking on, the first content block is a `thinking` block, so a
    reader that took `content[0].text` would return the reasoning as
    the answer — and a reader that took `content[0]` blindly would
    return nothing at all. Filtering on `type == "text"` is what makes
    thinking safe to enable. The `thinking` field is never read here
    and never reaches a log line: it is model reasoning, the
    conventions class content capture as opt-in, and this gateway has
    no opt-in.

    **A response with no text block raises.** Before this, a
    thinking-only answer — the shape a truncated or refused generation
    produces once thinking is on — returned `""`, and every caller
    treated the empty string as a legitimate answer: the planner fell
    back to the raw query, the critic approved with a zero score, and
    the run finished `succeeded` having been told nothing. That is the
    failure `UpstreamModelOutput` names, and it costs one branch to say
    so. Cost is recorded before this point, because the call happened
    and Anthropic billed it whatever came back.

    Raises:
        UpstreamModelOutput: When no content block has `type == "text"`.
    """
    texts = [block.text for block in response.content if block.type == "text"]
    if not texts:
        seen = sorted({block.type for block in response.content})
        raise UpstreamModelOutput(
            log_detail=(
                "model response carried no text block; block types: "
                f"{seen or ['<none>']}"
            )
        )
    return "".join(texts)


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
    *,
    agent: str = "",
    schema: type[pydantic.BaseModel] | None = None,
) -> dict[str, Any]:
    """Call Claude and parse the response as JSON.

    Two paths, and which one runs is a property of the deployment
    rather than of the caller. When `enable_structured_outputs` is on,
    the resolved model's row allows it, and `schema` is given, the
    schema goes out as `output_config.format` and the answer is
    validated against it. Otherwise — including for every caller that
    passes no schema — the free-text path runs exactly as it did
    before ADR 0077: `json.loads`, then a `strict=False` retry for
    unescaped control characters, handling markdown fences on the way
    in through `call_llm`.

    **Why not `client.messages.parse`.** The SDK ships a `parse` helper
    that does the schema transform and the validation in one call, and
    it is the documented way to do this. It is not used here because
    `messages.with_raw_response` wraps only `create` and `count_tokens`
    (anthropic 0.116.0, `resources/messages/messages.py`), and this
    gateway reads `retries_taken` off the raw response — that is ADR
    0051's entire retry-visibility fix. Calling `parse` would mean
    either losing it or duplicating the span, cost, and
    exception-mapping block around a second call site. So the schema is
    transformed with the SDK's own public `anthropic.transform_schema`,
    sent through `create`, and validated here with the same pydantic
    model the SDK would have used. What reaches the wire is identical;
    what reaches `record_llm_call` is not.

    Args:
        prompt: The user message.
        system_prompt: System instruction for the model.
        model_name: Claude model to use. Defaults to `settings.anthropic_model`.
        max_tokens: Maximum output tokens.
        cache_system: When True, mark the system prompt for Anthropic's
            ephemeral prompt cache (ADR 0022). See `call_llm`.
        agent: Which agent is calling, for its `<agent>_effort`
            override. See `call_llm`.
        schema: The shape to ask the model for. Ignored — silently, and
            with no change in behaviour — when structured outputs are
            off or unsupported.

    Returns:
        Parsed JSON dict. On the structured path this is the validated
        model's `model_dump()`, which is a superset of what the
        free-text path produced: every field the schema requires is
        present and correctly typed, and the callers' own coercions
        (ADR 0041) still run on top of it unchanged.

    Raises:
        UpstreamModelOutput: On the structured path, when the response
            does not satisfy the schema. The free-text path keeps
            raising `json.JSONDecodeError`, which every caller already
            catches (ADR 0041) — changing that would be a behaviour
            change on the default path.
    """
    import json

    raw = call_llm(
        prompt,
        system_prompt,
        model_name,
        max_tokens,
        cache_system=cache_system,
        agent=agent,
        schema=schema,
    )

    if schema is not None and _structured_output_applies(model_name, agent):
        try:
            return schema.model_validate_json(raw).model_dump()
        except pydantic.ValidationError as exc:
            # The provider answered and the content was unusable, which
            # is exactly the line `UpstreamModelOutput` draws against
            # `UpstreamModel` (ADR 0064). `log_detail` carries the
            # error count and the schema name; the model's own text is
            # not put in it, because a validation failure is most
            # likely to happen on output that is long and may quote the
            # user's content.
            raise UpstreamModelOutput(
                log_detail=(
                    f"structured output failed {schema.__name__} validation "
                    f"with {exc.error_count()} error(s)"
                )
            ) from exc

    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        return cast(dict[str, Any], json.loads(raw, strict=False))


def _structured_output_applies(model_name: str | None, agent: str) -> bool:
    """Whether the call just issued actually carried a schema.

    Re-resolved rather than returned from `call_llm`, so that
    `call_llm`'s signature stays "text in, text out" and this module
    keeps exactly one definition of when a feature is on. The
    resolution is a dict lookup and two boolean reads; the call it
    describes took a network round trip.
    """
    return resolve_profile(
        model_name or settings.anthropic_model, agent
    ).structured_outputs
