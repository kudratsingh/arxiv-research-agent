# Multi-Agent Research Assistant for ML/AI Papers

## Project Overview
A multi-agent system that takes a natural language research question about ML/AI, searches arXiv for relevant papers, extracts key findings, synthesizes a research briefing, and self-critiques for quality — orchestrated via LangGraph with Claude as the reasoning engine.

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
- PDF download + parsing
- Chunking by section headers
- FAISS relevance ranking
- Comparative tables in synthesis
- Error handling for PDF failures

### Phase 3: Polish
- Eval pipeline (faithfulness, completeness, citation accuracy)
- Human-in-the-loop (interrupt after planner)
- Streaming output
- Caching layer for paper embeddings
- Export to formatted markdown/PDF

## Conventions
- Use `anthropic` SDK directly for Claude API calls (not langchain-anthropic)
- All agents are pure functions: take ResearchState, return partial state updates
- Use `python-dotenv` to load ANTHROPIC_API_KEY from .env
- Type hints on everything
- Docstrings on all public functions
- Keep agent system prompts in the agent files (not separate config)

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
- [ ] Project scaffolded
- [ ] State schema defined
- [ ] Planner agent implemented
- [ ] Search agent implemented
- [ ] Reader agent implemented
- [ ] Synthesizer agent implemented
- [ ] Critic agent implemented
- [ ] LangGraph workflow wired
- [ ] End-to-end test passing
