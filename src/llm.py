"""Shared Anthropic Claude LLM client.

All tunables (model, retry policy, timeout) come from `src.config.settings`
so runtime behavior is one env-var away rather than a code edit. Every
successful call records into the per-run cost accumulator (ADR 0012);
see ADR 0009 for the SDK-native retry choice and ADR 0011 for the
config approach.
"""

import re

import anthropic

from src.config import settings
from src.observability import record_llm_call

# Back-compat re-exports so existing callers (`from src.llm import DEFAULT_MODEL`)
# keep working while we migrate to `settings.anthropic_model` at call sites.
DEFAULT_MODEL = settings.anthropic_model
MAX_RETRIES = settings.anthropic_max_retries
REQUEST_TIMEOUT_SEC = settings.anthropic_timeout_sec

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Get or create the shared Anthropic client (module-level singleton).

    Retry policy and timeout are baked in at construction from
    `settings`; call sites don't need to know about them.
    """
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        _client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            max_retries=settings.anthropic_max_retries,
            timeout=settings.anthropic_timeout_sec,
        )
    return _client


def _build_system_param(
    system_prompt: str, cache_system: bool
) -> str | list[dict] | object:
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
    """
    client = _get_client()
    resolved_model = model_name or settings.anthropic_model

    response = client.messages.create(
        model=resolved_model,
        max_tokens=max_tokens,
        temperature=0.3,
        system=_build_system_param(system_prompt, cache_system),
        messages=[{"role": "user", "content": prompt}],
    )

    # Anthropic's SDK exposes cache-token buckets on `usage`. They're 0
    # (or absent) when caching wasn't requested or the request missed
    # the cache. `input_tokens` from the SDK already excludes cached
    # tokens on a hit — the three buckets are additive.
    cache_read = int(getattr(response.usage, "cache_read_input_tokens", 0) or 0)
    cache_write = int(
        getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    )

    record_llm_call(
        model=resolved_model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )

    text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    return stripped


def call_llm_json(
    prompt: str,
    system_prompt: str = "",
    model_name: str | None = None,
    max_tokens: int = 4096,
    cache_system: bool = False,
) -> dict:
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
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw, strict=False)
