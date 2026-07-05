# Multi-Agent Research Assistant for ML/AI Papers

## Project Overview
A multi-agent system that takes a natural language research question about ML/AI, searches arXiv for relevant papers, extracts key findings, synthesizes a research briefing, and self-critiques for quality — orchestrated via LangGraph with Claude as the reasoning engine.

## Design Principles

Every decision in this project — library choice, code structure, testing
strategy, deployment shape — should be made with the intention of shipping
a **production system**, not a demo. Two guiding priorities:

1. **Use what the industry uses.** Pick technologies with community support,
   proven track records, and standard patterns for ML/AI orchestration,
   retrieval, and evaluation. If a choice would look out of place in a
   senior-engineer code review at a real ML/AI company, pick a different one.
   Avoid bespoke / toy / one-off solutions.

2. **Handle thousands of concurrent users from the first production
   milestone.** This is the initial scale target and it shapes everything
   downstream:
   - Concurrent / async I/O by default — parallel LLM calls, non-blocking
     network, thread pools or `asyncio` where appropriate. Never serialize
     work that can safely run in parallel.
   - Statelessness where possible; persistent state belongs in real stores
     (Redis, Postgres, S3-compatible object storage) not local files or
     in-process globals. Local caches are acceptable for dev only.
   - Retries, exponential backoff, and rate-limit handling on every
     external call (Anthropic, arXiv, HuggingFace).
   - Cost-aware LLM usage: prompt caching, batching, token budgets,
     cheaper models for routing / grading where possible.
   - Observability from the start — structured logging, per-node timing,
     tracing. Not bolted on later.
   - Deployment must be horizontally scalable: containerized, no
     process-local state, health checks, graceful shutdown.

When a "simple / quick" option conflicts with a "production-ready" option,
choose production-ready and note the tradeoff. Local shortcuts (e.g. the
current on-disk `.cache/pdfs/` used by the PDF parser) are acceptable
during MVP scaffolding but must be flagged as "replace with shared store
before production" and tracked in the phased plan.

## Tech Stack
- **LLM**: Claude (Anthropic API via `anthropic` Python SDK)
- **Orchestration**: LangGraph (from `langgraph` package)
- **Paper Search**: arXiv API (`arxiv` Python package)
- **PDF Parsing**: PyMuPDF (`fitz`)
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` via HuggingFace
- **Vector Search**: FAISS (`faiss-cpu`)
- **Config**: `python-dotenv` for API keys

## Directory Structure
```
arxiv-research-agent/
├── CLAUDE.md
├── pyproject.toml
├── .env                    # ANTHROPIC_API_KEY (never commit)
├── .env.example
├── src/
│   ├── __init__.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── planner.py      # Decomposes query into sub-questions + search queries
│   │   ├── search.py       # Searches arXiv, ranks by relevance
│   │   ├── reader.py       # Extracts structured findings from papers
│   │   ├── synthesizer.py  # Combines findings into research briefing
│   │   └── critic.py       # Evaluates draft, decides if revision needed
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── arxiv_search.py # arXiv API wrapper
│   │   ├── pdf_parser.py   # PDF download + text extraction
│   │   └── embeddings.py   # HuggingFace embeddings + FAISS ranking
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py        # ResearchState TypedDict
│   │   └── workflow.py     # LangGraph wiring + conditional edges
│   ├── eval/
│   │   ├── __init__.py
│   │   ├── metrics.py      # Faithfulness, completeness, citation accuracy
│   │   └── test_queries.py # Benchmark queries
│   └── main.py             # Entry point
├── tests/
│   └── __init__.py
├── outputs/                # Generated reports
└── README.md
```

## Architecture

```
User Query → PLANNER → SEARCH → READER → SYNTHESIZER → CRITIC → Output
                ↑                              ↑            │
                └──────────── RE-ROUTE ←───────┘────────────┘
                          (on critique failure, max 3 iterations)
```

### Shared State Schema

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class ResearchState(TypedDict):
    query: str
    sub_questions: list[str]
    search_queries: list[str]
    papers: list[dict]           # {id, title, authors, abstract, url, pdf_url}
    paper_analyses: list[dict]   # {paper_id, key_findings, methodology, limitations}
    draft_report: str
    citations: list[dict]
    critique: str
    quality_score: float         # 0-1
    revision_needed: bool
    revision_target: str         # "planner" | "search" | "synthesizer"
    iteration: int               # max 3 revisions
    messages: Annotated[list, add_messages]
```

## Agent Specs

### Planner
- Input: raw user query
- Output: 2-4 sub_questions + search_queries
- Considers: methods, theory, applications, benchmarks, temporal scope

### Search
- Uses arxiv Python package to search
- Deduplicates by paper ID across sub-queries
- Ranks by embedding similarity (query vs abstracts) using FAISS
- Caps at 8-10 papers

### Reader
- Phase 1 (MVP): abstracts + intros only
- Phase 2: full PDF parsing with PyMuPDF, chunked extraction
- Output per paper: {paper_id, title, key_findings, methodology, results_summary, limitations, relevance}

### Synthesizer
- Groups findings by theme/approach
- Compares methodologies and results
- Identifies consensus, contradictions, gaps
- Cites papers as [Author, Year]
- Output: structured markdown report

### Critic
- Scores on: completeness, accuracy, coherence, depth, balance (each 0-1)
- Average >= 0.7 → approve
- Below 0.7 → reject with feedback + revision_target:
  - Missing coverage → route to planner
  - Too few papers → route to search
  - Weak synthesis → route to synthesizer

## LangGraph Wiring

```python
workflow = StateGraph(ResearchState)
workflow.add_node("planner", planner_agent)
workflow.add_node("search", search_agent)
workflow.add_node("reader", reader_agent)
workflow.add_node("synthesizer", synthesizer_agent)
workflow.add_node("critic", critic_agent)

workflow.set_entry_point("planner")
workflow.add_edge("planner", "search")
workflow.add_edge("search", "reader")
workflow.add_edge("reader", "synthesizer")
workflow.add_edge("synthesizer", "critic")

# Conditional routing from critic
workflow.add_conditional_edges("critic", route_after_critique, {
    "planner": "planner",
    "search": "search",
    "synthesizer": "synthesizer",
    END: END,
})
```

## Phased Build Plan

### Phase 1: MVP (current)
- All 5 agents working end-to-end
- Abstracts only (no PDF parsing)
- Critic loop with conditional routing
- Iteration cap at 3 revisions
- Test with 3 example queries

### Phase 2: Depth
- Full-text PDF ingestion
  - `tools/pdf_parser.py`: download from `pdf_url`, extract text with PyMuPDF
  - Handle download failures / non-PDF responses gracefully
  - Cache parsed PDFs on disk to avoid re-download across runs
- Section-aware chunking
  - Detect headers (Introduction, Method, Results, Conclusion, Limitations)
  - Chunk by section, then by token budget within each section
- FAISS relevance ranking on chunks
  - Rank chunks against sub-questions (not just abstract vs query)
  - Feed top-K chunks per paper into reader instead of raw abstract
- Enriched reader output
  - Distinguish claims sourced from method vs results vs limitations
  - Optional: extract references to tables/figures
- Comparative tables in synthesis
  - Method-by-method matrix (dataset, metric, headline result)
- Robustness
  - Retry / backoff on Anthropic 429s
  - Graceful degradation when PDF unavailable (fall back to abstract)

### Phase 3: Polish
- Eval pipeline (`src/eval/`)
  - `test_queries.py`: 5-10 benchmark queries with expected coverage
  - `metrics.py`: faithfulness (claims traceable to sources), completeness
    (coverage of sub-questions), citation accuracy (paper IDs match text)
  - Batch-run the agent and produce an eval report
- Observability
  - Structured logging of each agent's inputs/outputs
  - Per-node timing
- UX
  - Streaming output via LangGraph `astream`
  - Interrupt after planner for human-in-the-loop plan approval
  - Node-level progress prints
- Caching
  - Cache paper embeddings by paper_id
  - Cache reader analyses by (paper_id, query) tuple
- Export
  - Markdown to PDF via pandoc or weasyprint
  - BibTeX export of citations

## Conventions
- Use `anthropic` SDK directly for Claude API calls (not langchain-anthropic)
- All agents are pure functions: take ResearchState, return partial state updates
- Use `python-dotenv` to load ANTHROPIC_API_KEY from .env
- Type hints on everything
- Docstrings on all public functions
- Keep agent system prompts in the agent files (not separate config)

## Development Workflow

We follow standard enterprise practice: every differential piece of work
(a feature, a bug fix, a refactor, a doc update, a test addition) lands
via its own commit on a feature branch and its own PR against `main`.
No direct pushes to `main`.

Branch naming: `<type>/<slug>` — e.g. `feat/pdf-parser`,
`fix/arxiv-timeout`, `docs/readme`, `chore/deps-bump`,
`test/critic-routing`.

PR requirements:
- One logical change per PR — do not bundle unrelated edits.
- Title is concise and describes what changed (under 70 chars).
- Body explains the *why* (motivation, tradeoffs), links related issues,
  and includes a short test plan.
- Tests and `mypy src/` must pass locally before opening the PR.
- Squash-merge to keep `main` history linear and each PR a single commit.

Scope rule of thumb: if you can't summarize the change in one sentence
without using "and", split it.

## Commands
```bash
# Run the agent
python -m src.main "What are the latest approaches to reducing hallucination in LLMs?"

# Run tests
pytest tests/

# Check types
mypy src/
```

## Current Status
- [x] Project scaffolded
- [x] State schema defined
- [x] Planner agent implemented
- [x] Search agent implemented (live arXiv + mock-data fallback)
- [x] Reader agent implemented (abstracts, parallelized per-paper LLM calls)
- [x] Synthesizer agent implemented
- [x] Critic agent implemented
- [x] LangGraph workflow wired
- [x] Anthropic Claude migration complete (from Groq / Gemini)
- [x] Smoke tests for pure functions (dedupe, critic routing)
- [x] README
- [ ] End-to-end test passing
- [ ] Phase 2: PDF parsing
- [ ] Phase 3: Eval pipeline
