# 0101. Make the funded episode path complete before funding it

- **Status**: accepted
- **Date**: 2026-09-18
- **Deciders**: fable (orchestrator), LE-S builder

## Context

`src/campaign/` can plan a campaign, seal every episode's manifest, open
a durable trajectory, run the graph, reconcile a ledger and write a
report. It has done all of that, three hundred episodes at a time, at
`$0.000000`. What it has never done is run an episode that *cost*
anything, and the owner's eval-fix ledger found eight separate reasons
why the first one would have produced less than it should have:

1. **EL-05 — nothing is persisted.** ADR 0088's own docstring says
   `EpisodeRun.state` is "never persisted whole". The trajectory carries
   node *names*; W08's `source_discovered`, `evidence_extracted`,
   `claim_created` and `plan_created` emitters have zero callers. A judge
   run a week after a funded campaign would have had nothing to read, and
   a judge run during it read whatever happened to be in memory.
2. **EL-01 — there is no live scorer.** `scorer=None` unless
   `--mock-judge`, and `execute_campaign` refuses a campaign that budgets
   judge calls with no scorer. Correctly: scoring less than the protocol
   declared is worse than not running. The consequence was that the
   funded path had no scorer at all.
3. **EL-02 — judge spend lands on the workflow's ledger.**
   `GraphEpisodeRunner.__call__` calls `start_cost_tracking()` and never
   resets it, so a judge call after the graph would be recorded against
   the arm under test and refused by `_check_cost_budget` once the
   *workflow* reached its cap. `judge_cost_usd` and `judge_model_calls`
   were hard-coded `"0.000000"` and `0`.
4. **EL-03 — a scorer exception strands a paid episode.**
   `scores = scorer(episode, run)` sat in a `try` whose `finally` only
   closed the trajectory. A judge that raised left no `completion.json`,
   and the next resume re-ran the whole graph — paying twice for one
   measurement.
5. **EL-17 — the per-episode cap is checked after the graph returns.**
   `bind_effective_cost_cap` had no caller anywhere in `src/campaign/`.
   The only pre-call stop was the deployment-wide `settings.max_cost_usd`,
   and `_reason_for` mapped only `TimeoutError` and `MemoryError`.
6. **EL-15 — two of the packet's stop rules do not exist.**
   `16-w12-approval-packet-draft.md` §5 lists `provider-drift` and
   `judge-failure-rate`; neither had an implementation. `source-drift`
   was enforced at seal time only, which catches a campaign that *starts*
   on the wrong corpus rather than one that changes under a running
   campaign — the case the rule is about.
7. **EL-16 — the rehearsal stops before scoring.** `rehearse` proves the
   funded path up to the credential, which was the whole of the path
   until items 1–3 added more of it.
8. **EL-04 — the CAP-06 smoke has no script.** ADR 0090 closed with five
   things about Anthropic's 1.x behaviour that no test here can
   establish, and "run the CAP-06 smoke" meant improvising five calls by
   hand against a real key.

None of these is discoverable by planning. Every one of them is
discoverable by funding a run and watching it disappoint, which is the
one experiment the approval packet is not allowed to propose.

## Decision

Complete the funded path, at zero spend, before it is funded.

**`episode-state.json`, written before the scorer runs.** One JSON file
per episode directory holding the planner's decomposition, the papers
with their identifiers, the citations, the analyses, the evidence, the
reader's ranked chunks grouped by the paper they came from, the critic's
score and routing decision *per pass*, the abstract-only tally with its
reasons, the verification block, the retrieval window with the ids it
returned, and the run's own outcome. It excludes `messages` and any full
document text, is bounded at 2 MiB, and is run through
`src/contracts/artifact_store.py`'s ADR 0096 structural screen. A
snapshot that will not fit or will not pass is **reduced** through four
declared levels — chunk text, then free text, then identity and counts —
and in the last resort stubbed. It is never refused and never raises,
because the episode it describes has already been paid for.

Two things it keeps are not on the graph's state at all and had to be
observed: the critic's per-pass decision is read off the graph's own
`updates` stream as it goes by (the final state keeps only the last one),
and the abstract-only tally is read from the reader's own log lines,
which is the only place the per-paper *reason* exists.

**`src/campaign/scoring.py::LiveJudgeScorer`, selected by
`--live-judge`.** It reuses `src/eval/runner.py::_compute_metrics` — the
function that already guards each of the five metrics separately and
documents that it never raises — and writes the same `detail["metrics"]`
layout `MockJudgeScorer` writes, so `report.py::_score_block` reads a
live-judged record through the path it already had. It refuses to
construct under `USE_MOCK_DATA=true` or the zero-spend sentinel, the
mirror of `build_mock_judge_scorer`'s guard. It declares
`score_persisted`, so the loop hands it the parse of the file it just
wrote: a re-judge later reads the same bytes.

**The snapshot is what widens the faithfulness judge.** ADR 0100 gave
`measure_faithfulness` a `chunks_by_paper` argument and made it record
`source_scope` either way, and named the campaign as the caller that
would supply it. This is that caller: the snapshot's per-paper ranked
chunks go in, `source_scope="abstract_and_chunks"` comes back, and it is
lifted to the top of the episode's score detail because it is the field
that decides whether two episodes' faithfulness numbers may be averaged
together. `src/eval/runner.py::_compute_metrics` gains one optional
keyword to thread it through — additive, defaulted to `None`, so the
offline runner and the mock judge stay on `abstract_only` and their
records stay byte-identical. A snapshot reduced past level 0 has the
digests and not the text, so the scope degrades to `abstract_only` with
the reason on the record rather than the episode failing.

ADR 0100's other half matters here too: a judged metric whose `score` is
`None` with a reason (`empty_report`, `no_cited_claims`,
`all_sources_unavailable`) is a judge that *answered* and had no
denominator, and is deliberately **not** counted as a judge failure by
the stop rule below. A campaign of blank reports is a finding about the
arm; only a missing metric block is an instrument problem.

**Judges run under their own accumulator and their own cap.**
`judge_cost_scope` swaps `_current_costs` for a fresh `RunCosts`, binds
`judge_cost_usd_max` as the effective cap, and restores both in
`finally`. The episode reports real `judge_cost_usd` and
`judge_model_calls`; a judge cap reached mid-pass nulls the remaining
rubrics with `judge_budget_exhausted` and the episode completes.

**Scoring cannot strand an episode.** The order is persist → score →
complete, and `_score_safely` turns any scorer exception into a null
metric with a reason. An episode that was interrupted between its
snapshot and its receipt is **recovered** on the next pass: scored from
the snapshot, with its node route replayed onto the trajectory, without
the graph running again.

**The episode's workflow cap is bound inside the runner.**
`GraphEpisodeRunner.__call__` binds it as the effective cost cap for the
duration of the episode and releases it in `finally`;
`CostBudgetExceeded` maps to `BUDGET_STOPPED` /
`episode_budget_exhausted` keeping the partial report.

**Three new `StopReason` members**, checked between episodes with
everything already completed kept and counted: `provider_drift` (the
sealed manifest's model routes, price-table date and dependency-lock
digest against the campaign's first episode), `source_drift` (the
resolved corpus mode against the declared one, and the source snapshot
ref against the first episode's), and `judge_failure_rate` (three of the
first ten judged episodes, then more than 10 % cumulative, on **any**
judged metric).

**Three new rehearsal steps.** `state-retention-on` and
`stop-rules-armed` before the credential boundary, where they are free to
prove; `scorer-resolved` *after* it, because a live scorer refuses to
construct under the sentinel and a step placed earlier would report the
funded path stopping at the scorer, which is false.

**`python -m src.campaign smoke`.** ADR 0090's five probes under one
`start_cost_tracking()` and one `bind_effective_cost_cap(cap)`, requiring
the same kind of approval record a campaign does — against the smoke's
own campaign id `camp_cap06_smoke` and stage `cap-06-smoke` — and writing
a JSON receipt with each probe's classification, usage fields, request
ids and cost. The retry probe is classified `observed` / `not_observed`
and never failed on `not_observed`; the induced 4xx uses `max_tokens=0`,
which is refused before any generation and therefore costs nothing.

## Alternatives considered

- **Put the reader's ranked chunks on `ResearchState` behind a flag.**
  The obvious way to get item 1's chunks, and rejected for a mechanical
  reason: `ResearchState` is a *total* `TypedDict` with three initial-state
  constructors, `src/eval/runner.py::_serialize_state` writes the whole
  state into every benchmark record, and the scripted research tier's
  committed baseline is a byte comparison over those records. A new state
  key would move a baseline this order is not allowed to regenerate. The
  chunks are already on the state as `evidence[].source_text` — ADR 0016
  documents it as "the ranked chunk verbatim" — so the snapshot groups
  what is there instead of adding a second copy.
- **Read the abstract-only tally from the ADR 0097 degradation
  observer.** It records `reader_paper_abstract_only` on the trajectory
  and would need no log handler. Rejected because it records the *code*
  and not the stage: "the PDF link was dead" and "the ranker returned
  nothing" are different findings and the observer flattens them. The log
  handler is scoped to one episode and correct at concurrency 1, which is
  the only concurrency the loop offers and the one 16 §3.4 recommends.
- **Let the live scorer raise and let the loop catch it.** Fewer moving
  parts. Rejected because "never raises" has to be a property of the
  scorer as well as of the loop: `LiveJudgeScorer` is usable outside
  `execute_campaign`, and a scorer whose safety depends on its caller is
  a scorer that will eventually be called by something else.
- **Add a public screen function to `src/contracts/artifact_store.py`.**
  Tidier than importing `_screen_text`. Rejected as out of this order's
  file scope, and the alternative — a second copy of the signed-URL,
  credential and private-reasoning patterns — is worse: two copies of a
  refusal rule drift, and the whole point of ADR 0096 was to have one
  narrow, reviewed set.
- **Make the smoke reuse a research campaign's approval record.** Would
  save an owner one record. Rejected: a record covering sixty funded
  episodes should not also, silently, cover an unrelated five calls, and
  an owner approving a small smoke should not have to mint a research
  campaign to hang it on.
- **Fail the CAP-06 smoke when no retry is observed.** ADR 0090 asks for
  `retries_taken` "on a call that actually retried". Rejected: that is a
  smoke that only passes during a provider incident. The classification
  is `not_observed`, with the field's presence and integrality still
  checked — which is the half a 2.x rename would break.

## Consequences

- **Positive**: a funded episode now leaves behind everything a later
  analysis or a re-judge needs, and paying twice for one measurement
  requires deleting a file rather than crashing at the wrong moment.
- **Positive**: judge spend and workflow spend are separate numbers with
  separate ceilings, so `budget_stop_reached` — which sums both from the
  ledger — is summing two real numbers rather than one real and one
  hard-coded zero.
- **Positive**: the per-episode ceiling is enforced between calls. The
  overshoot bound drops from "one whole episode" to "one reader fan-out",
  and 16 §3.4's campaign-scale statement gains an episode-scale twin.
- **Positive**: three stop rules that were rows in a table now run, and
  `rehearse` reports which of them are armed and at what threshold, so a
  packet reviewer reads the rule and the number from the same place the
  loop reads them.
- **Negative**: 300 episodes now write 300 state files. At mock scale
  they are about 2 KB each; on a live campaign with chunk retention on
  they will be substantially larger, which is what `--no-state-chunks`
  and the 2 MiB per-episode bound exist for. The 300-episode mock matrix
  is otherwise unchanged: `$0.000000`, zero model calls, the same
  goldens.
- **Negative**: the snapshot's `papers[].published` is always `null`.
  `src/graph/state.py::PaperMetadata` carries no publication date, and
  the only year anywhere in the state is the one the synthesizer's model
  wrote onto each `Citation`. Recording the absence is the honest
  answer and makes the gap visible to whoever indexes by `(author, year)`.
- **Negative**: `provider_fingerprint` uses the environment's dependency
  lock digest as its proxy for "the SDK changed", because no field on
  `RunManifestV1` carries a library version. It is a superset — an
  unrelated dependency bump moves it too — which is the conservative
  direction for a stop rule and is stated where it is computed.
- **Follow-ups**: LE-E's `rejudge` verb (EL-14) is the `--fill-missing`
  half of the recovery implemented here; the snapshot is the file it
  reads. LE-J's EL-09 faithfulness judge consumes
  `state["evidence"]`, which this snapshot preserves and hands to
  `_compute_metrics`. CAP-06 itself remains unverified until an owner
  runs the smoke against a credential under an approval record: the
  script exists, the receipt schema exists, and no probe has been
  observed live.
