# Multi-Agent Research Assistant for ML/AI Papers

## Project Overview
A multi-agent system that takes a natural language research question about ML/AI, searches arXiv for relevant papers, extracts key findings, synthesizes a research briefing, and self-critiques for quality — orchestrated via LangGraph with Claude as the reasoning engine.

## Documentation

Excellent, thorough documentation is a non-negotiable requirement for
this project. Every significant module, agent, tool, and design decision
must be documented so that (a) a new engineer can be productive on day
one and (b) design intent survives contact with future changes.

To keep this file focused, detailed docs live in `docs/`. This file
(`CLAUDE-Agent-Proj-1.md`) is the top-level index — it summarizes the
system, states the principles, and points into `docs/` for anything
that needs more space.

Documentation requirements:
- Every module has a docstring explaining what it does and why.
- Every public function / class has a docstring with Args, Returns, and
  (where relevant) Raises sections.
- Every non-trivial architectural or technical decision gets an ADR in
  `docs/decisions/` (format: `docs/decisions/TEMPLATE.md`).
- Every agent gets a page in `docs/agents/<name>.md` covering inputs,
  outputs, prompt design, and known failure modes.
- Every phase deliverable is tracked in `docs/roadmap.md`.
- Every non-trivial change updates the relevant doc in the **same PR**.
  Doc drift is a bug — the reviewer should request updates if a diff
  changes behavior without changing docs.

## Testing

Every piece of code merged to `main` ships with tests. Untested code
does not merge. Full strategy in `docs/testing.md`. Summary:

- **Test taxonomy** (three tiers, mirroring the standard pyramid):
  - `tests/unit/` — pure functions, no I/O / network / LLM. Fast,
    deterministic. Runs on every PR.
  - `tests/integration/` — external libraries against local fixtures
    (PyMuPDF on a sample PDF, sentence-transformers, canned arXiv XML).
    Runs when the diff touches integration-adjacent code.
  - `tests/e2e/` — full LangGraph workflow with recorded LLM cassettes.
    Runs on merge to `main` and nightly, **not** on individual PRs.
- **Selective per-PR execution**: CI does **not** run the full suite on
  every PR. It selects tests by changed paths plus pytest markers
  (`@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`).
- **Coverage target**: >=80% on unit-testable code.
- **LLM code**: assert on response structure and prompt shape, never
  on exact model output. Cassette-based e2e for pipeline-level checks.

See `docs/testing.md` for how the tiers are wired, how CI selects, and
what "tested" means for non-deterministic code.

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
│   │   ├── pdf_parser.py   # PDF download + text extraction (cached)
│   │   ├── chunker.py      # Section-aware chunker for paper full text
│   │   ├── chunk_ranker.py # FAISS chunk ranking against sub-questions
│   │   └── embeddings.py   # HuggingFace embeddings + FAISS ranking
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py        # ResearchState TypedDict
│   │   └── workflow.py     # LangGraph wiring + conditional edges
│   ├── eval/
│   │   ├── __init__.py
│   │   ├── benchmark_queries.py # Hand-curated eval queries + get_queries()
│   │   ├── metrics.py           # Faithfulness, completeness, citation accuracy
│   │   ├── regression_diff.py   # Baseline-vs-current summary diff for nightly CI
│   │   └── runner.py            # Batch runner + report writer
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── logging.py      # JSON formatter + run_id ContextVar + propagate helper
│   │   └── costs.py        # RunCosts accumulator + price table + record_llm_call
│   ├── config.py           # pydantic-settings typed config surface
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
- Fetches PDF -> section-aware chunks -> FAISS-ranked top-K excerpts
  against sub-questions -> Claude analysis. Falls back to abstract-only
  on any PDF / chunk / rank failure. Per-paper LLM calls run in parallel.
- Output per paper: {paper_id, title, key_findings, methodology, results_summary, limitations, relevance}
- Full details: [`docs/agents/reader.md`](docs/agents/reader.md).

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
- Eval pipeline (`src/eval/`) — full strategy in [`docs/eval.md`](docs/eval.md)
  - `benchmark_queries.py`: 10 hand-curated ML/AI queries with
    `expected_topics` for reference-free scoring (landed)
  - `metrics.py`: faithfulness (per-claim traceability), completeness
    (topic coverage), citation accuracy (regex + set membership)
  - `runner.py`: batch runner, JSONL + markdown reports to
    `outputs/eval/<timestamp>/`
  - Custom in-repo rather than Ragas / DeepEval / LangSmith — see
    [ADR 0005](docs/decisions/0005-custom-eval-over-ragas.md)
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

We land work on feature branches and open PRs against `main` — no
direct pushes to `main`.

Branch naming: `<type>/<slug>` — e.g. `feat/pdf-parser`,
`fix/arxiv-timeout`, `docs/readme`, `chore/deps-bump`,
`test/critic-routing`.

PR requirements:
- **Bundle related concerns into one PR.** Cluster changes by subsystem
  (all "observability core" pieces together), by architectural theme
  (a foundation + its natural first consumers), or by sprint slice
  (all Sprint 1 reliability items). ~400-800 additions is the sweet
  spot; smaller PRs are fine for genuinely isolated fixes. **Do not
  fragment cohesive work into nano-PRs** — the review overhead
  outweighs the granularity signal.
- Do not bundle *unrelated* concerns (a doc-only change alongside a
  bug fix). Cohesion still matters; this is not a license for
  grab-bag PRs.
- Title is concise and describes what changed (under 70 chars).
- Body explains the *why* (motivation, tradeoffs), links related issues,
  and includes a short test plan.
- Tests and docs for the diff ship in the same PR (per the Testing and
  Documentation mandates above). `pytest tests/` must pass locally
  before opening the PR.
- Squash-merge to keep `main` history linear and each PR a single commit.

## Commands

Everything goes through the `Makefile`. Common targets:

```bash
make install-dev          # fresh venv + runtime + dev deps
make test                 # unit tier (default per-PR check)
make test-all             # every tier
make typecheck            # mypy src/
make run QUERY='What are the latest approaches to reducing hallucination in LLMs?'
```

Full setup, targets, and troubleshooting in [`docs/development.md`](docs/development.md).

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
- [x] Phase 2: PDF parsing (`pdf_parser`, `chunker`, `chunk_ranker`, reader wired)
- [x] Phase 3: Eval pipeline (20-query benchmark + 4 metrics + runner + `make eval`)
- [x] Retry/backoff on Anthropic 429s (SDK-native, 4 retries + 120s timeout)
- [x] Retry/backoff on arXiv API + PDF downloads (`urllib3.Retry` shared session)
- [x] Nightly eval CI with regression detection (`.github/workflows/eval-nightly.yml`)
- [x] Typed config via `pydantic-settings` (`src/config.py`)
- [x] Structured JSON logging + `run_id` propagation (`src/observability/`)
- [x] Per-run cost tracking (token counts + USD, per-model breakdown) — landed in `summary.jsonl`
- [x] OpenTelemetry tracing (opt-in; `traced_node` wraps every agent)
- [x] LangGraph SqliteSaver checkpointing (on by default; interrupt/resume)
- [x] Expand benchmark queries 10 -> 20 (12+ distinct domains)
- [x] Retrieval recall metric (batched LLM-as-judge; separates search from generation)

**Sprint 1 complete.** 20+ merged PRs, 13 ADRs, 262+ tests. See
[`planning/03-roadmap.md`](planning/03-roadmap.md) for the sprint-by-
sprint log.

## Next Phases (post-Sprint-1)

The system is currently **agentic-lite** — five agents in a fixed
DAG with one conditional edge on the critic. Sprint 2 turns this into
a supervisor loop; Sprint 3 makes it deployable. Detailed plans live
in `planning/`:

- **Sprint 2 — go agentic**: build a supervisor loop, verifier
  agent, evidence store, budget-based stopping. Full sequenced plan
  with rationale in
  [`planning/05-agentic-upgrade-plan.md`](planning/05-agentic-upgrade-plan.md).
  Prerequisite: freeze a 3-repeat baseline eval on the current fixed
  pipeline so we can measure whether the loop pays for itself.
- **Sprint 3 — recovery + retrieval iteration**: query refiner,
  reader-requests-more-chunks, Semantic Scholar adapter, Claude
  prompt caching, cost-aware model routing. Roadmap in
  [`planning/03-roadmap.md`](planning/03-roadmap.md).
- **Sprint 4 — deployable**: FastAPI + Docker + CI workflow +
  paper cache. Roadmap in
  [`planning/03-roadmap.md`](planning/03-roadmap.md).
- **Portfolio polish (interleaves with Sprints 2-3)**: architecture
  diagram, README demo, eval results table, "Production
  considerations" section. Full checklist and sequencing in
  [`planning/06-portfolio-polish.md`](planning/06-portfolio-polish.md).

Follow-up items still on the backlog (see also
[`docs/eval.md`](docs/eval.md)):

- [ ] End-to-end test with LLM cassettes
- [ ] Regression tracking issue bot (`feat/eval-regression-issue-bot`)
- [ ] Cheaper eval judges via Haiku (`feat/eval-cheaper-judge`)
- [ ] Prompt-injection isolation on the reader (**severity upgraded**
  once the supervisor loop lands — see
  [`planning/05-agentic-upgrade-plan.md`](planning/05-agentic-upgrade-plan.md)
  item 8)
- [ ] `regression_diff` `METRIC_FIELDS` extended with `iterations`,
  `llm_calls`, `cost_usd` — catches loop-induced cost creep before it
  drowns quality wins
