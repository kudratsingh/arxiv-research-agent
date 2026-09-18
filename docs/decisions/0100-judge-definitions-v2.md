# 0100. Judge definitions v2: identified sources, the writer's evidence, honest empty denominators, and a judge-scoped sampler

- **Status**: accepted
- **Date**: 2026-09-17
- **Deciders**: live-eval fix wave (LE-J), under ruling R12
- **Amends**: [0007](0007-faithfulness-single-call-abstracts.md), [0074](0074-deterministic-groundedness.md)
- **Related**: [0015](0015-verifier-agent-runtime-faithfulness.md), [0070](0070-eval-integrity-provenance.md),
  [0077](0077-model-aware-request-profiles.md), [0095](0095-deterministic-mock-judge-campaign-scoring.md)

## Context

The first funded research campaign is about to buy measurements from three
LLM-as-judge metrics. The owner's fix ledger found four defects in those
judges' *definitions* — not in their plumbing — and the ordering rule is that
definition changes land before any episode is paid for, because a definition
changed afterwards makes the money already spent unusable.

All four were reproduced on `main` at dbd4bb8.

**EL-08 — the faithfulness source index collides.**
`build_source_index` keyed `index[(lastname, paper_year)] = abstract`. Two
cited papers by a Zhang in 2024 produced one entry: the second overwrote the
first, and every `[Zhang, 2024]` claim was then judged against whichever
abstract the loop happened to write last. Reproduced by execution — two
papers in, one entry out, no warning anywhere.

**EL-09 — the judge did not see what the writer saw.**
`FAITHFULNESS_SYSTEM_PROMPT` asked whether each claim was supported "by the
cited paper's abstract", while the reader works from the top
`reader_max_chunks_per_paper` ranked chunks. Every claim drawn from a paper's
body was therefore marked unsupported, and the row reported a blind spot in
the harness as an error in the report. The runtime verifier had already
closed this for itself (ADR 0015's evidence path); the offline metric had not.

**EL-10 — an empty denominator scored 1.0.** In five places:
`_aggregate_claims` (`else 1.0`), `measure_faithfulness` on an empty report,
`_aggregate_coverage` and `_aggregate_retrieval` (`else 1.0`), and
`measure_completeness` on an empty topic list. A run that produced no report
scored a perfect faithfulness mark. This is the defect ADR 0074 closed on the
citation path, still open on the other three, and 07 §7's non-regression
gates name it by name: "no increase in missing/null metric denominators
hidden by aggregation".

**EL-11 — the judges sampled at the workflow's temperature.** The three judge
calls went through the shared gateway with no temperature of their own, so
they inherited `llm_temperature` (0.3) and, passing no `schema=`, always took
the free-text parse path even where the deployment had structured outputs
enabled. A grader that resamples its own verdicts adds variance to every
measurement taken with it, and that variance is indistinguishable on the row
from a real difference between two arms.

## Decision

### 1. Sources are identified by `paper_id`

`build_faithfulness_sources` replaces `build_source_index` on the metric path
and returns one entry per cited paper, keyed by `paper_id`. Each entry gets a
cite key that is unique *within the dossier*: the base `Surname, Year`, plus a
lowercase letter when the base is shared — `[Zhang, 2024a]`, `[Zhang, 2024b]`
— which is the ordinary academic disambiguation and a form the judge already
understands. The paper's title is printed beside the key as a second
discriminator.

The year in the key comes from the arXiv identifier (`2401.xxxxx` → 2024) when
the id is one, with the citation's year as the fallback. The identifier was
written by the retrieval pipeline; the citation's year was written by the
synthesizer, whose output is the thing under examination, and a metric that
takes a document's identity from the text it is checking cannot catch a year
the model invented. Both years are registered as resolution aliases, because
the report's own inline tags were written from the citation list and a dossier
those tags cannot address would trade one silent failure for another.

`resolve_cite` maps a judge's cite back to a paper: an explicit suffix first,
then the base key when exactly one paper answers to it. **Two papers
answering is `ambiguous_citation` and stops there.** The claim abstains, is
excluded from the denominator, and is counted. Resolving it by picking one
would be a coin flip recorded as a measurement — EL-08 in a new costume. The
result also carries `collision_count`: how many cited papers needed a suffix,
which is exactly how many entries the old index would have dropped.

**`build_source_index` keeps its old contract**, and therefore keeps the
collision. ADR 0015 shares it with `src/agents/verifier.py`, whose
abstract-path dossier is built from its keys; changing the return shape would
change a runtime agent's prompt from inside a metrics work order. The
verifier's own exposure is left open and recorded here (see *Open*), rather
than fixed underneath its owner.

### 2. The judge sees the writer's evidence when it is supplied — Option A

`measure_faithfulness` takes an optional `chunks_by_paper`
(`paper_id -> ranked chunk texts`). Supplied, each cited paper's dossier entry
carries those chunks beside its abstract and the result reports
`source_scope: "abstract_and_chunks"`. Omitted, the entry is the abstract
alone and the result reports `source_scope: "abstract_only"` — the ADR 0007
substrate, now *stated* rather than assumed. The prompt was rewritten to
match. Two scores taken at different scopes are two instruments and must not
be averaged.

**This is the one judge whose input grows.** An abstract is a few hundred
tokens; a paper's ranked chunks are several thousand. Faithfulness input
grows roughly three to six times, an **ESTIMATED** +$0.07–0.12 per episode at
present judge pricing — an estimate from token counts and the published price
table, not a measurement, and it stays an estimate until Stage 1 reports real
tokens. Completeness and retrieval recall are unchanged.

Nothing in this repository supplies the chunks yet. LE-S persists the
reader's ranked chunks into `episode-state.json`, and the campaign scorer
passes them from there; until then every caller lands on `abstract_only`,
which is the pre-existing behaviour with a label on it.

### 3. An empty denominator is `None` with a reason

All three judged metrics now publish `score: float | None` beside a `reason`,
following ADR 0074's pattern exactly:

| Condition | `score` | `reason` |
|---|---|---|
| Empty report | `None` | `empty_report` |
| Judge extracted no cited claim | `None` | `no_cited_claims` |
| Claims extracted, none decidable | `None` | `all_sources_unavailable` |
| No expected topics | `None` | `no_expected_topics` |

The last two empty faithfulness cases are kept apart because they have
different owners: "the judge found nothing to check" is a report that did not
cite, and "we could not check anything the judge found" is a retrieval or
plumbing failure. A retrieved set that covers none of its topics still scores
0.0 — that denominator is not empty and the zero is earned.

Every consumer was checked. `runner._get_score` already read a non-numeric
score as `None`; `regression_diff._score` and `readme_update._mean_or_none`
already skip `None` and already state their shrunken denominators;
`report.py::_metric_row` reads only the integer count fields, which keep their
names, meanings and types.

### 4. The judges sample at 0.0, under their own schema

`eval_judge_temperature` (default 0.0) joins the evaluation-integrity settings
block, and `src/llm.py` grows an additive per-call `temperature` override
threaded through `call_llm_json` → `call_llm` → `resolve_profile`. The
override changes *which* temperature is considered, never *whether* one is
sent: a model whose capability row rejects sampling parameters still receives
none, so ADR 0077's guarantee is intact and an override cannot turn a working
request into an HTTP 400.

Each of the three judge calls now passes its own pydantic output model as
`schema=`, so a deployment with `enable_structured_outputs` on constrains the
judge's response. **Judge model only**: the workflow arm is untouched, which
is what keeps this a change to the instrument rather than to the thing being
measured.

Every judged result carries a `judge` block — model, the temperature actually
sent (`None` when the row refused sampling), whether the schema was actually
sent, and the schema's name — because "the grader was resampled" and "the arm
got worse" are otherwise the same row.

The three response models live in `src/eval/metrics.py` and the mock judge
(ADR 0095) now aliases them instead of declaring a second, stricter set of its
own; a harness that can satisfy a shape the real judge was never asked for is
not a harness. They are deliberately *shapes* — names, types,
`extra="forbid"` — with no length or pattern constraints, because a constraint
on the structured path is a whole-call failure and every bound worth enforcing
is enforced by the aggregators, which must keep working on the free path
anyway. Their base class is declared locally rather than imported from
`src.contracts.kernel`, because
`tests/e2e/test_contract_shadow_research.py` requires that importing
`src.eval.runner` loads no contract module at all.

### 5. Rubric versions

`completeness`, `faithfulness` and `retrieval_recall` go to **2.0.0**;
`groundedness` stays at 1.0.0, untouched. `tests/fixtures/eval/rubric_lock.json`
gains one appended entry each, and the versions propagate into the eight
`eval_registry/` objects that record them and into both `campaigns/*.plan.json`
digests, all regenerated by their own `produced_by` commands. `regression_diff`
already refuses to compare across a rubric-version change (exit 3), which is
what stops a 1.0.0 baseline being diffed against a 2.0.0 candidate.

#### Why the two topic rubrics moved too

Completeness and retrieval recall changed as *instruments* — a null empty
denominator, a pinned temperature, an enforced schema — but their grading
criteria did not. The lock binds a version to prompt text and refuses to
re-lock a version against an unchanged digest, so a version bump requires the
prompt to move. Each therefore took one truthful edit: the response-format
paragraph now says the object alone is wanted and that this is the schema the
structured path enforces, and each adds "add no topic that was not given to
you". Nothing about what counts as covered changed. The bump is honest on its
own terms — 2.0.0 asserts that scores either side are not comparable, and they
are not.

## Consequences

- Every existing research baseline is invalidated for the three judged
  metrics. That is the point of the version bump, and `regression_diff`
  enforces it.
- Three metric results grow fields (`reason`, `judge`, and faithfulness's
  resolution counters and scope). All additive; ADR 0070's no-rename rule
  holds.
- A campaign that supplies reader chunks pays more for faithfulness and gets a
  number about the report rather than about the abstract. The two scopes are
  not comparable and the result says which one it is.
- The mock judge still scores the 300-episode matrix at $0, still makes
  exactly three rubric calls per episode, and still exercises blinding and
  position randomisation.

## Alternatives considered

**Resolve an ambiguous cite by picking the best match.** Rejected. There is no
evidence in a `[Zhang, 2024]` tag that distinguishes two Zhangs, so any rule
is a guess, and a guess recorded as a verdict is the defect rather than its
fix. Abstention costs a claim from the denominator and says so.

**Give the judge the full parsed PDF.** Rejected for this wave. It would judge
against text the writer never read, which measures a different thing, and it
needs a per-paper cache read that ADR 0074's follow-up already declined to put
behind a guard whose only failure mode is `None`.

**Score an empty denominator as 0.0.** Rejected. A run that cited nothing is
not a run that cited everything wrongly. `None` plus a reason is the only
answer that does not invent an observation.

**Pin the judge temperature by setting `llm_temperature=0.0` for eval runs.**
Rejected: it would change the workflow arm as well, so the thing measured and
the instrument would move together and neither effect could be attributed.

## Open

- **The verifier still collides on `(surname, year)`.** `build_source_index`
  keeps its ADR 0015 contract, so `src/agents/verifier.py`'s abstract-path
  dossier still loses one of two same-surname, same-year papers. Its evidence
  path (ADR 0016) is unaffected. Closing it means changing a runtime agent's
  prompt and belongs to that file's owner;
  `tests/test_metrics_faithfulness.py::TestBuildSourceIndexIsTheVerifiersAdapter`
  pins the current behaviour so the follow-up cannot be lost.
- **No caller supplies `chunks_by_paper` yet.** Until LE-S lands, every
  faithfulness score in this repository is `abstract_only`.
- **The +$0.07–0.12 figure is an estimate.** It is re-derived from measured
  tokens at the Stage-1 checkpoint.
