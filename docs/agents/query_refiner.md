# Query refiner agent

Recovery action for weak search results. When the supervisor picks
`refine_query`, this agent produces a fresh set of arXiv search
queries targeted at coverage gaps — verifier `missing_evidence`,
critic feedback, sub-questions not yet answered — and replaces
`state.search_queries` with them so the next `search` action tries
something different.

Source: `src/agents/query_refiner.py`. Design rationale: ADR
[0018](../decisions/0018-query-refiner-recovery-action.md).

The refiner is **supervisor-only**. Under the fixed pipeline it is
never wired. `enable_query_refiner` is independent of every other
Sprint 2 flag so its lift can be measured separately.

## Inputs

Reads from `ResearchState`:

- `query` — original research question.
- `sub_questions` — planner decomposition.
- `search_queries` — currently in flight (about to be replaced).
- `tried_search_queries` — history of every query the loop has run
  in this workflow. Used for dedup.
- `papers` — already retrieved; titles + abstract heads inform what
  territory is covered.
- `missing_evidence` — verifier-reported gaps (when available).
- `critique` — critic feedback (when available).

## Outputs

Writes to `ResearchState` (only on success):

- `search_queries` — replaced with the refined set.
- `tried_search_queries` — extended with what was in
  `search_queries` at entry.
- A `messages` entry (`AIMessage` named `"query_refiner"`).

On fail-closed rounds (LLM error, non-list response, empty output,
all duplicates), only the `messages` entry is returned — search
state stays intact.

## Fail-closed policy

The refiner never blanks `search_queries`. Four failure modes fold
into the same "keep current" branch:

| Trigger | Log key |
|---|---|
| LLM exception | `query_refiner_kept_current` (reason: `LLM call failed (...)`) |
| `queries` field is not a list | same (reason: `LLM returned non-list 'queries' field`) |
| Filtered set is empty (empty LLM output or all duplicates) | same (reason: `LLM returned no queries distinct from history`) |

Rationale: repeating a weak query is worse than nothing but strictly
better than searching for nothing. The loop stays alive; the
supervisor can pick a different action next.

## Dedup

Two-level:

1. **Prompt-side**: the system prompt tells the LLM never to repeat
   an already-tried query, even paraphrased, and to return `[]` if
   it can't find a genuinely new angle.
2. **Server-side**: the refiner normalizes every candidate
   (lowercase + strip), rejects those in
   `tried_search_queries ∪ current search_queries`, and dedupes
   duplicates within the current batch (first-occurrence order).

Prompt-side dedup catches "why did the LLM repeat itself?" bugs
during dev; server-side dedup is the load-bearing guarantee.

## Prompt shape

**System**: role + rules (no repeats, prefer gap-targeted queries,
concise keyword phrases, cap at `query_refiner_max_queries`).
Response schema is `{queries: [...], reason: "..."}`.

**User**: original question + sub-questions + all already-tried
queries + retrieved-paper block (title + first 40 words of abstract
per paper) + verifier `missing_evidence` + critic feedback (if any).

Kept short-ish by design — abstract heads instead of full abstracts,
flat lists everywhere.

## Configuration

Settings that drive the refiner (see `src/config.py`):

- `enable_query_refiner: bool = False` — master flag. When off,
  `refine_query` is stripped from the supervisor's action enum and
  the workflow doesn't wire this node.
- `query_refiner_max_queries: int = 5` — cap on queries emitted per
  invocation. Interpolated into the system prompt and enforced
  server-side.

No refiner-specific cost / iteration caps — the supervisor's
`max_cost_usd` and `max_loop_iterations` gate every node including
this one.

## Testing

- Unit: `tests/test_query_refiner.py` — 20 tests covering the prompt
  builder (already-tried listing, missing evidence, critique
  inclusion, papers block), normalization, all four fail-closed
  paths (LLM exception, non-list, empty output, all duplicates),
  and the happy path (fresh queries land in state, history extends,
  within-batch dedup, non-string entries dropped, config cap
  respected).
- Supervisor gating: `tests/test_supervisor.py` — 8 additional tests
  covering the `enable_query_refiner` flag (`refine_query` accepted /
  rejected, state summary contents, router behavior with stale
  checkpoints).

## Known limitations

- **No search-side caching**. The refined queries can retrieve
  papers that overlap with what was already found; there's no dedup
  at the paper level (only at the query level). Sprint 4 item.
- **Verifier-independent gap signal only**. The refiner reads
  `missing_evidence` and `critique` but not `unsupported_claims` —
  the latter is a synthesis-level problem, not a retrieval one.
