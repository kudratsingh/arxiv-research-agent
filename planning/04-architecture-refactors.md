# Architecture Refactors

Concrete refactors that unlock the roadmap, mapped to current files. These are non-breaking additions — do them incrementally as part of Sprint 1/2.

## 1. `SourceAdapter` protocol

**Where:** new `src/tools/sources/` package.

Abstract `search()` and `fetch()` so arXiv, Semantic Scholar, OpenReview all conform. `arxiv_search.py` becomes one adapter. Unblocks feature #1 (multi-source retrieval) and #2 (citation graph traversal).

## 2. `LLMClient` wrapper

**Where:** new `src/llm/client.py` (there is already an `src/llm.py` to fold in).

Wraps `anthropic` SDK and centralizes:
- retries + backoff
- token/cost tracking
- prompt caching
- model selection (Haiku / Sonnet / Opus)

All agents call `self.llm.complete(...)` instead of the raw SDK. Enables swapping providers later (Bedrock, Vertex).

## 3. `ResearchState` — additive fields

**Where:** `src/graph/state.py`.

Add without breaking existing agents:
- `run_id: str`
- `user_id: str | None`
- `budget_remaining_usd: float | None`
- `trace_id: str | None`
- `source_provenance: list[dict]` — per-finding paper+page+chunk pointer
- `errors: list[dict]`

Consumed by observability, cost tracking, and provenance features.

## 4. `BaseAgent` class

**Where:** new `src/agents/base.py`.

Currently agents are free functions. A tiny class gives a clean hook for tracing, cost tracking, and metrics per agent:

```python
class BaseAgent:
    name: str
    llm: LLMClient
    logger: Logger
    metrics: MetricsSink
    def __call__(self, state: ResearchState) -> dict: ...
```

Existing agent functions can be kept as thin wrappers around a class instance during migration.

## 5. Split `graph/workflow.py`

**Where:** `src/graph/workflow.py` → `workflow.py` (wiring) + `routing.py` (conditional edges + max-iteration guard).

Iteration cap is documented in `CLAUDE-Agent-Proj-1.md` but not enforced in code — this refactor is the natural place to add it.

## 6. Fill in `src/eval/`

**Where:** existing `src/eval/` package.

Structure:
- `datasets/` — golden queries + expected paper sets
- `metrics/` — recall@k, MRR, faithfulness (LLM-judge), citation accuracy, completeness, coherence
- `runners/` — orchestrates a golden-set run
- Pytest fixture that runs the golden set as a marked-slow test

## 7. `outputs/` schema

**Where:** `outputs/` directory (currently drops `.md` files only).

Save alongside each report:
- `run_id.md` — the report
- `run_id.json` — full `ResearchState` + trace + cost breakdown

Then reports become reproducible and inspectable, and become fodder for the eval harness.
