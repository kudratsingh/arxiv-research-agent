# Data, ranking and compatibility

Implementation note, 2026-11-05: the baseline gaps below describe the original planning checkpoint. D0–D4 now implement the versioned [context contract](06-context-api-contract.md) and [ranking policy](07-ranking-policy-v1.md). [STATUS](STATUS.md) separates code, runtime verification and later gated assistance.

## Verified starting point

Inspected controller **dff860e16e89c22382bce88d98f64645dfdcbfc8** (G6 app
fda9d7616e8cbd0d882bcc41510a997ade117bf9). This is a code inventory, not a
claim that the project model below exists.

- `src/workspace/schemas.py`: `ProfileData` has topics, custom topics, exclusions,
  streams, minutes, one research_question, exploration and pinned_entry_id.
  There is no product-mode or project contract. Strict writes forbid extras.
- `EntryData` ties question/note/next-action body to work_id, version_id, anchor.
  Reading revisions and entries carry activity order. Preserve those identities.
- `src/workspace/ranking.py` currently uses the profile question only after an
  interest/custom match. Its `mode` parameter means relevance/chronological/
  keyword ranking, not Explore/Research. Do not overload that enum silently.
- Frozen editions/cursors, version-specific retained availability, provenance,
  optimistic revisions, request-id deduplication and per-owner stores already
  exist. Reuse them, extending their identity inputs when mode/project matters.
- `web/lib/workspace/{queue,urlState,navigation,navigationRuntime}.ts` and
  `web/components/workspace/Reader.tsx` provide shared focus and return behavior.
  `commands.ts` is the keyboard vocabulary. Extend it once for new actions.

The repaired qualification/executor branches and benchmark have later commits
than this frontend baseline. Reconcile those exact source identities before
integrating backend changes; do not treat the controller branch as carrying V8.

## Proposed durable objects (new migrations/APIs required)

| Object | Minimum data and semantics |
|---|---|
| Workspace preference extension | Explicit default product mode; optional learning goals/background, revision-guarded and backwards compatible |
| ResearchProject | owner, stable id, revision, title, question, scope, constraints, status, created/updated/activity sequence |
| ProjectSource | owned project id + shared work id + exact version id + optional retained material/span/anchor; explicit role and annotation link; dedup key |
| ProjectEntry link | project id and existing entry id/revision; reuse note text, do not clone it on mode switch |
| LearningThread | owner/id/revision, declared goal, optional prerequisite and originating project; exact source/entry links and return context |
| Typed research artifact | observation, assumption, hypothesis, comparison or experiment proposal; provenance and authored/generated status; proposed versus tested |
| Mode-specific edition/cursor | product mode, project revision/question digest when applicable, profile revision, policy version, candidate cutoff, source/version snapshots and clock |

Research project context is separate from the legacy organizing profile question.
Offer explicit import/create, with preview and idempotency. Do not mutate the
saved profile when navigating. Add nullable/compatible fields in versioned
migrations; never reset owner data. Ownership checks cover every link and lookup.
Project deletion/archive must not cascade-delete shared work/notes/materials.

The initial endpoint sketch covered project list/detail/create/update,
link/unlink source and entry, learning-thread create/update, and explicit
mode/project-aware discovery parameters. The implemented paths and typed requests
are now in contract06; the original sketch does not override them. Updates use current revision + request_id. Mutation
retries reuse identity; conflicts preserve both local draft and server revision.

## Discovery policies

Use distinct names: **product_mode** selects learn/research, **ranking_order**
selects a diagnostic/baseline ordering. Source/date/access/read-state filters,
explicit exclusions, ownership, frozen cutoff and deterministic ties apply to
all comparable arms. Keep term/reason receipts inspectable.

**Explore & Learn**: declared interests/custom terms, connected stream priorities,
known freshness, bounded novelty/diversity and explicit exploration allocation.
Reading-window rounding and sparse-pool behavior stay truthful. Foundations
can be a transparent curated pool; don’t infer foundational status from age.
Background and goals shape suggestions only when explicitly declared. Existing
question text is optional context, never a requirement for candidate eligibility.

**Research**: project question and explicitly declared scope are primary.
Question match does not require topic overlap. General interests may break ties
or contribute a bounded secondary score; stream membership cannot reject an
otherwise relevant work unless the user explicitly selects a hard source/scope
constraint. Unsupported/contradictory evidence is not discarded merely because
it conflicts with a hypothesis. A lexical score is retrieval relevance, not a
factual-support score. Phase one is deterministic and model-free.

Predeclare formulas before scoring a new comparison. Record policy version,
question/profile revisions, term matches, score components, hard filters, clock,
ties and missing-date treatment. Never infer publication dates from ids or fetch
clocks. Preserve the current frozen benchmark and its original retrieval report;
a separate exploratory query/profile/combined comparison informs the next policy
without retroactively improving old results or claiming owner usefulness.

## Identity and privacy invariants

1. One canonical work can have distinct source observations and immutable
   versions. Project links preserve their selected version; missing versions
   stay unavailable. A newer paper does not inherit an older note's anchor.
2. Evidence references bind material hash, parser revision, source scope and
   exact span/Unicode offsets. A resolving citation id alone is insufficient.
3. Store manual activity separately from generated artifacts and machine-assisted
   proposed annotations. Never populate owner feedback or mastery fields.
4. Local ranking can use saved preferences; sealed remote requests contain only
   approved public evidence unless the owner explicitly approves private context.
5. Mode/project changes affect relevant caches and future request digests. Results
   bound to an older question/source/settings are stale, never silently rebased.
6. Unknown or uncertain completion keeps its ledger receipt and conservative
   liability. UI acceptance and financial reconciliation remain separate.

## Rollout

Read existing data in place; build disposable fixtures for owner isolation,
migrations, conflict and recovery verification. A copy of public context and an
isolated principal is sufficient for the first walkthrough. No writes to owner
3137 data during verification. Preserve all old routes and export/import contracts;
unknown optional mode fields must not break legacy clients. Commit migration and
API contracts under one owner before parallel screen work.
