# Predeclared deterministic mode ranking v1

Recorded before mode implementation or comparison results. Policy identity:
`workspace-modes-lexical-v1`. This is a development comparison, separate from
the preserved diagnostic benchmark and its frozen thresholds. No owner labels
are supplied or inferred.

The pool is the same retained public works, with the same owner visibility,
explicit exclusions, source/access/read-state/date filters, cutoff and clock in
every comparison. Terms use the existing Unicode tokenization, stop words and
authored topic descendant/literal resolver. Ties end with ascending work id.
Missing publication/update dates receive no freshness bonus, and remain missing
in the chronological diagnostic; acquisition dates and identifiers are not dates.

## Explore & Learn

Ignore the legacy organizing question. Reuse the declared-interest score:
`min(24, 4 * number of matched declared terms) + known freshness bonus - read
penalty`. Freshness is `max(0, 3 - 0.4 * age_days)` from the authoritative
publication/update date; read penalty is2. Topic membership respects explicitly
selected streams; custom terms remain explicit. Reasons expose matching terms,
unknown dates and exploration. Five-minute edition slots and the existing
floor-on-final-count exploration cap remain unchanged. Stream variety is a
stable round-robin over already ranked direct candidates before applying the
slot allocator; within each stream the declared score order is retained.
The candidate list itself remains score ordered for inspectable Radar results.
No question, mastery or foundational status is invented.

## Research

Tokenize the saved project question and scope separately. Let `Q` be three times
the number of distinct question tokens in the title plus the number in the
abstract. Let `S` be the equivalent scope overlap. Let `P` be the existing
declared-interest keyword score, with the organizing question disabled.
Sort descending by `(Q > 0, Q, S, min(1, P/24), known freshness)`, then work id.
Eligibility requires `Q > 0 or S > 0`; profile or stream mismatch cannot reject
it. Scope is a relevance signal, not an inferred geographic/dataset hard filter.
Only explicitly selected source/date/access/status filters and exclusions are
hard constraints. Contradictory results are retained. The finite Research
edition takes the first `minutes/5` matches without a profile exploration quota.

Project edits, profile/context-preference revisions, mode, policy and exact
candidate versions bind snapshots/cursors. A different question revision cannot
reuse an old result cursor. A lexical match is not evidence of factual support.

## Offline comparison

Compare question-only `(Q,S)`, profile-only `P`, combined Research ordering and
known-date chronological ordering on the same pool and filters. Export per-item
tokens/components, missing-date denominators, rank changes, duplicates and blank
owner usefulness labels. Any proposed reference relevance is machine-assisted,
never independent human gold. These comparisons assess question retrieval;
daily learning usefulness needs the owner's later review.
