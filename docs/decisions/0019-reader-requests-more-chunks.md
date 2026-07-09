# 0019. Reader requests more chunks — recovery at the read layer

- **Status**: accepted
- **Date**: 2026-07-08
- **Depends on**: ADR
  [0004](0004-reader-fulltext-with-abstract-fallback.md),
  [0014](0014-supervisor-loop-behind-flag.md),
  [0018](0018-query-refiner-recovery-action.md)

## Context

The reader ranks all chunks of every paper against the planner's
sub-questions and keeps the top-K. That's cost-bounded and works, but
the planner's sub-questions are written before any papers are read —
they can miss the specific angle the reader ends up needing (a
`results` section for a benchmark comparison, a `limitations` section
for a critique). Under the fixed pipeline that's just tough luck; the
critic sees the shallow analysis and asks for revision but the
revision loop re-reads with the same ranker, so it gets the same
chunks.

ADR 0018 added recovery at the search layer via a `refine_query`
action. Sprint 2 item 7 in
[`planning/05-agentic-upgrade-plan.md`](../../planning/05-agentic-upgrade-plan.md)
asks for the mirror at the read layer: let the reader flag, per
paper, that it didn't get enough excerpts, name the sections it
wants re-read, and then give the ranker a way to promote those
sections on the next read.

Constraints match the earlier Sprint 2 agents:

1. **Fixed pipeline stays byte-identical.** Baseline eval numbers
   must still be comparable.
2. **Independent flag.** `enable_reader_recovery` is orthogonal to
   `enable_supervisor`, `enable_verifier`, `enable_evidence_store`,
   `enable_query_refiner`. Every substrate change gets its own A/B
   knob.
3. **Fail-open on parse errors.** A broken response defaults to
   "complete" so a malformed LLM output can't accidentally send the
   loop into an infinite re-read.

## Decision

Extend the reader's response schema (both the base and evidence
paths) with three optional fields, gated by `settings.enable_reader_recovery`:

```json
{
  "analysis_complete": true|false,
  "missing_context": "short description of what's missing",
  "request_more_sections": ["results", "limitations", ...]
}
```

Rather than duplicating both system prompts, a `RECOVERY_ADDENDUM` is
concatenated onto whichever prompt (`SYSTEM_PROMPT` or
`EVIDENCE_SYSTEM_PROMPT`) is in use. The base prompts stay byte-
identical when the flag is off, so the addendum has zero effect on
the Sprint 1 baseline.

### State additions

- `reader_analysis_complete: bool` — AND across all papers'
  `analysis_complete`. Default `True` so consumers reading a fresh
  state don't spuriously trigger a re-read.
- `reader_missing_context: str` — `"<paper title>: <what's missing>"`
  entries joined with `"; "`.
- `reader_requested_sections: list[str]` — deduped union of every
  paper's `request_more_sections`, case-insensitive on the dedup key
  but preserving the first-seen casing for display.

### Per-paper signal shape

`ReaderRecoverySignal` TypedDict lives in `src/agents/reader.py`
(local, not on the state surface). `_analyze_paper` now returns
`(PaperAnalysis, list[EvidenceClaim], ReaderRecoverySignal)`. Under
the base config a `_default_signal()` (`analysis_complete=True`, no
sections requested) is returned so upstream code always sees a
well-formed shape.

### Ranker biasing on re-read

`rank_chunks_by_relevance` gets a new optional
`preferred_sections: list[str] | None` argument. When populated,
`_apply_preferred_sections` reserves `min(len(preferred), max(1,
top_k // 2))` slots for chunks whose section matches (case-
insensitive), then fills the remaining slots from the top of the
overall ranking. Preferred chunks come first in the returned list so
the reader's prompt shows them prominently.

Two ranker corner cases:
- **No matching preferred chunks** — behaves like `preferred_sections`
  wasn't set. Keeps re-reads useful when the LLM guessed a section
  name (`"experiments"`) that the paper doesn't actually have.
- **`preferred_sections=None`** (the default) — behavior is byte-
  identical to Sprint 1. The base ranker call site
  (`_gather_context`, used only in tests today) passes nothing, so
  its behavior doesn't shift.

### Supervisor surface

The supervisor's state summary surfaces three lines when the flag is
on: `reader_analysis_complete`, `reader_requested_sections`,
`reader_missing_context` (truncated to 200 chars). The system prompt
gains a deviation hint telling the supervisor to prefer `read` when
`reader_analysis_complete` is false — the reader will consume the
`reader_requested_sections` on re-invocation and promote them in the
ranker.

### Abstract-only override

If the reader falls back to the abstract-only path (PDF fetch failed,
no chunks), the recovery signal is forced to `analysis_complete=False`
with `missing_context="full text unavailable"` and an empty
`request_more_sections`. The supervisor sees the truth regardless of
what the LLM chose to emit — an abstract-only read is always a lesser
read from the workflow's perspective.

## Alternatives considered

**Have the reader emit an ID or handle that the supervisor passes back
to it verbatim.** Would make the round-trip more explicit. Rejected
because there's no meaningful handle — the reader just wants "which
sections to prioritize", and section names are the natural currency.

**Add `preferred_sections` to `Chunk` or `RankedChunk` and let the
reader annotate.** Considered against extending the ranker signature.
Rejected because the section preference isn't a per-chunk property; it
belongs at the ranker call site, which is closer to the reader's
knowledge of what was missing.

**Bias the ranker by injecting section names into the sub-question
list.** Concrete: instead of a new argument, add `"results section"`
and `"limitations section"` as pseudo-sub-questions. Rejected because
the semantic similarity of chunks to `"results section"` isn't a
strong enough signal — a chunk with the word "result" in an intro
paragraph will score higher than the actual results section. Section-
metadata biasing is the right abstraction.

**Track re-read count and give up after N.** Considered as a safety
valve. Rejected because the supervisor's `max_loop_iterations`
already caps total re-reads. Adding another cap would just add
another off-by-one.

**Track requested sections per paper, not aggregated.** Would let the
ranker bias only for papers that flagged the section. Rejected as
premature complexity — the current union-of-sections gives every re-
read a chance at every requested section, and if that turns out to
over-fetch, per-paper tracking is a compatible follow-up. Ship simple
first.

## Consequences

**Wins**

- Recovery at the read layer complements ADR 0018's recovery at the
  search layer.
- Reader signals what's missing in natural language; supervisor state
  summary surfaces it, so the supervisor loop can reason about read-
  level gaps.
- Ranker biasing means the "re-read" action actually reads different
  chunks — otherwise it would be another retry-with-nothing-changed.
- Abstract-only fallback is now always visible as
  `analysis_complete=False`, which was a silent quality regression
  before.

**Tradeoffs**

- Reader prompt grows by the addendum (~150 tokens output cap +
  slightly larger response). Bounded per-paper; scales with paper
  count.
- `_analyze_paper` return type widened to a 3-tuple, which touches a
  handful of test mocks. Kept the 2-tuple ergonomics under the
  `default_signal` helper so future callers don't have to think about
  the recovery dimension.
- Ranker signature gained an argument. Default (`None`) preserves
  Sprint 1 behavior byte-for-byte, but every fake that intercepts
  `rank_chunks_by_relevance` needs to accept the keyword.
- The section union is unioned across papers — a re-read biases the
  ranker for every paper, even ones that didn't flag any sections.
  Slight over-promotion; measurably cheaper than per-paper tracking
  and probably harmless.

**Non-goals (deferred)**

- Per-paper preferred sections. See alternatives.
- Reader emitting evidence-store `EvidenceClaim`s directly from the
  requested sections. Sprint 2 item 5a already covers claim emission
  from ranked chunks — recovered chunks flow through the same path.
- A "section-of-the-paper" taxonomy shared with the planner. Today
  the reader's emitted section names are freeform (whatever the LLM
  picks) — mostly-consistent-with the chunker's section headers but
  not guaranteed. If we need strict matching we'd normalize both
  sides; not needed while the ranker fallback ("no matching preferred
  chunks → behave as if unset") holds.
