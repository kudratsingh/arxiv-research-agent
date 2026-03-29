"""Shared Groq LLM client."""

import os
import re

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_client: Groq | None = None


def _get_client() -> Groq:
    """Get or create the Groq client."""
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        _client = Groq(api_key=api_key)
    return _client


def call_llm(
    prompt: str,
    system_prompt: str = "",
    model_name: str = "llama-3.3-70b-versatile",
    max_tokens: int = 4096,
) -> str:
    """Call Groq and return the text response.

    Args:
        prompt: The user message.
        system_prompt: System instruction for the model.
        model_name: Model to use.
        max_tokens: Maximum output tokens.

    Returns:
        The model's text response.
    """
    client = _get_client()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.3,
    )

    text = response.choices[0].message.content or ""

    # Strip markdown code fences if present (```json ... ```)
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    return stripped


def call_llm_json(
    prompt: str,
    system_prompt: str = "",
    model_name: str = "llama-3.3-70b-versatile",
    max_tokens: int = 4096,
) -> dict:
    """Call Groq and parse the response as JSON.

    Handles markdown fences and control characters that break json.loads.

    Args:
        prompt: The user message.
        system_prompt: System instruction for the model.
        model_name: Model to use.
        max_tokens: Maximum output tokens.

    Returns:
        Parsed JSON dict.
    """
    import json

    raw = call_llm(prompt, system_prompt, model_name, max_tokens)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Handle unescaped control characters (newlines inside JSON strings)
        return json.loads(raw, strict=False)
