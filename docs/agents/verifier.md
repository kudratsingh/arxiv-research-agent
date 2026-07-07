# Verifier agent

Runtime faithfulness check that runs as a supervisor-selected action.
When `settings.enable_verifier` is `True` the supervisor may pick
`verify`; the node reads the current draft plus its cited papers,
judges each cited claim against the cited abstract, and writes a
recovery recommendation back to state for the supervisor to act on.

Source: `src/agents/verifier.py`. Design rationale: ADR
[0015](../decisions/0015-verifier-agent-runtime-faithfulness.md).

The verifier is **supervisor-only** — it is never wired into the
fixed pipeline. `enable_verifier` is independent of `enable_supervisor`
so the two features can be A/B'd separately against the Sprint 1
baseline.

## Inputs

Reads from `ResearchState`:

- `draft_report` — required; empty draft short-circuits with
  `verified=True` and no LLM call.
- `citations` — required; a draft with no citations skips the judge
  entirely and returns `verified=True` (the critic catches that case).
- `papers` — supplies the abstracts joined against `citations` via
  `build_source_index` (shared with ADR 0007's offline metric).
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
  cited source.
- `verifier_recommendation: str` — one of `read_more | search_more |
  revise_report | ""`. Intent-shaped, not routing-shaped; the
  supervisor picks the next node.
- A `messages` entry (`AIMessage` named `"verifier"`) summarizing the
  decision.

## Response schema

The system prompt asks for exactly:

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
        return empty_result("no draft to verify")   # verified=True
    if not state.citations:
        return empty_result("draft has no citations")  # verified=True

    # 2. Ask the judge.
    try:
        parsed = call_llm_json(VERIFIER_PROMPT, _build_user_prompt(state))
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
        verified = False            # judge contradicts itself -> not verified
    if not verified and not recommendation:
        recommendation = "search_more" if missing else "revise_report"
    if verified:
        recommendation = ""

    return { verified, unsupported_claims, missing_evidence, verifier_recommendation }
```

## Failure modes

| Failure | Where | Handling |
|---|---|---|
| Empty draft | Pre-LLM check | `verified=True`, no LLM call, no recommendation. Prevents paying for verification before synthesis. |
| Draft has no citations | Pre-LLM check | `verified=True`, no LLM call. Critic catches the "no citations" case separately. |
| Anthropic 429 / other exception | `call_llm_json` | Caught; falls back to `verified=False, recommendation="revise_report"`. Logged as `verifier_llm_failed_fallback`. |
| Judge output not JSON | `call_llm_json` | Same fallback path. |
| `verified=True` alongside flagged issues | Post-parse invariant | Downgraded to `verified=False`; recommendation kept. `verified` must mean "no follow-up needed". |
| `recommended_action` outside enum | `_clean_recommendation` | Cleared to empty, then re-inferred from `missing_evidence` / `unsupported_claims`. |
| Wrong-typed fields (`unsupported_claims` = "string", etc.) | `_coerce_string_list` | Coerced to `[]` (drops the field silently rather than crashing). |
| Judge redirects via prompt-injected paper text | Not yet mitigated | Same open item as the supervisor (planning/05 item 8). |

## Configuration

Settings that drive the verifier (see `src/config.py`):

- `enable_verifier: bool = False` — master flag. When off, the
  verifier node is not wired and the supervisor's action enum
  excludes `verify`.

The verifier does not have its own cost / iteration caps — the
supervisor's `max_cost_usd` and `max_loop_iterations` gate every node
including this one.

## Testing

- Unit: `tests/test_verifier.py` — 15 tests covering short-circuits
  (empty draft, no citations), well-formed judge output (all three
  recommendation values), invariants (`verified=True` + issues gets
  downgraded, recommendations get inferred when the judge omits them),
  and malformed output (LLM exception, unknown recommendation,
  wrong-typed fields).
- Supervisor gating: `tests/test_supervisor.py` — additional tests
  covering the `enable_verifier` flag (`verify` accepted / rejected,
  state summary contents, router behavior with stale checkpoints).

## Source dossier — abstracts vs chunks (ADR 0016)

The verifier's `_build_user_prompt` picks its dossier shape at call
time:

- **Chunks dossier** — when `settings.enable_evidence_store` is on
  AND `state.evidence` is populated. Groups evidence claims by
  cited paper, keyed by `[Author, Year]`, and emits each paper's
  ranked chunks verbatim with `(section, relevance=X.XX)` headers.
  Papers cited but lacking evidence (partial coverage) fall back to
  their abstract inside the same block, marked as such — the judge
  can then calibrate strictness per paper.
- **Abstracts dossier** — default. Uses `build_source_index` (shared
  with the offline faithfulness metric) so runtime and offline
  judges read the same substrate.

`VERIFIER_SYSTEM_PROMPT` describes both source shapes so the judge
knows to treat chunks and abstracts differently — chunks are the
strongest evidence; abstracts are a lower bound.

## Known limitations

- **Reader-dependent substrate**. The verifier judges against chunks
  only when the reader could extract them (PDF fetch + chunk + rank
  succeeded). When any of those fail, the verifier silently falls
  back to abstracts for that paper — same behavior as before ADR
  0016 for that paper, just per-paper instead of per-run.
- **No per-claim citation cross-check**. If the judge flags a claim
  whose only cited source we couldn't provide, we currently keep the
  claim rather than reclassifying it as `source_unavailable` (which is
  what the offline metric does). Deliberate: the alternative requires
  a per-claim citation index, and the supervisor's `missing_evidence`
  handling covers this case orthogonally.
- **Synthesizer still writes from `paper_analyses`, not `evidence`**.
  Sprint 2 item 5b will swap that so every sentence in the report
  traces to a claim ID.
