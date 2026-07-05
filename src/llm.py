"""Shared Anthropic Claude LLM client."""

import os
import re

import anthropic
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-4-6"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Get or create the Anthropic client."""
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        _client = anthropic.Anthropic(api_key=api_key)
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
