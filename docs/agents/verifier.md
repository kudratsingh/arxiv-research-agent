# Verifier agent

## Purpose

Runtime faithfulness check that runs as a supervisor-selected action.
When `settings.enable_verifier` is `True` the supervisor may pick
`verify`; the node reads the current draft plus a per-paper source
dossier — ranked chunks when the evidence store is on and populated,
abstracts otherwise — judges each cited claim against it, and writes a
recovery recommendation back to state for the supervisor to act on.

The verifier is **supervisor-only** — it is never wired into the
fixed pipeline. `enable_verifier` is independent of `enable_supervisor`
so the two features can be A/B'd separately against the Sprint 1
baseline.

Source: `src/agents/verifier.py`. Wiring:
[`docs/architecture.md`](../architecture.md).

## Flow

```mermaid
flowchart LR
  IN["draft_report · citations<br/>papers · evidence · sub_questions"] --> SC{"draft empty or<br/>no citations?"}
  SC -->|"yes"| SKIP["verified = true<br/>no LLM call"]
  SC -->|"no"| DOS{"enable_evidence_store<br/>and state.evidence?"}
  DOS -->|"yes"| CH["chunks dossier<br/>_dossier_from_evidence"]
  DOS -->|"no"| AB["abstracts dossier<br/>build_source_index"]
  CH --> J["call_llm_json<br/>faithfulness judge"]
  AB --> J
  J -->|"parsed"| OUT["verified · unsupported_claims<br/>missing_evidence<br/>verifier_recommendation"]
  J -->|"raised or unusable"| FB["verified = false<br/>revise_report"]
  FB --> OUT
  SKIP --> OUT
  OUT --> SUP["supervisor picks the next action"]
```

## Inputs

Reads from `ResearchState`:

- `draft_report` — required; an empty/whitespace draft short-circuits
  with `verified=True` and no LLM call.
- `citations` — required; a draft with no citations skips the judge
  entirely and returns `verified=True` (the critic catches that case).
- `papers` — supplies the abstracts joined against `citations` via
  `build_source_index` (shared with ADR 0007's offline metric), and
  the author last names that key the chunks dossier.
- `evidence` — optional. When populated **and**
  `enable_evidence_store` is on, the dossier is built from the
  reader's ranked chunks instead of abstracts.
- `sub_questions` — surfaced to the judge as "topics the report should
  cover" so `missing_evidence` can name specific gaps.
- `query` — included as context in the prompt.

## Outputs

Writes to `ResearchState`:

- `verified: bool` — true iff every cited claim resolved and no
  sub-question was flagged as missing evidence.
- `unsupported_claims: list[str]` — verbatim claim strings the judge
  flagged.
- `missing_evidence: list[str]` — topics / sub-questions lacking a
  cited source. Also read by the
  [query refiner](query_refiner.md) as its gap signal.
- `verifier_recommendation: str` — one of `read_more | search_more |
  revise_report | ""`. Intent-shaped, not routing-shaped; the
  [supervisor](supervisor.md) translates it into an action.
- A `messages` entry (`AIMessage` named `"verifier"`) summarizing the
  decision.

## Prompt design

**System** (`VERIFIER_SYSTEM_PROMPT`): ADR-0007's calibrated
faithfulness prompt reused as the basis — no new prompt engineering —
with the response schema extended by `recommended_action`. It
describes both source shapes explicitly so the judge treats them
differently: **source chunks** are the strongest evidence; an
**abstract fallback**, marked `abstract (no chunks available)`, is a
lower bound and should be judged more strictly. It also defines what
counts as a factual claim, what "supported" means, and when to pick
each recovery action. `max_tokens=2048`.

**User** (`_build_user_prompt`): research question + the sub-questions
the report should cover + the full draft + the cited-paper dossier
(see below).

### Response schema

```json
{
  "verified": true,
  "unsupported_claims": ["<claim text>", ...],
  "missing_evidence": ["<topic>", ...],
  "recommended_action": "read_more|search_more|revise_report|",
  "reason": "one-sentence overall diagnosis"
}
```

Extends ADR 0007's per-claim judge output with a runtime recovery
recommendation and a top-level `verified` flag. The judge does not
control routing — it names the failure mode; the supervisor picks
the next node.

## Decision procedure

```
verifier_agent(state):
    # 1. Cheap short-circuits — no LLM call.
    if not state.draft_report.strip():
        return empty_result("no draft to verify")     # verified=True
    if not state.citations:
        return empty_result("draft has no citations") # verified=True

    # 2. Ask the judge.
    try:
        parsed = call_llm_json(prompt=_build_user_prompt(state),
                               system_prompt=VERIFIER_SYSTEM_PROMPT)
    except Exception:
        return fallback_result("LLM call failed")
        # verified=False, recommendation="revise_report"

    # 3. Coerce + validate the response.
    verified = parsed.get("verified") is True
    unsupported = _coerce_string_list(parsed.get("unsupported_claims"))
    missing = _coerce_string_list(parsed.get("missing_evidence"))
    recommendation = _clean_recommendation(parsed.get("recommended_action"))

    # 4. Enforce invariants.
    if verified and (unsupported or missing):
        verified = False          # judge contradicts itself -> not verified
    if not verified and not recommendation:
        if missing and not unsupported:
            recommendation = "search_more"
        elif unsupported:
            recommendation = "revise_report"
        # neither flagged -> recommendation stays ""
    if verified:
        recommendation = ""

    return { verified, unsupported_claims, missing_evidence, verifier_recommendation }
```

Note step 4's inference order: `search_more` is only inferred when the
judge reported missing evidence and **no** unsupported claims. When
both are present, an over-claiming report is the more actionable
diagnosis, so `revise_report` wins. And a `verified=False` verdict with
neither list populated keeps an empty recommendation — the supervisor
falls back to its own routing rather than being handed a guess.

## Source dossier — abstracts vs chunks (ADR 0016)

`_build_user_prompt` picks its dossier shape at call time:

- **Chunks dossier** (`_dossier_from_evidence`) — when
  `settings.enable_evidence_store` is on AND `state.evidence` is
  populated. Groups evidence claims by cited paper, keyed by
  `[Author, Year]` using the same first-author-lastname + 4-digit-year
  normalization as `build_source_index`, and emits each paper's ranked
  chunks verbatim with `(section, relevance=X.XX)` headers. Papers
  cited but lacking evidence claims (partial coverage — e.g. the
  reader couldn't fetch that PDF) fall back to their abstract inside
  the same block, explicitly marked `abstract (no chunks available)`,
  so the judge can calibrate strictness per paper. Cited papers whose
  first author can't be resolved to a last name are skipped entirely.
- **Abstracts dossier** — default. Uses `build_source_index` (shared
  with the offline faithfulness metric) so runtime and offline
  judges read the same substrate.

Either way, a dossier that ends up empty is sent as the literal string
`(no cited papers with sources available)` / `(no cited papers with
abstracts available)` rather than a blank block.

## Failure modes

| Failure | Where | Handling |
|---|---|---|
| Empty draft | Pre-LLM check | `verified=True`, no LLM call, no recommendation. Prevents paying for verification before synthesis. |
| Draft has no citations | Pre-LLM check | `verified=True`, no LLM call. Critic catches the "no citations" case separately. |
| Anthropic 429 / other exception | `call_llm_json` | Caught; falls back to `verified=False, recommendation="revise_report"`. Logged as `verifier_llm_failed_fallback`. |
| Judge output not JSON | `call_llm_json` | Same fallback path — the raised `JSONDecodeError` is caught by the same broad `except`. |
| `verified=True` alongside flagged issues | Post-parse invariant | Downgraded to `verified=False`; recommendation kept. `verified` must mean "no follow-up needed". |
| `verified` truthy but not literal `true` | Post-parse | Treated as `False`. Same idiom the critic uses for `revision_needed`. |
| `recommended_action` outside the enum | `_clean_recommendation` | Cleared to empty, then re-inferred per step 4 above. |
| Wrong-typed fields (`unsupported_claims` = `"string"`, etc.) | `_coerce_string_list` | Coerced to `[]` (drops the field silently rather than crashing). Non-string / blank entries inside a real list are dropped individually. |
| Judge redirects via prompt-injected paper text | Partially mitigated | Reader-side isolation (ADR 0020) scrubs the `claim` fields that reach the chunks dossier, but `source_text` is verbatim by design and the verifier's own prompt is not tag-wrapped — listed in ADR 0020's non-goals. See `docs/security.md`. |

## Flags

Settings that drive the verifier (see `src/config.py`):

- `enable_verifier: bool = False` — master flag. When off, the
  verifier node is not added to the graph and the supervisor's action
  enum excludes `verify`.
- `enable_evidence_store: bool = False` — selects the chunks dossier
  over abstracts (ADR 0016). Shared with the reader and synthesizer;
  turning it on switches all three together.
- `verifier_model: str = ""` — per-agent model override (ADR 0021).
  Empty falls back to `anthropic_model`.
- `enable_prompt_caching: bool = False` — system-prompt caching
  (ADR 0022).

The verifier does not have its own cost / iteration caps — the
supervisor's `max_cost_usd` and `max_loop_iterations` gate every node
including this one, and the API runner's between-node budget check
(ADR 0051) applies regardless of graph shape.

## Testing

- Unit: `tests/test_verifier.py` — 23 tests covering short-circuits
  (empty draft, no citations), well-formed judge output (all three
  recommendation values), invariants (`verified=True` + issues gets
  downgraded, recommendations get inferred when the judge omits them),
  and malformed output (LLM exception, unknown recommendation,
  wrong-typed fields).
- Supervisor gating: `tests/test_supervisor.py::TestVerifierGating` —
  8 tests covering the `enable_verifier` flag (`verify` accepted /
  rejected, state summary contents, router behavior with stale
  checkpoints).
- Shared join: `tests/test_metrics_faithfulness.py` — exercises
  `build_source_index`, the abstracts-dossier substrate.

## Known limitations

- **Reader-dependent substrate**. The verifier judges against chunks
  only when the reader could extract them (PDF fetch + chunk + rank
  succeeded). When any of those fail, the verifier falls back to the
  abstract for that paper — same behavior as before ADR 0016, but now
  marked in the dossier and applied per-paper instead of per-run.
- **No per-claim citation cross-check**. If the judge flags a claim
  whose only cited source we couldn't provide, we currently keep the
  claim rather than reclassifying it as `source_unavailable` (which is
  what the offline metric does). Deliberate: the alternative requires
  a per-claim citation index, and the supervisor's `missing_evidence`
  handling covers this case orthogonally.
- **Prompt not isolated**. The dossier embeds verbatim paper text;
  wrapping it is ADR 0020's deferred follow-up.
- ~~**Synthesizer still writes from `paper_analyses`, not
  `evidence`**.~~ Landed — the synthesizer's evidence-grounded path
  shipped as ADR 0017 (same `enable_evidence_store` flag; no claim
  IDs embedded in the report text — the grounding rules in the system
  prompt do the work).

## Related

- **Hands off to** — the [supervisor](supervisor.md), always. The
  recommendation maps to a next action there: `read_more` →
  [reader](reader.md), `search_more` → [search](search.md) or the
  [query refiner](query_refiner.md), `revise_report` →
  [synthesizer](synthesizer.md).
- **ADRs** — [0015](../decisions/0015-verifier-agent-runtime-faithfulness.md)
  (this agent),
  [0007](../decisions/0007-faithfulness-single-call-abstracts.md) (the
  offline judge it promotes),
  [0016](../decisions/0016-evidence-store-source-text-verifier.md)
  (chunks dossier),
  [0017](../decisions/0017-synthesizer-evidence-swap.md),
  [0014](../decisions/0014-supervisor-loop-behind-flag.md),
  [0020](../decisions/0020-prompt-injection-isolation-reader.md)
  (isolation non-goals),
  [0021](../decisions/0021-cost-aware-model-routing.md),
  [0022](../decisions/0022-anthropic-prompt-caching.md).
- **Workflow wiring** — [`docs/architecture.md`](../architecture.md).
