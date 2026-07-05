# arxiv-research-agent

A multi-agent research assistant for ML/AI papers. Takes a natural-language
research question, searches arXiv, extracts findings from each paper,
synthesizes a briefing, and self-critiques for quality. Orchestrated with
LangGraph and Claude.

## Architecture

```
User Query -> PLANNER -> SEARCH -> READER -> SYNTHESIZER -> CRITIC -> Output
                 ^                              ^             |
                 |__________ RE-ROUTE __________|_____________|
                        (on critique failure, max 3 iterations)
```

Full design in `CLAUDE-Agent-Proj-1.md`.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Copy `.env.example` to `.env` and add your Anthropic API key:

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
python -m src.main "What are the latest approaches to reducing hallucination in LLMs?"
```

The final markdown report is printed to stdout and saved to
`outputs/report_<timestamp>.md`.

### Offline mode

If arXiv is rate-limiting or unavailable, force the built-in mock papers
instead of a live search:

```bash
USE_MOCK_DATA=true python -m src.main "..."
```

## Tests

```bash
pytest tests/
```

## Project status

Phase 1 (MVP) — abstracts only, no PDF parsing. Phase 2 adds full-text
parsing with PyMuPDF; Phase 3 adds an eval pipeline. See
`CLAUDE-Agent-Proj-1.md` for the phased plan.
