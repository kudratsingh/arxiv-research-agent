"""Shared Anthropic Claude LLM client.

Configures the SDK's built-in retry + timeout so 429s and transient 5xxs
don't kill an eval run. See ADR 0009 for the choice of SDK-native retry
over `tenacity` / custom loop, and the rationale for the specific
`MAX_RETRIES` / `REQUEST_TIMEOUT_SEC` values.
"""

import os
import re

import anthropic
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-4-6"

# The anthropic SDK auto-retries on 408 / 409 / 429 and 5xx with exponential
# backoff (starting at 0.5s, doubling, capped at 8s per attempt). MAX_RETRIES
# is retries AFTER the first attempt — so 4 gives up to 5 total attempts.
# Tuned for eval runs that fire ~300 Claude calls; without it, single-run
# rate-limit hits abort the whole benchmark.
MAX_RETRIES = 4

# Request timeout in seconds. Anthropic's SDK default is 10 minutes which is
# far too generous — a stuck request should fail loudly and let the retry
# layer take over. 120s comfortably covers a 4096-token synthesis response.
REQUEST_TIMEOUT_SEC = 120.0

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Get or create the shared Anthropic client (module-level singleton).

    The client bakes in `max_retries` and `timeout` at construction; call
    sites don't need to know about retry policy.
    """
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        _client = anthropic.Anthropic(
            api_key=api_key,
            max_retries=MAX_RETRIES,
            timeout=REQUEST_TIMEOUT_SEC,
        )
    return _client


def call_llm(
    prompt: str,
    system_prompt: str = "",
    model_name: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
) -> str:
    """Call Claude and return the text response.

    Args:
        prompt: The user message.
        system_prompt: System instruction for the model.
        model_name: Claude model to use.
        max_tokens: Maximum output tokens.

    Returns:
        The model's text response, with any markdown code fences stripped.
    """
    client = _get_client()

    response = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        temperature=0.3,
        system=system_prompt if system_prompt else anthropic.NOT_GIVEN,
        messages=[{"role": "user", "content": prompt}],
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
    model_name: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
) -> dict:
    """Call Claude and parse the response as JSON.

    Handles markdown fences and unescaped control characters in string values.

    Args:
        prompt: The user message.
        system_prompt: System instruction for the model.
        model_name: Claude model to use.
        max_tokens: Maximum output tokens.

    Returns:
        Parsed JSON dict.
    """
    import json

    raw = call_llm(prompt, system_prompt, model_name, max_tokens)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw, strict=False)
