# D3 mode ranking development protocol

This development comparison is separate from the preserved diagnostic benchmark.
Policy `workspace-modes-lexical-v1` was declared in `07-ranking-policy-v1.md`
before implementation or observed pool results. No owner/reference labels are
supplied, inferred or fitted. Source-only mechanics are not personal usefulness
or factual-support evidence.

Use the explicitly copied public 40-work JSON and local owner-profile snapshot;
do not query a database or copy private profile/question text into this package.
The report may expose matched interest terms, as authorized. Input hashes and
local paths make the private profile dependency inspectable without publishing it.
Clock: **2026-11-05T12:00:00+00:00**. Default hard filters: no source/access/status
restriction, all dates. All arms use exactly the same filtered visible candidates
and explicit exclusions. No provider, source acquisition or recurrence is enabled.

## Mechanics fixed before pool results

- Learn disables both legacy organizing-question spellings. It retains existing
  authored-term matching, exclusions, hidden-state rules, score rounding and
  five-minute allocation. The candidate ranking remains score ordered. For an
  edition, direct streams are visited round-robin in their first-occurrence order
  in that ranking, retaining within-stream order; then the legacy floor-on-final-
  count exploration cap applies.
- Research uses exactly the declared Q/S/P tuple in policy07, with Q/S eligibility
  independent of profile/stream overlap. The comparison's question-only, profile-
  only, combined Research and chronological arms share that Q/S-eligible pool.
  Learn's full visible pool is reported separately, never graded by question recall.
- Date clarification declared to ROOT before pool results: publication/update
  only, with existing update-before-publication precedence; an invalid/naive date
  remains unknown. No announced, fetched, first-seen or identifier date is used as
  a substitute. Missing dates remain eligible under a date window and last in the
  chronological diagnostic, with their chronological evidence rank unscored.
- Research ties: descending `(Q>0,Q,S,min(1,P/24),known freshness)`, ascending work
  id. Question-only uses descending `(Q,S)`, profile-only descending `P`, both
  then ascending work id. Chronology uses known dates descending, unknown last,
  then work id. First duplicate work occurrence after shared filters is retained;
  duplicate counts remain explicit.
- No reference judgments exist in this comparison. Recall, precision and owner
  usefulness remain null; zero quality denominators are not invented. Every item
  exports null owner usefulness/reason/reference relevance. Rank movements are
  ordering diagnostics only.

## Outside-interest manual walkthrough selection

ROOT requested a real paper with zero P and positive Q. As a transparent
development fixture, select the first ascending work id among actual copied
papers with declared-profile keyword score zero. Form a proposed question from
that paper's retained public title: `What does "TITLE" investigate?`, empty scope.
This intentionally demonstrates eligibility outside interests; it is an exact-
title development lookup, not an owner question, human label or unseen evaluation.
If no such paper exists, report the gap instead of fabricating a candidate.
No record is created in a project database by this selection.

## Reproduction

From the worktree root, use the existing locked Python and sentinel environment:

```bash
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true WORKSPACE_SCHEDULE_APPROVED=false \
  /Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
  -m tools.workspace_mode_ranking_report \
  --items outputs/modes-d0/public-pool.json \
  --profile outputs/modes-d0/owner-profile.json \
  --project planning/14-explore-and-research-modes/evidence/ranking/development-project.json \
  --now 2026-11-05T12:00:00Z --minutes 15 --days 0 \
  --output outputs/mode-ranking-replay-new
```

The CLI refuses an existing output directory. It writes escaped Markdown/HTML,
raw per-item components/ranks/denominators and input/source digests. The original
benchmark questions, corpus, rankings, thresholds, outputs and freezes are untouched.
