# Synthesizer agent

Turns paper analyses (and, when available, source-grounded evidence)
into a structured markdown research briefing with an inline citation
list. One of the five agents wired into both the fixed pipeline and
the supervisor loop.

Source: `src/agents/synthesizer.py`. Design rationale: ADRs
[0016](../decisions/0016-evidence-store-source-text-verifier.md) and
[0017](../decisions/0017-synthesizer-evidence-swap.md).

## Inputs

Reads from `ResearchState`:

- `query` — the user's research question.
- `paper_analyses` — required. Free-form summaries from the reader.
  Used as paper "shape" context (methodology / limitations) even on
  the evidence path.
- `papers` — supplies author labels for the paper header lines.
- `critique` — previous critic feedback, if any. Included verbatim so
  the LLM addresses it in this revision.
- `evidence` — optional. When populated **and** `enable_evidence_store`
  is on, triggers the evidence path.
- `sub_questions` — used to group evidence claims in prompt order.

## Outputs

Writes to `ResearchState`:

- `draft_report` — markdown report body with inline `[Author, Year]`
  citations. Shape is the same on both paths.
- `citations` — list of `Citation` TypedDicts, one per cited paper.
- A `messages` entry (`AIMessage` named `"synthesizer"`) summarizing
  the run.

## Two prompt paths

`_use_evidence_path(state)` picks between them at call time:

```
enable_evidence_store  state.evidence   → path
False                  any              → base
True                   []               → base (fall-back)
True                   [claim, ...]     → evidence
```

The base path is byte-identical to Sprint 1. The evidence path adds
grounding rules to the system prompt and appends an evidence bank to
the user prompt.

### Base path (Sprint 1 baseline)

- `SYSTEM_PROMPT` — high-level rules (group by theme, compare methods,
  cite inline, end with Key Takeaways + Open Questions).
- User prompt = `Research question` + `critique` (if any) + numbered
  `--- Paper N ---` blocks with title / authors / ID / URL / key
  findings / methodology / results / limitations / relevance.

Preserved exactly so `enable_evidence_store=False` runs compare
directly against pre-flag numbers.

### Evidence path

- `EVIDENCE_SYSTEM_PROMPT` — same rules plus a **GROUNDING RULES**
  block: every factual claim must trace to a provided excerpt,
  missing coverage goes to "Open Questions" rather than being filled
  from the abstract, paraphrasing is fine but adding facts is not.
- User prompt = base prompt + **sub-questions list** + **evidence
  bank** grouped by `supports_question` in planner order. Within each
  group, claims are sorted by `relevance_score` descending so the
  strongest support comes first. Each entry shows author label,
  section, relevance, the claim itself, and the verbatim
  `source_text` excerpt.

Response schema is unchanged (`draft_report` + `citations`). No claim
IDs embedded in the report text — the grounding rules in the system
prompt do the work.

## Failure modes

| Failure | Where | Handling |
|---|---|---|
| Anthropic 429 / other exception | `call_llm_json` | Propagates. Synthesizer intentionally doesn't retry above the SDK layer (ADR 0009). |
| `EvidenceClaim.supports_question` doesn't match a planner sub-question | Reader `_parse_claim` | Already cleared to `""` at emission time, so it lands under "Unassigned excerpts" here. |
| Evidence bank silent on a sub-question | Prompt design | LLM instructed to add it to "Open Questions" rather than fabricate coverage. |
| Report cites a paper not in `state.papers` | Downstream | Caught by the citation-accuracy metric (offline) and the verifier's `missing_evidence` (online). |

## Configuration

Settings that drive the synthesizer (see `src/config.py`):

- `enable_evidence_store: bool = False` — same flag that gates the
  reader's claim emission and the verifier's chunks dossier. Turning
  it on switches all three agents together (ADR 0017).

No synthesizer-specific tunables today.

## Testing

- Unit: `tests/test_synthesizer.py` — 16 tests covering
  `_use_evidence_path` (all three cells of the table above),
  base-path prompt stability (headers byte-identical to baseline,
  critique carried through, evidence ignored when flag off), evidence
  block formatting (grouped by sub-question in planner order, ordered
  by relevance within group, unassigned heading, verbatim
  `source_text`), evidence-path prompt shape, and full agent
  behavior including message summaries.
- Integration: exercised inside the workflow-level tests.
- E2E: covered by the future cassette suite.

## Follow-ups

- Evidence-aware completeness / citation-accuracy metrics. Offline
  metric substrate stays abstract-based (ADR 0007) so cross-config
  comparability holds during the substrate rollout.
- `open_questions` / `evidence_gaps` state fields with dedicated
  producers (a critic or verifier extension). Report body still
  surfaces open questions inside the markdown for now.
