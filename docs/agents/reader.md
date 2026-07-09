# Reader agent

Extracts structured findings from each paper's full text (when
available) or abstract (as fallback). One of the five agents wired
through the LangGraph workflow.

Source: `src/agents/reader.py`.

## Inputs

Reads from `ResearchState`:

- `papers: list[PaperMetadata]` — ranked papers from the search agent.
- `query: str` — the original user query. Included in the prompt so the
  model calibrates relevance against the same target the user asked
  about.
- `sub_questions: list[str]` — planner's decomposition. Used to rank
  chunks (not directly to prompt the LLM).

## Outputs

Writes to `ResearchState`:

- `paper_analyses: list[PaperAnalysis]` — one entry per input paper,
  each with `key_findings`, `methodology`, `results_summary`,
  `limitations`, and a `relevance` score in `[0, 1]`.
- A `messages` entry (`AIMessage` named `"reader"`).

## Pipeline per paper

```
PaperMetadata
   |
   +--> parse_pdf(pdf_url)              # PyMuPDF, cached on disk
   |         |
   |         v
   |     full_text or ""
   |         |
   +--> chunk_paper(full_text)          # section-aware chunker
   |         |
   |         v
   |     chunks or []
   |         |
   +--> rank_chunks_by_relevance(       # FAISS + MiniLM
   |         chunks, sub_questions,
   |         top_k=5)
   |         |
   |         v
   |     ranked chunks or []
   |
   +--> _build_user_prompt(paper, query, excerpts)
   |         |
   |         v
   +--> call_llm_json(...) -> PaperAnalysis
```

If any of `parse_pdf`, `chunk_paper`, or the ranker returns empty,
`_gather_context` yields `""` and the prompt tells the model:

> Full text unavailable; base your analysis on the abstract only.

Papers are processed in parallel via a
`ThreadPoolExecutor(max_workers=5)`.

## Prompt design

**System**: instructs the model to extract JSON with five fields,
forbids fabrication, tells it to prefer excerpts over the abstract for
methodology and results when both are present.

**User**: query + title + abstract, always. Then either:
- Section-tagged excerpts (`[method] ...`), joined by blank lines, or
- An explicit "full text unavailable" note.

Rationale for the fallback signal: see ADR
[0004](../decisions/0004-reader-fulltext-with-abstract-fallback.md).

## Known failure modes

| Failure | Where | Handling |
|---|---|---|
| PDF 404 / rate-limited | `parse_pdf` HTTP layer | Returns `""`; reader falls back to abstract. |
| Non-PDF response body | `parse_pdf` magic-header check | Returns `""`. |
| PyMuPDF extraction throws | `parse_pdf` try/except | Returns `""`. |
| Chunker finds no headers | `chunk_paper` | Returns a single `body` chunk — still valid. |
| Chunker finds no chunks | `chunk_paper` (empty input) | Returns `[]`; reader falls back. |
| Ranker returns empty | shouldn't happen with non-empty chunks | Guarded; falls back. |
| Claude returns non-JSON | `call_llm_json` | Raises `JSONDecodeError`; the ThreadPoolExecutor propagates. Improvement candidate: catch + retry with a "return valid JSON" nudge. |
| Anthropic 429 | `call_llm_json` | Currently propagates. Follow-up: `feat/anthropic-retry` with exponential backoff. |

## Configuration

Constants in `src/agents/reader.py`:

- `MAX_WORKERS = 5` — parallel papers.
- `MAX_CHUNKS_PER_PAPER = 5` — top-K passed to the LLM. Bounds per-paper prompt at ~5 × 800 tokens.

## Testing

- Unit: `tests/test_reader.py` covers `_build_user_prompt` (context /
  no-context branches) and `_gather_context` (all three empty-return
  paths + happy-path formatting), with `parse_pdf` / `chunk_paper` /
  `rank_chunks_by_relevance` monkeypatched.
- Integration: TODO — needs a canned PDF fixture and a stubbed Claude
  response. Tracked as a follow-up.
- E2E: covered by the workflow-level cassette suite (TODO).

## Evidence store path (ADR 0016)

When `settings.enable_evidence_store` is on, the reader's LLM call
uses an extended prompt (`EVIDENCE_SYSTEM_PROMPT`) that also emits a
`claims` list. Each claim carries a 1-based `chunk_index` into the
numbered ranked-chunk block, and the reader hydrates
`source_text` / `section` / `relevance_score` from the ranked chunk
itself (server-side) so those fields can't be paraphrased by the LLM.
The verifier consumes the resulting `EvidenceClaim`s to judge against
real text instead of abstracts (ADR-0007's known limitation).

Base-path prompts (`SYSTEM_PROMPT`, `_build_user_prompt`,
`_gather_context`) stay byte-identical to the Sprint 1 baseline so
`enable_evidence_store=False` runs are directly comparable to
pre-flag results.

Cost bounds:
- `reader_max_claims_per_paper: int = 5` — per-paper claim cap.
- Per-paper `max_tokens` raised to 1536 on the evidence path (base
  path stays at 1024).
- Per-paper LLM call count is unchanged (still one).

Fallback: if the ranked-chunks list is empty (PDF unavailable, chunks
filtered), the evidence path silently falls back to the base prompt
and emits `evidence = []`. We do **not** fabricate `source_text` from
the abstract.

## Recovery path (ADR 0019)

When `settings.enable_reader_recovery` is on, a `RECOVERY_ADDENDUM`
is concatenated onto whichever system prompt is in use, extending
the response schema with three fields:

- `analysis_complete: bool` — did the excerpts cover this paper's
  contribution to the sub-questions?
- `missing_context: str` — short natural-language description of the
  gap.
- `request_more_sections: list[str]` — section names the reader
  wants re-read.

`_analyze_paper` returns those as a per-paper `ReaderRecoverySignal`.
Aggregation across papers (in `_aggregate_recovery`):

- `reader_analysis_complete` = AND across papers.
- `reader_missing_context` = `"<paper title>: <what's missing>"`
  entries joined with `"; "`.
- `reader_requested_sections` = deduped union across papers, case-
  insensitive dedup with first-seen casing preserved.

On subsequent invocation, `reader_agent` passes
`state.reader_requested_sections` into `rank_chunks_by_relevance` as
`preferred_sections`. The ranker reserves `min(len(preferred),
max(1, top_k // 2))` slots for chunks whose section matches (case-
insensitive), then fills the remaining slots from the top of the
overall ranking. Preferred chunks come first in the returned list so
the reader's prompt shows them prominently.

If the reader falls back to the abstract-only path (PDF fetch failed,
no chunks), the recovery signal is forced to
`analysis_complete=False` with `missing_context="full text
unavailable"` regardless of what the LLM emitted — an abstract-only
read is always a lesser read from the workflow's perspective.

Fail-open on parse errors: any missing / wrong-typed recovery field
defaults to "analysis complete" so a broken response can't trigger
an infinite re-read loop.

## Prompt-injection isolation (ADR 0020)

When `settings.enable_prompt_isolation` is on, paper-derived text
(abstract + ranked chunks) is wrapped in
`<untrusted_paper_text>...</untrusted_paper_text>` tags in the user
prompt and the system prompt gains an explicit "treat wrapped
content as data" instruction. On the output side, the reader's
control fields (`missing_context`, `request_more_sections`) and the
`EvidenceClaim.claim` field are scrubbed through
`sanitize_control_string` / `sanitize_section_names` before flowing
to state.

`source_text` inside `EvidenceClaim` is left verbatim on purpose —
the verifier judges against it, so paraphrase-in-the-middle would
break the substrate. Downstream agents (verifier, synthesizer) are
follow-up isolation work.

Default off; **recommend enabling whenever `enable_supervisor` is
on**. See `docs/security.md` for the full threat model and
adversarial tests in `tests/test_reader_isolation.py`.

## Follow-ups tracked in ADRs

- Retry / backoff for arXiv PDF downloads
  (`feat/arxiv-download-retry`).
- Retry / backoff for Anthropic 429s (`feat/anthropic-retry`).
- Per-paper `source: "fulltext" | "abstract"` field on `PaperAnalysis`
  for observability (`feat/reader-provenance`).
- Per-paper preferred sections (currently unioned across papers) —
  see ADR 0019 alternatives.
- Extend prompt-injection isolation into synthesizer and verifier
  prompts — see ADR 0020 non-goals.
