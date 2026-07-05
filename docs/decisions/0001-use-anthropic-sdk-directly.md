# 0001. Use the Anthropic SDK directly, not LangChain's wrapper

- **Status**: accepted
- **Date**: 2026-07-05

## Context

The workflow is orchestrated with LangGraph, whose ecosystem includes
`langchain-anthropic` — a wrapper that exposes Claude through the
LangChain `ChatModel` interface. We need a way to call Claude from
each of the five agents (planner, search, reader, synthesizer, critic).
The initial scaffold used Groq, and before that Gemini; we standardized
on Anthropic Claude during the MVP polish pass.

## Decision

Call `anthropic.Anthropic().messages.create(...)` directly. All shared
LLM logic lives in `src/llm.py`, exposing two helpers:
`call_llm(prompt, system_prompt, model_name, max_tokens)` and
`call_llm_json(...)`. Agents call these helpers — never the SDK
directly.

## Alternatives considered

- **`langchain-anthropic`** — provides the LangChain `ChatModel`
  interface. Rejected: adds an indirection layer without buying
  anything we need. We do not use LangChain's chains, callbacks, or
  runnables — only the LangGraph state graph, which does not require
  ChatModel-compatible providers.
- **Raw HTTP via `requests`** — rejected: reinvents SDK ergonomics
  (retries, streaming, typed responses, prompt caching support) with
  no upside.
- **Multiple SDKs in parallel (e.g. Anthropic + OpenAI)** — deferred.
  Adds complexity we don't currently need. If cost / latency demands
  a mix later, revisit with a new ADR.

## Consequences

- **Positive**:
  - Direct access to Anthropic SDK features (prompt caching, extended
    thinking, tool use) without waiting for LangChain to expose them.
  - Fewer moving parts, fewer version-compat conflicts.
  - Clean call sites — agents call `call_llm_json()`, not a chained
    Runnable.
- **Negative**:
  - We reimplement retry/backoff and streaming ourselves when we need
    them.
- **Follow-ups**:
  - Add Anthropic-native retry/backoff on 429s and 5xx (tracked as
    `feat/anthropic-retry` in Phase 2 robustness).
  - Add prompt caching to reduce cost on repeated system prompts
    (planner / synthesizer / critic all reuse long system prompts).
