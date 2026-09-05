# 0075. Give the research lane a free gate, and run the paired path on it

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Phase C assurance program (WO-C1)

## Context

Two gaps, and they turn out to be one problem.

**The research lane has no gate that runs on a pull request.** The
learning lane has had one since WO-W10: `simulate_learner`'s scripted
tier replays fifteen scenarios against the compiled session graph under
`USE_MOCK_DATA=true`, `scripted_tier_check` asserts the campaign was
complete and free, and it is the only gate in this repository that has
ever caught a regression. The research lane's only campaign is
[`src/eval/runner.py`](../../src/eval/runner.py): it drives the real
workflow against real models and real arXiv, it costs money, and the
first funded campaign is still gated on an owner decision (W-OD-1). So
the lane that publishes this repository's headline numbers is checked,
per PR, by nothing at all.

**The statistical apparatus has no caller.** ADR
[0071](0071-eval-statistics-and-gates.md) built
[`src/eval/stats.py`](../../src/eval/stats.py) — `mcnemar`,
`pair_binary_outcomes`, `mcnemar_required_pairs`,
`paired_bootstrap_delta`, `wilson_interval`, the rule of three, the
minimum-N guard. ADR [0074](0074-deterministic-groundedness.md) built
`groundedness.paired_outcomes`, which produces exactly the per-claim
binary outcome McNemar pairs on, with content-derived ids that are
stable across arms. Its own follow-up list says the quiet part:
"`paired_outcomes()` is the shape `src/eval/stats.py`'s McNemar path
wants, and **nothing hands it one yet**." Every comparison
`regression_diff` makes is over aggregate *means*.

The two gaps meet because the missing gate is also the missing caller. A
free, deterministic campaign over twenty benchmark queries is precisely
the thing that can hand the paired path enough claims to say something.

### The asymmetry that shapes everything below

**Mock mode is not an LLM stub.** `USE_MOCK_DATA` swaps arXiv search for
five fixture papers ([`src/agents/search.py`](../../src/agents/search.py))
and gives the tutor and the assessment judge deterministic branches. It
does **not** touch [`src/llm.py`](../../src/llm.py), and the research
graph's planner, reader, synthesizer and critic call `call_llm_json`
under it exactly as they do in production.
[`tests/e2e/conftest.py`](../../tests/e2e/conftest.py) has said so since
WO-A15, and cans the four agents itself for the same reason.

So the session graph runs free on mock mode alone, and the research
graph does not. A research scripted tier has to supply the words the
*model* would have said, where the learning lane's supplies the words
the *learner* would have said.

## Decision

### 1. A scripted research tier: `src/eval/simulate_research.py`

It replays every `BENCHMARK_QUERIES` entry through the **real compiled
research graph** — the real router, the real state reducers, the real
search / reader / synthesizer / critic nodes — with a scripted model
surface installed over the four agents' own `call_llm_json` names, and
writes the durable per-record layout `runner.py` writes
(`runner.CampaignShape`, so crash-safety, `--resume` and the exit codes
are inherited rather than re-implemented).

Named for its counterpart. `simulate_learner` : `simulate_research` ::
`make simulate-learner` : `make simulate-research`. What it simulates is
named in its first paragraph rather than in its filename, because the
filename's job is to be findable next to the module it mirrors.

**The trajectory is the assertion.** The driver uses `app.stream(...)`
rather than `invoke`, so the node sequence comes out of the run itself.
A graph that skipped the reader, looped the synthesizer, or routed a
revision to a node the router cannot dispatch still produces a non-empty
report — which is why `tests/e2e/test_research_workflow.py` asserts on
trajectory, and why this campaign records one per query and gates on it
as an unmet structural expectation.

**The scripted synthesizer is fed the graph's own papers.** The driver
is already reading the `updates` stream, so it hands the surface the
`search` node's output before the synthesizer runs. The citations in a
scripted report are therefore the corpus *this run* retrieved, not a
fixed list: a search that returns four papers, a reader that drops one,
or a citation entry `_parse_citations` rejects all move the claim set
the tier measures. A hard-coded citation list would have reported five
perfectly-grounded claims for a run that retrieved nothing.

### 2. Zero spend, in four layers

Each layer alone would be a hope.

1. **There is no second tier.** `simulate_learner` has a `--tier` flag
   with a funded setting to fall into; this module has neither. The
   funded research campaign is a different module with a different CLI.
2. **It refuses to start when `USE_MOCK_DATA` is false**, the way
   `simulate_learner._config_problem` does — and here the refusal also
   buys *offline*, because live search would leave the machine even
   though no model call could.
3. **A tripwire on `src.llm.call_llm`.** The four agent patches are an
   enumeration, and enumerations go stale. Anything the enumeration
   misses — a new node, a judge, a supervisor branch — raises
   `ScriptedSurfaceBreach` instead of reaching Anthropic.
4. **Every row is asserted zero** by `scripted_tier_check --lane
   research`: three cost columns and two call counts. A dollar figure
   can round to zero; a call count cannot.

The tier is also offline in the reader: `parse_pdf` is stubbed to `""`
so the reader takes ADR [0004](0004-reader-fulltext-with-abstract-fallback.md)'s
abstract-only path. The mock corpus has no local full text, and a per-PR
gate that fetches five PDFs from arxiv.org is neither free nor reliable.

`scripted_tier_check` gains one assertion the learning lane has no
analogue for: `scripted_llm_calls` must be **positive** while
`llm_calls` is zero. Nothing that never ran ever spends, so a campaign
short-circuited to twenty empty records passes every cost check ever
written. The pair is what separates "free" from "absent".

### 3. The paired path, on the campaign

Every scripted record scores `measure_groundedness` over the report the
graph assembled against the corpus it retrieved, and publishes
`paired_outcomes()` on its summary row. `runner.py` publishes the same
field, so the funded lane gets the paired path too — computed by a
second call to the deterministic check rather than by changing
`measure_citation_resolution`, so every published *score* stays
byte-identical and no campaign is rebaselined.

`regression_diff.compare_claims` pairs the two runs' claim maps with
`stats.pair_binary_outcomes` and tests them with `stats.mcnemar`. The
report prints the two arms' grounded rates with Wilson intervals, the
matched and unmatched counts, the b/c/concordant cells, and — the
sentence this ADR most wanted to be able to write — what
`mcnemar_required_pairs` says the comparison would need.

**The unit is `<query_id>/<claim_id>`, not `claim_id`.** A claim id
digests the cited identifier and nothing else, so the same paper cited
under two queries carries the same id. On a fixed five-paper corpus an
un-namespaced campaign-wide union collapses 100 claims into 5.
Namespacing also makes the pair the right thing: the same query's
assertion about the same paper, scored under two arms.

Across repeats, a claim is kept only when **every** repeat that decided
it agreed; a claim whose repeats disagreed is dropped and counted. That
is the rule `paired_outcomes` already applies to an undecidable claim
and `pair_binary_outcomes` to an unmatched one — a verdict an arm could
not reproduce against itself is not evidence about the other arm, and a
majority vote would manufacture one.

### 4. A deterministic lane may promote, and gates on one claim

`MetricLane` gains `deterministic`, and the scripted research lane sets
it. It changes two things, and both are honesty rather than convenience.

**A deterministic campaign that moved nothing may PROMOTE.** The
underpowered-HOLD rule is about *sampling noise*, and this lane has
none: no model is sampled, retrieval is a fixed corpus, the seed is
pinned, and two consecutive campaigns produce byte-identical rows. Being
told that twenty queries "could not have found a regression" would be
false. What the lane genuinely cannot measure is report *quality*,
because the report's words are the harness's — and that limit is the
tier's, not the sample's, so it goes in the sentence instead.

**One adverse discordant claim is a regression.** There is no sampling
distribution for a p-value to be computed against, so requiring
significance would mean waiting for five more claims to break before
saying the first one did. The p-value is still printed, labelled as
descriptive rather than inferential. On a *sampled* lane the usual rule
stands: significant at α = 0.05, in the adverse direction.

This is not decoration. A claim losing its grounding moves
`citation_resolution_rate` by `1 / denominator`, which on this
repository's own scripted campaign is **exactly 0.10** — the flat
epsilon, which `_significant` requires a move to *exceed*. Every
per-metric band stays green and only the pairing fires. That case is a
test, not a hypothetical
(`tests/test_simulate_research.py::test_one_flipped_claim_is_a_rollback`).

Every band on the scripted lane is `(0.0, 0.0)` — zero tolerance — for
the same reason: on a fixed function of the code, a metric that moved
by any amount moved because the product did.

### 5. A committed baseline that cannot go stale quietly

`tests/fixtures/eval/research-scripted/baseline.jsonl` is generated by
`make research-scripted-baseline` from a real campaign, checked by
`scripted_tier_check` *before* it is copied into place, and committed.

A committed baseline is a claim about the world, and an unchecked one is
worse than none: it goes on passing after the thing it describes has
moved. Three mechanisms, in the order they fire:

- **The script versions itself.** `script_digest()` is a SHA-256 over
  the responders' own source, folded with `RESEARCH_DATASET_VERSION`
  into the campaign's `provenance.dataset_version`. Both halves are
  derived, not declared, for the reason `dataset_fingerprint` already
  gives: a hand-maintained version is a constant somebody forgets to
  bump. It is deliberately conservative — a whitespace-only edit bumps
  it — because rebaselining costs seconds and a silently stale baseline
  costs a wrong verdict.
- **A unit test fails first.** `test_it_is_not_stale` compares the
  committed rows' `dataset_version` against the one this checkout
  computes, and names the regeneration command in the failure.
- **The differ refuses second.** `dataset_version` is one of
  `COMPARABILITY_FIELDS`, so a stale baseline meeting a current campaign
  exits **3** — "not comparable; no verdict was reached" — rather than
  reporting a reconfiguration as a regression.

The `tier` string (`research-scripted`) and `mock_mode` are the other
two comparability fields that separate this campaign from the funded
one, so a canned report can never be diffed against a real one, three
times over.

## Alternatives considered

- **Add a `use_mock_data` branch to the four research agents**, the way
  `tutor.py` and `assessment.py` have one. This is the cleanest possible
  answer and would make the research graph free on mock mode alone, with
  no harness patching at all. Rejected here for scope — `src/agents/**`
  belongs to another work order — and it remains the better long-run
  shape. It is recorded as a follow-up rather than dismissed: the tier
  as built would then delete its scripted surface and keep everything
  else.
- **Run the real agents against the disabled key.** Every call would
  make a real HTTPS request, 401, exhaust the SDK's retries, and land in
  each agent's *fallback* path — so the campaign would be slow, online,
  and measuring the degradation paths rather than the product. Not free
  of network, not free of time, and not a measurement of anything.
- **Reuse `tests/fixtures/e2e/research_llm_responses.json`.** The e2e
  tier's canned output is a fixed blob, which is exactly the property
  this tier must not have: its citation list would not follow the run's
  corpus, so a search regression would be invisible and every
  groundedness number would be about the fixture.
- **Parse the identifiers out of the synthesizer's prompt** instead of
  reading them off the stream. It works — the analyses block carries an
  `ID:` line per paper — but it couples the harness to a prompt format
  the synthesizer owns, and a scripted responder that parses prompts is
  one more thing that can break silently. The stream is the graph's own
  record of what each node produced.
- **A flag on `RESEARCH_LANE` rather than a third lane.** Three of the
  funded lane's metrics are paid judges this campaign never runs, so a
  shared lane would put three permanently-null columns on every report —
  the defect ADR 0074 named when it refused to publish
  `quote_verbatim_rate` — and the bands would have to mean two different
  things at once.
- **Gate the funded lane on one adverse claim too.** Rejected: live
  retrieval and a sampled model make a single flip ordinary. The sampled
  lane waits for significance, which is what the exact binomial test is
  for.
- **Wire it into CI in this change.** Deliberately out of scope. The
  tier and its Makefile target land here; the workflow step is a peer
  work order's, and the PR says what the step would be and what it
  costs.

## Consequences

- **Positive.** The research lane has a gate that runs on every PR for
  `$0.0000` and about five seconds of wall clock, and it asserts the one
  thing no unit test in this repository asserts: that the compiled
  research graph runs its five nodes, in order, wired to each other,
  with the citations surviving to the state. The statistical apparatus
  has a caller. The gate can now see a regression that every band it
  owns is blind to.
- **Positive.** `runner.py`'s rows carry `paired_outcomes`, so the
  funded lane inherits the paired comparison the moment a funded
  campaign runs — additively, with no score changed and no campaign
  rebaselined.
- **Negative, and it is the headline limitation.** *The report text in a
  scripted record is the harness's.* This tier measures the pipeline
  around the model, not the model's grounding. It cannot catch a prompt
  change that makes reports worse, and it must never be quoted as a
  quality number. The learning lane's scripted tier does not have this
  limitation, because the product's own mock branch writes the copy it
  scores.
- **Negative.** The mock corpus is five fixed papers, so the campaign's
  denominators are small and structurally uniform: 5 citation claims per
  query, 100 paired claims over the benchmark, and **no quote claims at
  all** (`quote_verbatim_rate` is `null` with reason `no_quotes` on
  every row, honestly). 100 pairs clears
  `mcnemar_required_pairs(delta=0.05, discordance=0.05, power=0.5)` = 77
  and does not clear the 155 the same move needs at 80% power — a
  distinction the report prints rather than a reader having to compute.
- **Negative.** The scripted surface patches module attributes from
  production code. It is confined to one context manager with an
  `ExitStack` restore on every path, and a test asserts the restore
  happens on the exception path — but it is machinery the tier would not
  need if the agents had a mock branch.
- **Negative.** A conservative script digest means a cosmetic edit to a
  responder forces a rebaseline. That is the direction to be wrong in,
  and the command is one line.
- **Follow-ups.**
  - Wire the tier into `ci.yml` beside the learning lane's step, with
    the differ against the committed baseline. Not this work order's.
  - Give the four research agents a `use_mock_data` branch and delete
    the scripted surface.
  - Pass `full_texts` so the quote half of ADR 0074's check has a
    denominator on some lane (tracked as
    `feat/faithfulness-fulltext-source`).
