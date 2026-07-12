# 0032. Follow-up conversation mode

- **Status**: accepted
- **Date**: 2026-07-12
- **Depends on**: ADR
  [0025](0025-fastapi-async-job-model.md) (job model),
  [0028](0028-postgres-paper-cache-and-embedding-cache.md) (Postgres pool),
  [0029](0029-nextjs-web-ui.md) (web UI)

## Context

Single-shot queries were fine for demo purposes but they leave a
gap: a real research session is rarely one question. A reviewer
who reads a briefing about hallucination mitigation naturally
follows up with "how do these compare on cost?" or "what changed
in the last six months?" — and the client shouldn't have to
copy-paste prior context back into the next prompt.

Sprint 5 PR 4 closes that gap. Multiple jobs bundle into a
**conversation**; the planner on follow-up queries sees a
retrieval-augmented slice of prior reports so it can build on
what's already known rather than starting from zero.

## Decision

New `Conversation` abstraction linking N jobs, with three moving
parts:

- **Postgres-backed storage** for conversations + their job
  membership (with report bodies stored inline).
- **Retrieval-augmented planner context**: prior reports get
  chunked by markdown section, embedded via the shared MiniLM
  pipeline, and the top-K matching chunks against the new query
  land in the planner's system prompt.
- **Sidebar + threaded main-view UI** in the Next.js app.

### Storage

Two Postgres tables in the existing pool (ADR 0028):

```sql
CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE conversation_jobs (
    conversation_id TEXT NOT NULL
        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    job_id          TEXT NOT NULL,
    ordinal         INTEGER NOT NULL,
    query           TEXT NOT NULL,
    report          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, ordinal)
);
```

`ConversationStore` is a Protocol with two impls: `InMemory`
(default) and `Postgres`. Selection via
`settings.conversation_store`; mirrors the JobStore / PaperCache /
EmbeddingCache pattern. The report body is stored inline on
`conversation_jobs` rather than joined from the JobStore. Trade-off:
duplicates the storage of `Job.result` (~5-20 KB per report), but
means the retriever never needs the JobStore online, and a
conversation survives Redis job-record retention expiry cleanly.

`ON DELETE CASCADE` on the FK — deleting a conversation deletes
its rows in `conversation_jobs` without a two-phase call.

### Retrieval-augmented context

`src.api.retriever.retrieve_prior_context(conversation, new_query,
top_k=5)` returns the top-K prior-report chunks by cosine
similarity to the new query.

- **Chunking**: reports get split by ATX-style markdown headings
  (H1/H2/H3), then each section is size-capped to
  `MAX_CHUNK_CHARS=900` (~225 tokens). Sections shorter than
  `MIN_CHUNK_CHARS=80` are dropped as noise.
- **Embedding**: reuses `src.tools.embeddings.encode_texts`,
  which routes through the embedding cache from ADR 0028. Repeat
  chunks (same conversation, same section) get cached vectors —
  cost approaches zero after warm-up.
- **Ranking**: L2-normalized dot product against the query
  embedding. No FAISS index — conversations rarely produce more
  than tens of chunks, and a straight NumPy dot is cheaper +
  cleaner.
- **Attribution**: each returned chunk carries `job_id`,
  `ordinal`, `query`, `section`, and `text` so the planner
  prompt can label snippets by their source turn.

`format_context_for_planner(chunks)` produces a compact prompt
block:

```
## Prior findings from this conversation
[query 1: hallucination survey · section: Training-time approaches]
RLHF-V uses fine-grained correctional feedback…

[query 2: cost tradeoffs · section: Comparing the three approaches]
Chain-of-Verification pays inference cost per response…
```

The block is prepended to the **user** message on the planner
(not the system prompt) — that way `enable_prompt_caching` (ADR
0022) still gets full-hit cache reads on the static system
prompt across turns, and only the per-turn user message differs.

### Planner integration

`ResearchState` gets a new `prior_context: str` field.
`_build_user_prompt(state)` prepends it above any critique. The
runner populates the field in the initial state when
`job.conversation_id` is set and the conversation has jobs —
otherwise it stays blank, so single-shot queries are unchanged
byte-for-byte.

### API surface

New endpoints under `/conversations`:

- `POST /conversations` — create; body `{title?}`. Returns 201
  with full `ConversationDetail`.
- `GET /conversations` — list, sidebar view (no job bodies).
- `GET /conversations/{id}` — full thread including every job's
  report.
- `DELETE /conversations/{id}` — 204 on success, 404 if missing.

`POST /research` gains an optional `conversation_id` field. When
set:
- 404 if the conversation doesn't exist (fast-fail before the
  workflow starts).
- The runner retrieves prior context and injects it into
  `state.prior_context`.
- On success the completed job is `append_job`'d to the
  conversation — this is what makes each turn's report available
  as context for the next.
- The first job's query auto-titles a conversation that was
  seeded with the default "New conversation" placeholder.

`Job.conversation_id` field is optional; carried through
`JobDetail` so a client GET can identify the conversation
without an extra lookup.

### Web UI

New route `/c/[id]` and a sidebar layout across both routes:

- **Sidebar** — conversation list, most-recent-first. "+ New
  conversation" button POSTs a fresh conversation and navigates.
  Delete button on each item.
- **Home page (`/`)** — landing card. First query creates a
  conversation implicitly and redirects into `/c/[id]`.
- **Conversation page (`/c/[id]`)** — threaded main view.
  Historical turns render as accordion cards (collapsed by
  default; latest auto-expanded on load). New-query input pinned
  at the bottom. When a turn is in flight, its progress + plan
  review + report render inline under the historical turns until
  it settles, then the conversation reloads and the fresh turn
  becomes another accordion card.

`useResearchStream` grows a `SubmitOptions` param with
`conversation_id` and `onDone`. The threaded view uses `onDone`
to trigger a fresh `GET /conversations/{id}` after each turn.

## Alternatives considered

- **Full prior reports appended verbatim.** Simplest to
  implement; costs scale linearly with conversation length. A
  three-turn conversation could easily push 15k+ tokens into the
  planner prompt. Rejected on cost.
- **Summary of prior reports only.** Each completed job produces
  a ~200-word summary that follow-ups see. Bounded but lossy;
  adds a summarization step per job and a summary quality bar.
  Rejected as premature — retrieval covers the "give me the
  relevant bits" use case without the extra LLM call.
- **Full prior queries in the system prompt.** Would preserve
  the prompt-caching hit rate but bloats the system prompt with
  content the planner sometimes doesn't need. Chose per-turn
  user-message injection instead so the system prompt stays
  static + cacheable.
- **FAISS index for retrieval.** Overkill at ~20-40 chunks per
  conversation. Cost/benefit doesn't add up until conversations
  reach hundreds of turns; a straight `numpy.dot` is faster to
  read and matches the "we only need top-K, not similarity
  search over a corpus" shape.
- **Redis for conversation storage.** Considered for symmetry
  with the JobStore. Rejected: conversations are durable content
  (a user expects their thread to survive process restarts and
  Redis TTL windows). Postgres already exists in the stack for
  the paper cache; adding tables to it costs nothing new.
- **Store `job_id`s only on `conversation_jobs`; JOIN in the
  JobStore for report bodies.** Cleaner normalization; couples
  the ConversationStore to the JobStore's schema and lifecycle
  (Redis-backed jobs expire on TTL from ADR 0027). Rejected —
  the inline `report` column is a small ergonomic + reliability
  win.
- **Auto-title via LLM summarization of the first query.** Nicer
  titles; extra 500-1000 token LLM call per conversation.
  Rejected for now: truncate to 80 chars with an ellipsis.
  Cheap, predictable, boring. LLM titles are a follow-up.
- **Streamlined single-page threaded scroll (no sidebar).**
  Simpler layout; loses easy switching between conversations.
  Rejected because the sidebar is what makes the "come back to
  a thread from last week" workflow real.
- **Modal-based follow-up on the existing single-shot page.**
  Cheapest change; sacrifices browsability. Rejected.

## Consequences

- **Positive.** The demo tells a two-turn story cleanly: run a
  query, read the briefing, ask a follow-up that references the
  briefing without re-quoting it. Postgres persistence means a
  conversation survives across API restarts and horizontal
  worker scaling. Retrieval + planner integration is bounded by
  `conversation_context_top_k` (default 5), so token spend stays
  predictable regardless of conversation length. The embedding
  cache (ADR 0028) makes second-turn planning almost free on
  embedding cost.
- **Neutral — inline report duplication.** `conversation_jobs`
  stores each report body separately from `Job.result`. Under
  Redis-backed jobs with 1-hour TTL, that's a feature: reports
  outlive the Redis window naturally in conversation context.
  Under Postgres-backed storage of both, it's ~5-20 KB
  duplicated per turn, which is a rounding error.
- **Negative — planner prompt cache invalidation.** The
  `prior_context` block lands in the **user** message, so the
  static system prompt keeps its cache hit rate. But the user
  message is per-turn, so the "user prompt cache" hit rate for
  the planner drops to zero when a conversation is active. This
  is intended; per-turn context is per-turn by definition.
- **Negative — no cross-worker resume for the sidebar's live
  updates.** Follows the same worker-affinity story as SSE (ADR
  0027) and HITL (ADR 0030). Documented.
- **Follow-ups.**
  - **LLM-generated conversation titles** on first-turn
    completion. Small extra call, nicer titles.
  - **Cross-conversation retrieval** — treat the whole
    corpus of prior conversations as a search space when a new
    conversation starts. Requires index tuning.
  - **Turn-level cancel** during a follow-up — currently the
    threaded view surfaces the progress but not a cancel button
    for the in-flight turn. Same infra as the ADR-0030 cancel
    action; UI hookup only.
  - **Server-sent conversation updates** for the sidebar so a
    second browser tab picks up a new conversation without a
    reload. `EventSource` on `/conversations/stream` would work
    naturally with the existing SSE plumbing.
  - **PostgresConversationStore.update_title(...)** so the
    first-turn auto-title actually persists under Postgres
    (in-memory works today via mutation; Postgres needs an
    explicit UPDATE). Small follow-up.
