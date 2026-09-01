# 0061. Bounded Tier-1 session memory

- **Status**: accepted
- **Date**: 2026-09-01
- **Deciders**: kudratsingh
- **Follows**: [ADR 0058](0058-learner-profile-store-and-provenance.md),
  [ADR 0059](0059-guided-read-session-graph.md)
- **Implements**: WO-W05 and Phase W scope ruling SR-06

## Context

A useful coach must remember the learner's goal and yesterday's session, but
putting an unbounded transcript into every turn makes cost grow with tenure and
lets errors in prose summaries displace facts the learner explicitly supplied.
Phase W needs only the 14-day pilot horizon, so SR-06 adopts Tier 1 plus one
previous-session summary and defers weekly/monthly rollups and retrieval.

## Decision

Every new session receives a `tier1.v1` block composed from the principal's
structured profile, current path position, today's bounded session spec, and
the newest valid session summary. The exact compact JSON stays at or below
10,000 characters, the documented tokenizer-free `chars / 4` estimate for a
2,500-token ceiling. Goals, daily time budget, and declared constraints are
never truncated to make that bound: lower-priority skill claims are omitted
first, with `skills_omitted` making the loss visible. Declared claims precede
assessed claims, which precede inferred claims.

The profile serializer remains the provenance-labelled skill renderer. Goals
and constraints live once in the structured block rather than being duplicated
inside that prose render; duplicated prompt text is still billed context.

At the `progress_update` node, session close generates one approximately
150-token summary and an optional inference batch using `tutor_model`. Mock
mode takes a deterministic branch before client construction. Malformed or
ungrounded output discards the complete model response and uses a deterministic
summary with no inferences. Cancellation and the cost ceiling still propagate.

The `session_completed` progress event stores the summary as
`{summary_id, lossy: true, text}`. A `summary:*` id is structurally refused as a
skill claim's `evidence_ref`; summaries are coaching memory, not evidence.
Each accepted inference instead cites `session:<session_id>`. The shared runner
applies the batch only after the graph has returned its close-time final state,
and verifies the provenance and exact session id before calling the
principal-scoped profile store.

For Phase W, session creation reads at most 2,000 principal events to locate the
newest summary. That covers the deliberately small pilot without widening the
append-only progress-store contract. A cursor or dedicated descending read is
required before a long-lived production account can exceed that window.

## Consequences

- Prompt context has a CI-enforced cost ceiling rather than an advisory target.
- Corrupt summary prose cannot replace the learner's structured goal, budget,
  or declared constraints.
- Inference writes happen once, at successful session close, never mid-turn.
- A summary-generation failure loses convenience memory, not the session or an
  evidence-backed learner fact.
- Tier-2 rollups, Tier-3 retrieval, and their summary-drift defenses remain
  explicitly deferred beyond Phase W.
