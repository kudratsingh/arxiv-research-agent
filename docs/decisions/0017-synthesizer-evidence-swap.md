# 0017. Synthesizer prefers `EvidenceClaim`s when available

- **Status**: accepted
- **Date**: 2026-07-07
- **Depends on**: ADR
  [0016](0016-evidence-store-source-text-verifier.md)

## Context

ADR 0016 landed the substrate half of Sprint 2 item 5: reader emits
`EvidenceClaim`s with `source_text` hydrated from ranked chunks, and
the verifier now judges those excerpts instead of paper abstracts.

But the synthesizer — the agent that actually writes the report — was
left reading `paper_analyses` only. That leaves the substrate
half-connected: the verifier gets richer sources, but the report the
verifier judges is still built from the same free-form summaries as
Sprint 1. The plan's item 5b (see
[`planning/05-agentic-upgrade-plan.md`](../../planning/05-agentic-upgrade-plan.md))
calls out the fix: synthesizer should draw every factual sentence
from the evidence bank when one exists.

Constraints (same as ADR 0016):

1. **Fixed pipeline byte-identical to Sprint 1 baseline.** The base
   synthesizer prompt and paper-analyses block must not change, so
   the `enable_evidence_store=False` configuration compares directly
   against Sprint 1 numbers.
2. **Fall back cleanly when evidence is empty.** If the reader
   couldn't extract claims (all PDFs failed, chunks filtered), the
   synthesizer should silently take the base path rather than
   producing a grounded report against no grounding.
3. **Report output shape unchanged externally.** Downstream metrics
   (completeness, citation-accuracy, faithfulness) and the verifier
   all key off `draft_report` markdown + `citations` list. Changing
   the report's on-disk shape (e.g. embedding claim IDs) would fan
   out into every metric.

## Decision

Add an evidence-path prompt (`EVIDENCE_SYSTEM_PROMPT`) alongside the
existing base prompt. Select at call time with `_use_evidence_path`:

```python
def _use_evidence_path(state):
    return settings.enable_evidence_store and bool(state.get("evidence"))
```

Both conditions must hold — the flag alone is not enough. This
guarantees the fall-back-to-base behavior when the reader couldn't
produce claims.

### Prompt design

- **Grounding rules** are the only real difference: every factual
  claim in the briefing must be traceable to one of the provided
  evidence excerpts, missing coverage must land in "Open Questions"
  rather than being filled from the abstract, paraphrasing is fine
  but adding facts is not.
- **Response schema is unchanged.** Still emits `draft_report` +
  `citations`. No new fields, no claim IDs embedded in the report
  text. Downstream metrics keep working without modification.
- **User prompt combines both blocks.** Base path emits just the
  analyses block; evidence path keeps the analyses block *and*
  appends the grounded evidence bank. Analyses give the LLM the
  paper's "shape" (methodology, limitations) while the evidence bank
  is the source-of-truth for factual claims.

### Evidence bank formatting

Grouped by `supports_question` (the sub-question each claim answers)
in planner order — same order the report body will follow — and
sorted within each group by `relevance_score` (highest first) so the
LLM sees the strongest support first. Claims with an empty
`supports_question` land under a dedicated "(unassigned)" heading so
their evidence isn't dropped on the floor.

Author labels are looked up from `state["papers"]` using the same
`"First, Second, Third et al."` format the base analyses block uses,
so the two blocks feed the LLM structurally identical paper headers.

### Reused config

The evidence-path swap is gated by the same
`settings.enable_evidence_store` flag as ADR 0016 — no new config
knob. This tightly couples the two halves of item 5 into a single
on/off unit. See "alternatives considered" for why.

### State field additions

None. This ADR consumes `state.evidence` (already added in ADR 0016)
and writes to `draft_report` / `citations` (already existed). The
`open_questions` / `evidence_gaps` fields listed in the plan are
deferred because they still lack producers — the synthesizer surfaces
open questions inside the report body's "Open Questions" section,
which is already how it worked in Sprint 1.

## Alternatives considered

**Add a second flag `enable_evidence_synthesis` independent of
`enable_evidence_store`.** Would let us A/B "does the synthesizer
using evidence help, given the substrate exists?" Rejected on
YAGNI + cost grounds. A three-config baseline sweep (fixed / sup+ver
/ sup+ver+evidence) is already expensive at ~$45 per configuration
per repeat × 3 repeats. A fourth "evidence store on but synthesizer
doesn't use it" configuration would consume budget without answering
a question we actually plan to act on — we wouldn't ship a
configuration where the reader pays for claim extraction but the
synthesizer ignores it.

**Embed claim IDs in the report text (`... [Smith, 2023 c3]`).**
Would give every sentence a traceable claim reference. Rejected
because it changes the report's on-disk shape, which breaks the
citation-accuracy regex, the verifier's cite-key match, the
completeness metric, and any downstream reader-facing display. The
grounding rules in the system prompt achieve the substance of the
win (grounded sentences) without the schema churn.

**Replace the analyses block entirely on the evidence path.**
Considered — the plan does say the synthesizer "writes from claims,
not paper analyses." Rejected because paper analyses carry
`methodology` and `limitations` at the paper level, which the
evidence bank (organized by sub-question, not paper) does not
naturally express. Keeping both blocks gives the LLM the paper's
shape *and* the grounded claims, which is strictly more information
without inviting fabrication (analyses have never been the source of
factual claims in the report — they've always been context).

**Move evidence-bank formatting into a new module (`src/evidence/`).**
Considered against the plan's `src/evidence/store.py` hint. Rejected
because the formatting is only used by the synthesizer prompt today.
If a future consumer needs the same grouping (e.g. an evidence-aware
critic), extract at that point.

## Consequences

**Wins**

- Item 5b completes item 5. The substrate (reader emits claims) now
  reaches the report (synthesizer grounds sentences).
- No new flag combinations to test. The three-config sweep
  (`fixed` / `sup+ver` / `sup+ver+evidence`) covers the full lift.
- Report output shape unchanged. Downstream metrics keep working
  without modification.
- Fall-back-to-base behavior is automatic when evidence is empty —
  callers don't need to think about "is the flag actually doing
  anything right now?"

**Tradeoffs**

- Synthesizer prompt gets larger on the evidence path — evidence bank
  can be ~50 chunks (`max_papers × reader_max_claims_per_paper`)
  worth of quoted text. Well under Anthropic's context limit but
  measurably higher per-synthesis cost than the base path.
- The LLM is now told to add "Open Questions" for gap coverage
  rather than filling from abstracts. If the evidence bank is thin
  (few chunks that don't cover the sub-questions well), the "Open
  Questions" section will grow. That's the intended behavior — a
  short but honest report is preferable to a long fabricated one —
  but eval judges scoring completeness may read it as a regression.
  Watch the paired diff.

**Non-goals (deferred)**

- Evidence-aware completeness / citation-accuracy metrics. Offline
  metric substrate stays abstract-based (ADR 0007) so cross-config
  comparability holds during the substrate rollout.
- `open_questions` / `evidence_gaps` state fields with dedicated
  producers. Report body still surfaces open questions inside the
  markdown.
- Claim-ID embedding in the report. Discussed and rejected above.
