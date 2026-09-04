# Evaluation

Offline evaluation of the full research workflow. Distinct from the
in-loop `critic` agent (which scores a single run's draft) — this
pipeline runs the whole system on a fixed benchmark, computes
system-level metrics, and produces a report so we can measure the
effect of code changes on end-to-end quality.

Living under `src/eval/`. Design decision: [ADR
0005](decisions/0005-custom-eval-over-ragas.md) — custom in-repo eval
rather than adopting Ragas / DeepEval / LangSmith.

## Goals

- Detect regressions in end-to-end report quality when we change
  agent prompts, retrieval, or the model.
- Compare the impact of specific changes — e.g. swapping the embedding
  model, tightening K in the chunk ranker, adjusting the critic
  threshold.
- Produce a durable eval report artifact that ships alongside major
  merges to `main`.

## Non-goals

- Human eval. The benchmark is automated and cheap enough to run in
  CI; human eval is a separate, later track.
- Live scoring inside a production run. That's the `critic` agent's
  job.

## Components

### `src/eval/benchmark_queries.py`

Twenty hand-curated ML/AI research questions with `query_id`, `query`,
`domain`, `expected_topics`, and `notes` (the original ten were
doubled by ADR
[0013](decisions/0013-sprint-1-finish-retry-checkpoint-tracing-recall.md)).
Coverage across hallucination, retrieval, alignment, reasoning,
fine-tuning, multimodal, efficiency, evaluation, architecture, and
safety.

Since ADR [0070](decisions/0070-eval-integrity-provenance.md) each query
also carries **dataset provenance** — `author`, `created` and `license`
— because a benchmark whose origin nobody recorded cannot support a
claim about the system it scores (NIST AI RMF **MEASURE 2.1** asks for
exactly this). The values are honest rather than tidy: two authoring
dates (`2026-07-05` for the original ten, `2026-07-07` for the Sprint 1
expansion), one author, and `license: "UNLICENSED"` — this repository
ships no `LICENSE` file, so the query text carries no grant, and
inventing an SPDX id here would be a licensing claim the repository does
not make.

**One query is contaminated, and says so.** `hallucination-mitigation`
is annotated *"well-covered by the built-in mock papers"*. That is a
contamination note, not a comment: its retrieval recall is scored
against papers hand-picked to match it, so the number reads high for a
reason that has nothing to do with search quality. A test asserts the
annotation survives every edit to the file.

`RESEARCH_DATASET_VERSION` is a **fingerprint of the list's own
contents** — `research-benchmark@20:<sha256[:12]>` — computed at import
and recorded on every summary row. Derived rather than declared, so
there is no constant anybody can forget to bump: edit a query and the
version moves, and a regression diff can see that the *benchmark*
changed rather than the system. `simulate_learner` does the same for the
scenario set as `LEARNING_DATASET_VERSION`.

Invariants (protected by `tests/test_benchmark_queries.py`):
- IDs are kebab-case slugs, unique
- Every query is non-empty and ends with `?`
- `expected_topics` is a non-empty list of non-empty strings
- Domain diversity: at least 5 distinct domains
- Every query names an author, an ISO creation date and a licence
- The contamination note on `hallucination-mitigation` is still there

### `src/eval/learning_benchmark.py`

The guided-read benchmark, for the learning agent rather than the
research workflow (Phase W, WO-W08). Its unit is a **scenario** — a
learner persona × a paper from the flagship reading path × a
deterministic script of what the learner types — because a tutoring
session is a conversation, not a single query.

Fifteen scenarios over the three personas from the plan (novice
undergrad, career-switcher, time-poor industry engineer) and the eight
papers of the "Reading your first papers" path. Scripts cover the
behaviours the design calls load-bearing: *declares 10 minutes*,
*answers wrongly then self-corrects*, *tries a prompt injection in the
explain-back*, plus the honesty edges (overclaims a declared skill,
abandons mid-session, disengages into one-word answers).

`ScenarioExpectations` is deliberately structural — plan size, whether
a downscope must be stated, which progress events must exist, which
declared skills must survive — so the scripted tier can run in CI with
zero spend. Judge-scored qualities live in the metrics module.

Invariants (`validate_benchmark()`, asserted by
`tests/test_learning_benchmark.py`):
- Scenario / persona / paper ids unique; scenario ids kebab-case
- Every script opens on a `check_in` and closes on an `explain_back` or
  `end_session`, with dense, ordered turn indices — the simulator's
  stop condition
- Personas may only carry `declared` skills at `confidence = 1.0`
- Close-read / skim section names come from
  `src/tools/chunker.SECTION_HEADERS` — the same detector the briefing
  guidance is keyed to
- Only progress-event kinds Phase W actually writes may be expected
- An `unassessed` outcome and an `assessment` event are mutually
  exclusive — no fabricated grade
- Coverage: a scenario per persona, a time-poor script, an adversarial
  script whose canary is actually planted in a turn

### `src/eval/learning_fixtures.py`

Loader and validator for the fixtures the learning judges score against
(`tests/fixtures/learning/`), indexed by a `manifest.json`. Two kinds,
and the difference is enforced, not documented: **hand-authored**
fixtures name no generating commit and set `mock_mode: false` because
nothing generated them; **recorded-mock** fixtures must name the commit
and the mock mode that produced them. No fixture may set
`real_session: true`, and every disclaimer must contain
`"Not a real learner session."` verbatim.

Shipped now: four session plans, including the honest-downscope /
budget-ignoring pair on one 10-minute scenario that the plan-coherence
judge has to score differently, three hand-authored transcripts (an
evidence-linked assessment, an unassessed close, a contained
injection), and — since WO-W11 — fifteen **recorded** ones, below.

#### The recorded mock-session transcripts

The `recorded_mock_session_transcripts` set was shipped `pending` on
WO-W03 with its completion condition written down as an executable
instruction rather than a promise, and `validate_fixtures` *failed* if
a pending set held any file — so nothing hand-written could be dropped
in and inherit the credibility of a recording. WO-W03 merged, WO-W10
built the driver, and WO-W11 executed the condition: one transcript per
scenario in `LEARNING_SCENARIOS`, recorded by replaying it through
`build_session_workflow()` under `use_mock_data=true` with the
disabled-key sentinel, each stamped with the generating commit and
`mock_mode: true`. The manifest entry is now `complete`, and the same
validator that forbade files there now requires them.

Re-record after any change to the session graph or tutor copy:

```bash
make record-learning-fixtures
# or, explicitly:
USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled \
ENABLE_CHECKPOINTING=true \
  python -m src.eval.record_learning_fixtures
```

`src/eval/record_learning_fixtures.py` is not a second driver — it
calls `simulate_learner.drive_session`, the same code the benchmark
runs, so the fixtures cannot drift into being recordings of a private
simulator. It refuses to run outside mock mode and refuses to write a
fixture that names no commit.

A transcript holds the turn-by-turn messages and the progress-event
summaries, not the session's close summary (`draft_report`), so a copy
change confined to the close line re-records to a commit-stamp-only
diff — as WO-W03b's did. That is the recorder working, not a stale
recording: the close line is covered by
`tests/test_simulate_learner.py`, which scans everything
`learner_facing_copy` collects.

Two properties make "these are recordings" checkable, and
`tests/test_record_learning_fixtures.py` asserts both:

- **Deterministic.** The graph mints a fresh run id per session and
  writes it into every `evidence_ref`; the recorder substitutes it for
  a stable id derived from the scenario id, and nothing else is
  rewritten. Two recordings of the same code are byte-identical.
- **Fresh.** A re-recording must reproduce the committed files byte for
  byte, apart from the commit stamp. When that test fails, the fix is
  to re-record and commit the diff — a change in tutor copy *should*
  show up in the files that claim to be recordings of it.

Two vocabulary items belong to recordings alone, because they describe
what the graph did rather than what a scenario hoped for. A recording's
`assessment_outcome` may be `recorded_ungraded` (ADR 0060's honest
record when an explain-back was taken and no calibrated judge scored
it), in which case it is deliberately *not* checked against the
scenario's `expected_assessment` — that expectation describes a graded
session, and writing `strength` into a file the mock graph never graded
is exactly the fabrication these rules exist to prevent. And a learner
turn may carry the intent `simulator_filler`, marking a turn the
simulator filled with its content-free line rather than one the
scenario scripted. A hand-authored fixture may use neither.

### `src/eval/simulate_learner.py`

The learner-simulation benchmark (Phase W, WO-W10). Replays a scenario's
scripted turns against WO-W03's compiled session graph and scores the
session, one record per scenario per repeat. Two tiers — a free scripted
one that runs against mock mode, and a funded one gated on W-OD-1 — and
the campaign discipline of `runner.py` reached through
`runner.CampaignShape` rather than copied. Full treatment in
[Learner-simulation benchmark](#the-learner-simulation-benchmark-phase-w)
below.

### `src/eval/metrics.py`

Four metrics, each of which landed as its own PR so the design and
prompts got scrutinized independently:

- **Citation accuracy**. Pure regex + set
  membership over `(first-author-lastname, 4-digit-year)`. Handles
  `[Smith, 2023]`, `[Smith et al., 2023]`, `[Smith and Jones, 2023]`,
  year suffixes (`2023a`), and deduplicates repeated citations.
  Returns `{score, total_citations, resolved, unresolved}`.
- **Completeness**. Single batched LLM-as-judge
  call — the judge sees the whole report plus the full topic list and
  returns per-topic `covered` decisions with short reasons. Strict
  prompt: name-dropping does not count. Aggregator defensively handles
  missing / extra / malformed judge output. See ADR
  [0006](decisions/0006-completeness-batched-judge.md) for the
  batched-vs-per-topic tradeoff.
- **Faithfulness**. Single LLM-as-judge call
  extracts each factual, cited claim from the report and decides
  `supported: true|false|null` against the cited paper's abstract.
  Source of truth is `state["papers"]` abstracts joined with
  `state["citations"]` on `paper_id`. Score = supported / (supported +
  unsupported); `source_unavailable` claims are reported separately.
  Defensive override: if the judge claims support against a cite key
  we didn't provide, we force `supported=None`. See ADR
  [0007](decisions/0007-faithfulness-single-call-abstracts.md) for
  source-of-truth and denominator tradeoffs.
- **Retrieval recall**. LLM-as-judge over the retrieved paper set
  against `expected_topics` — did search actually fetch material for
  each expected topic, independent of what the report did with it
  (ADR 0013).

**Which model judges.** `EVAL_JUDGE_MODEL`
(`settings.eval_judge_model`, default `claude-sonnet-4-6`), passed
explicitly at every judge call site. Nothing inherits.

This changed in ADR
[0070](decisions/0070-eval-integrity-provenance.md), and the old
behaviour is worth naming because it was a live defect: the three judges
called `call_llm_json` with no `model_name`, `src/llm.py` fell through
to `settings.anthropic_model`, and **upgrading the product model
silently changed the judge**. The system graded itself with a moving
ruler and no output said so.

`eval_judge_model` is deliberately *not* shaped like the per-agent
routing knobs of ADR 0021 (`READER_MODEL`, `CRITIC_MODEL`, …). Those
default to `""` meaning "inherit `ANTHROPIC_MODEL`"; this one rejects
the empty string at settings load, because inheritance is the thing
being removed. It is still picked up by `resolved_model_ids()`, so an
off-table judge model is detected and priced like any other routed id —
judge spend is metered separately from workflow spend (below), and an
unpriced judge would under-report it.

**Changing `EVAL_JUDGE_MODEL` invalidates every existing baseline.** A
regression diff across a judge swap compares two different instruments,
and its verdict means nothing. The provenance block records the value,
so the swap is visible in the data rather than only in somebody's
memory.

### `src/eval/groundedness.py`

**Landed (WO-A16, ADR
[0074](decisions/0074-deterministic-groundedness.md)).** Deterministic
groundedness with **no model call**: cited arXiv identifiers resolved
against the papers the run actually retrieved, and quoted spans located
verbatim in the cited paper's text under a normalization that is stated
and tested rule by rule. Every metric publishes its denominator, and a
zero denominator is `null` with a reason code rather than a score. Full
treatment in [Deterministic groundedness (no
judge)](#deterministic-groundedness-no-judge); it is not yet wired into
the campaign.

### `src/eval/runner.py`

**Landed.** Sequential batch runner with per-query error isolation
(see ADR [0008](decisions/0008-eval-runner-sequential-per-query-isolation.md),
hardened by ADR [0050](decisions/0050-eval-runner-hardening.md)).
Fresh workflow per query for state-leak isolation, and its checkpointer
is closed after every query. Writes three output layers:

```
outputs/eval/<run_id>/
    queries/<query_id>.json  — full record: state + metrics + timing + err
    summary.jsonl            — one line per query (for dashboards / CI)
    summary.md               — human-readable table + aggregates
```

Run identifier: `YYYYMMDDTHHMMSSZ` UTC timestamp.

`queries/*.json` is the durable layer: it is written the moment a query
finishes, and both summary files are derived from it at the end of the
run. `summary.jsonl` also gets its line appended and flushed per query,
so it stays useful mid-campaign; the end-of-run rebuild is what
collapses the duplicate lines a resumed run appends.

### Isolation, crash-safety and interrupts

- **A judge failure costs one metric, not the batch.** Each of the four
  metrics is scored inside its own guard. A judge that times out, 429s
  past its retries or truncates into invalid JSON leaves that metric as
  `null`, records the reason in `metrics_error`, and keeps the run's
  state, spend and timing — the workflow output is what cost money.
  Neither the query nor the campaign fails on it, so both consumers of
  `summary.jsonl` state the denominator they actually averaged over
  (below) and the runner's closing line counts the affected queries.
- **A kill loses at most the in-flight query.** Everything finished is
  already on disk.
- **`Ctrl-C` and SIGTERM take the same path.** `kill`, `docker stop`
  and an Actions cancellation flush partial results, the in-flight
  query's record included, before exiting `130`.
- **`--resume` re-enters a campaign** without re-paying: queries whose
  `queries/<id>.json` exists are skipped and folded into the final
  summary. That includes *errored* queries — to retry one, delete its
  record file first.
- **A populated `--output-dir` is refused** unless `--resume` is
  passed, so a repair run cannot overwrite a previous campaign's
  records.

### Cost accounting: product vs harness

Since ADR 0050 the summary separates the agent's spend from the eval
rig's:

| Field | Covers |
|---|---|
| `cost_usd`, `llm_calls`, `elapsed_sec` | the workflow run |
| `judge_cost_usd`, `judge_llm_calls`, `scoring_sec` | the scoring judges |
| `total_cost_usd` | both — what the benchmark query cost to run |

The README block and the regression gate's `cost_usd` band both read
the *workflow* figures, so neither is polluted by judge noise.
Summaries written before ADR 0050 folded judge spend into `cost_usd`
and read a few percent high; they are not comparable on cost with newer
ones.

## Running an eval

```bash
make eval                                          # full benchmark
make eval QUERIES=hallucination-mitigation,rag-multi-hop
python -m src.eval.runner --output-dir custom/dir  # bypass Makefile
python -m src.eval.runner --output-dir custom/dir --resume
python -m src.eval.runner --max-budget-usd 25      # campaign ceiling
python -m src.eval.runner --help                   # full CLI reference
```

Requires `ANTHROPIC_API_KEY` in `.env` — the runner refuses to start
without it.

`--max-budget-usd` is checked *between* queries against accumulated
workflow+judge spend (including spend reused from a resumed campaign),
so the final query can overshoot the ceiling by its own cost. It is a
campaign ceiling, and the only one the eval path owns — the per-call
dollar cap is ADR 0051's, at `call_llm`.

### Campaign run-book

For a paid multi-query campaign (as opposed to a one-query smoke):

```bash
API_JOB_TIMEOUT_SEC=3600 \
python -m src.eval.runner \
  --output-dir outputs/eval/campaign-<name> \
  --max-budget-usd 25
# interrupted or partially failed? same command + --resume
```

- **`API_JOB_TIMEOUT_SEC=3600` restores retry headroom.** The LLM
  client clamps its retry envelope so one call chain fits inside 75%
  of `api_job_timeout_sec` (`src/llm.py::_retry_envelope`, ADR 0051)
  — and the clamp applies on the eval path too, even though no API
  job exists there. At the defaults (600s timeout, 120s per attempt)
  only 3 attempts fit, so the configured `anthropic_max_retries=4`
  is cut to 2 (the client warns once:
  `llm_retry_budget_clamped`). Raising the env var to 3600 lets all
  4 retries through — worth it on a long campaign where a transient
  529 otherwise costs a whole query record.
- **Name the output dir** so `--resume` has a stable target; the
  runner refuses a populated dir without `--resume`, and `--resume`
  skips every query whose `queries/<id>.json` already exists
  (delete a record file to retry that query).
- **`--max-budget-usd`** stops the campaign between queries at the
  ceiling (exit 5) with everything already scored safely on disk.
- **Watch the exit code** (table below) — a `0` means every attempted
  query succeeded; `3` means the campaign completed but the summary
  contains errored queries.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | every attempted query succeeded |
| 1 | configuration error (no `ANTHROPIC_API_KEY`) |
| 2 | usage error (non-empty output directory without `--resume`) |
| 3 | completed, but at least one query errored |
| 4 | every attempted query errored |
| 5 | stopped early on the `--max-budget-usd` ceiling |
| 130 | interrupted (Ctrl-C / SIGTERM); partial results are on disk |

Precedence is "why is the campaign incomplete" before "how did the
queries go": an interrupted or budget-stopped run reports as such even
when the queries it did run all passed.

## Run provenance

*ADR [0070](decisions/0070-eval-integrity-provenance.md).* A score is
only worth a confidence interval if it is attributable. Before this,
no row in either lane recorded which model judged it, which rubric text
produced the verdict, or which commit ran the harness — so a red
nightly could not tell "the product got worse" from "somebody upgraded
the model", "somebody tightened a prompt" or "somebody added a
benchmark query".

Every record and every summary row of **both** lanes now carries one
nested `provenance` block:

| Field | What it answers |
|---|---|
| `harness_version` | which row schema this is |
| `judge_model` | what graded it |
| `product_model` | what was graded |
| `rubric_versions` | `{name: version}`, for the rubrics this campaign ran |
| `code_commit` | which checkout produced it |
| `code_dirty` | `true` / `false` / `null` when nobody could check |
| `dataset_version` | which benchmark, at which contents |
| `tier` | `research`, or the learning lane's `scripted` / `funded` |
| `seed` | the harness seed applied |
| `mock_mode` | whether the run was against the built-in mock papers |
| `captured_at` | when |

Three properties are worth knowing about how it is written.

**It is captured when the record is created, not when the summary is
rendered.** `rebuild_summaries` re-derives `summary.jsonl` from the
durable per-record JSON, possibly days later on a `--resume`; a block
captured then would describe the rebuild rather than the run that
produced the score.

**A row that cannot say what produced it fails the gate.** A record
written before ADR 0070 arrives with an empty block, and
`scripted_tier_check` reports it. That is the correct answer rather than
an inconvenience — such a row cannot participate in a comparison — but
it does mean a campaign started before this change must be re-run rather
than resumed.

**A mixed campaign announces itself.** Both lanes' `summary.md` render
the block and print `⚠ MIXED` when the rows disagree on any field. A
`--resume` can re-enter a campaign under a different judge model or a
different commit, and a summary that quoted only the first row would
present two instruments as one measurement.

`code_commit` is resolved from `git rev-parse HEAD` when git is
available, then `GITHUB_SHA`, then the literal `"unknown"`. `code_dirty`
is `null` rather than `false` on the fallback paths, because "nobody
checked" and "checked and clean" are different claims about a result's
reproducibility.

### What the seed does not buy

`EVAL_SEED` (`settings.eval_seed`, default `0`) is applied at the start
of both campaigns and recorded on every row. It pins `random` and numpy
— the generators anything under `src/` draws from.

It does **not** make a campaign reproducible. The Anthropic Messages API
exposes no sampling seed, and the judges are sampled at temperature 0.3.
Recording the seed says what was pinned; it is not a claim of
determinism, and it must not be read as one.

### Rubric versions

Every judge prompt carries a version constant beside it —
`COMPLETENESS_RUBRIC_VERSION`, `FAITHFULNESS_RUBRIC_VERSION`,
`RETRIEVAL_RECALL_RUBRIC_VERSION` in `metrics.py`, and
`PLAN_RUBRIC_VERSION`, `EXPLAIN_BACK_RUBRIC_VERSION`,
`SHAME_FREE_COPY_RUBRIC_VERSION` in `learning_metrics.py`. Bumping a
version is the act that declares "scores from before and after this edit
are not comparable".

The version is not on the honour system. `tests/fixtures/eval/rubric_lock.json`
records each rubric's shipped history as `(version, sha256-of-prompt)`
entries, and `tests/test_eval_rubric_versions.py` asserts that the live
text matches the newest locked entry, that the live version matches it,
and that no rubric's history reuses a version or a digest. The only way
to change a prompt is therefore to append an entry under a version that
has never been used.

To change a judge prompt:

1. Edit the prompt.
2. Bump its `*_RUBRIC_VERSION` constant.
3. Append `{"version": "<new>", "sha256": "<new digest>"}` to that
   rubric's list in the lock file. The failing test prints the digest.

The bound, stated plainly: a determined edit can overwrite the last lock
entry in place instead of appending. That is the limit of any
checked-in baseline — it defends against forgetting, not against intent
— and the overwrite reads as an overwrite in the diff.

`citation_accuracy` has no rubric and gets no version: it is regex and
set membership. A version constant on a deterministic metric would be
provenance theatre.

### Judge–human calibration remains unmeasured

Provenance says *which* instrument produced a number. It says nothing
about whether that instrument is any good, and this repository has never
measured it: **judge–human agreement is unmeasured on all four research
metrics**, and it is deferred rather than planned, because it needs
labelled human verdicts nobody has produced.

When it is measured, the reporting form is not negotiable:

- Report **φ / MCC with both positive rates** — the judge's and the
  human's. For binary verdicts Pearson, Spearman, Kendall, φ and MCC are
  the same statistic, and κ = q·φ is not interpretable without the
  positive rates.
- **Never quote raw agreement.** It overstates chance-corrected
  agreement by 33–41 percentage points: in a 21-judge study, 85% exact
  match corresponded to a κ of about 0.48.
- **State how abstentions were counted.** The choice swings measured
  accuracy by 10–34 points on identical verdicts.

Two related notes, so effort lands in the right place. **Verbosity bias
has collapsed** (below 0.011 across all 21 judges measured); the
2023-era "judges love long answers" folk model is out of date and this
harness builds no machinery for it. **Position bias has not** collapsed
and is worth controlling by swap/AB+BA averaging — but none of these
judges runs a pairwise comparison, so there is no position to swap
today. If a pairwise judge is ever added, that control comes with it.

## Deterministic groundedness (no judge)

`src/eval/groundedness.py`. The domain hands this repository a signal
most systems cannot have: because the corpus is arXiv papers, two of the
most valuable accuracy checks are **decidable without a model call** —
does every cited identifier resolve, and does every quoted span appear
verbatim in the paper's text. ADR
[0074](decisions/0074-deterministic-groundedness.md) is the decision;
`03-ARCHITECTURE.md` §4.4 is where it sits in the architecture.

Zero spend, offline, no I/O of any kind. Nothing in the module imports
`src.llm`, `requests` or `socket`, and
`tests/test_groundedness.py::TestNoJudgeNoNetwork` asserts that
structurally rather than trusting the harness to catch it.

### Identifiers resolve against the run's own corpus

**Not against arxiv.org.** The harness blocks non-loopback sockets, but
the design reason is the stronger one: a citation to a real paper *the
run never fetched* is still a fabricated citation, and that is the
interesting failure. The oracle is `state["papers"]`.

Three outcomes, kept distinct because they have different owners:

| reason | meaning |
|---|---|
| `citation_resolved` | well-formed, and this run retrieved it |
| `citation_not_retrieved` | well-formed, and this run never fetched it |
| `citation_malformed` | not a well-formed arXiv identifier |

Both surfaces are checked: identifiers in the report body (`arXiv:…` or
an `arxiv.org` URL — a bare number in prose is deliberately *not*
extracted) and the identifier each `state["citations"]` entry asserts.
The second is the one `citation_accuracy` cannot see, because it matches
`[Author, Year]` tags against the same list that wrote them.

Canonical form is `arxiv:<id>`, matching `learning_benchmark.py`.
Version suffixes are stripped (a citation to v2 of a paper fetched at v1
is not a fabrication), old-style ids are case-folded, and Semantic
Scholar papers keep their `s2:` identity so a citation to one resolves.

### What quote normalization does, and what it does not

Three match levels, and **which one matched is recorded on every quote**:

| level | rule |
|---|---|
| `exact` | raw substring, no transformation |
| `folded` | format chars stripped → NFKC → line-break de-hyphenation → quote/dash folding → whitespace collapse → case-fold |
| `skeleton` | `folded`, then everything that is not a letter or digit removed |

`folded`, in order, each rule with its own test:

1. Unicode `Cf` format characters and U+00AD soft hyphen removed — PDF
   extraction emits zero-width spaces, joiners and soft hyphens nobody
   typed.
2. NFKC — folds the ligatures a TeX-set PDF extracts as single code
   points (`ﬁ` U+FB01, `ﬂ`, `ﬀ`), full-width forms, and `…` to `...`.
3. A hyphen at a line break followed by a **lower-case** letter is
   joined: `inter-\nnational` → `international`.
4. Curly quotes, angle quotes and primes fold to ASCII `'` and `"`.
5. The six dash code points and U+2212 fold to `-`.
6. Every whitespace run (NBSP, thin space, form feed) collapses to one
   space.
7. Case is folded.

**Nothing else.** No stemming, no stopword removal, no abbreviation
expansion, and no edit-distance or fuzzy matching anywhere. One changed
word, one changed number or a reordered clause fails at every level, and
`TestWhatIsNotNormalized` holds that edge — the entire value of a
verbatim check is that a near miss is a miss.

Rule 3 is knowingly incomplete and says so: it also turns
`state-\nof-the-art` into `stateof-the-art`, which is wrong. No
dictionary-free rule can separate a broken word from a compound at a
line break, so `skeleton` removes hyphens outright and subsumes the
case. A cheap rule plus a fallback that covers its failure beats a rule
claiming a distinction it cannot make.

Elided quotations (`"… ... …"`) are split on the ellipsis and their
fragments matched **in order**, so fragments appearing in the wrong order
are correctly not found. A fragment under three words is evidence-free
and the quote is reported undecidable instead of scored.

Quoted spans below `min_quote_words` (6, published on every result) are
not treated as quotations at all: `the "attention" mechanism` is
terminology, and checking it against a paper would measure the report's
punctuation habits. Markdown blockquotes are not treated as quotations
either — in this repository's reports a `>` block is as often the model's
own summary as a citation of source text.

### Source completeness gates the denominator

A quote can only be *falsified* against a complete source. Given only an
abstract, "not found" means "not in the abstract" and is evidence of
nothing.

- `full` — parsed document text. A miss is a real miss.
- `partial` — ranked evidence chunks (ADR 0016) or the abstract. A hit
  still proves the quotation; a miss is `quote_source_incomplete` and
  leaves the denominator instead of failing.

`source_coverage` is published beside the rate, and every metric carries
an `excluded` count, so the exclusion rule cannot quietly empty the
metric. Sources are held as `segments` and never matched across two of
them: the evidence chunks are non-contiguous, and whitespace collapses at
`folded` and vanishes at `skeleton`, so no separator survives to keep two
excerpts apart.

One more verdict falls out of this: when the attributed paper's source is
`full`, the quote is absent from it, and it *is* present verbatim in
another paper's `full` source, the outcome is `quote_misattributed` — a
specific defect no judge names reliably.

### Metrics that cannot report a score they did not earn

`citation_resolution_rate`, `quote_verbatim_rate` and
`unsupported_claim_count` share one envelope:

```json
{"name": "...", "value": 0.8, "numerator": 4, "denominator": 5,
 "excluded": 1, "reason": null}
```

**`value` is `null` exactly when `denominator` is 0**, with a reason
code — never a score. This is the defect being fixed: `citation_accuracy`
returns `1.0` for a report with zero citations, awarding a perfect score
to the exact failure it exists to catch.

| reason | meaning |
|---|---|
| `no_citations` | the report and its citation list assert no identifier |
| `no_quotes` | the report quotes nothing |
| `no_checkable_quotes` | it quotes, and no complete source was available |
| `no_checkable_claims` | nothing at all could be decided |

`no_quotes` and `no_checkable_quotes` are separate because "quoted
nothing" and "we had no PDF text" are different facts about a run, and
collapsing them would hide an empty cache behind a clean-looking metric.
`unsupported_claim_count` obeys the same rule though it is a count: zero
problems found in zero claims checked is *nothing measured*, not nothing
wrong.

### The per-claim outcome, and who consumes it

Every claim yields `{claim_id, kind, subject, locator, grounded, reason,
detail}`, where `grounded` is `true`, `false`, or `null` for undecidable.
`claim_id` is `<kind>:<sha256(subject)[:16]>` — content-derived, so the
same claim carries the same id across arms and across runs, and moving a
sentence does not move the id. `paired_outcomes()` projects a result to
`{claim_id: bool}`, dropping undecided claims rather than defaulting
them, which is the shape a paired (McNemar) comparison consumes.

The module deliberately does not decide whether a claim id present in one
arm and absent from the other is discordant or out of scope; that is a
statistical judgement and belongs with the paired-comparison code. This
side's only contract is that the ids are stable.

Results carry a `check` block (`check_version` + a digest of the
normalization spec) — ADR 0070's rubric-versioning mechanism applied to a
check that has no prompt — and the caller's `RunProvenance` block under
the same key every other eval row uses.

### What calibration found

The trap in a check like this is that too strict a matcher measures the
PDF parser rather than the agent. Four things were measured before the
constants were fixed:

1. **This repository's own e2e fixture cites a paper the run never
   retrieved, and today's metric scores it 1.0.**
   `tests/fixtures/e2e/research_llm_responses.json` cites
   `arxiv:2311.05232`; under mock mode the retrieved corpus is
   `search.MOCK_PAPERS`, whose survey paper is `2311.09000`.
   `measure_citation_accuracy` returns `1.0`;
   `citation_resolution_rate` returns `0.0` over a denominator of 1 with
   reason `citation_not_retrieved`.
2. **No recorded fixture in the repository contains a multi-word quoted
   span.** Across all 30 JSON fixture files (1,143 strings) there are 17
   quoted spans, every one a single word from a JSON key listing. So on
   today's recorded corpus `quote_verbatim_rate` is `null` with reason
   `no_quotes` — the right answer, and exactly what `citation_accuracy`
   gets wrong. The quote path is calibrated against
   `tests/fixtures/groundedness/run.json`, which is hand-authored and
   says so in its own `_readme`.
3. **Without normalization the check would measure the extractor.**
   `fitz.Page.get_text()` returns a hard newline at every rendered line
   break. In an offline PyMuPDF round-trip probe, three of four
   quotations that genuinely appear in the source matched only at
   `folded` or `skeleton`, and **none** matched as a raw substring. A
   check without `folded` would report a hallucination rate near 100% on
   true quotations. `exact_quote_count` is therefore reported beside the
   rate rather than being the rate.
4. **The six-word floor is doing real work.** Below it, quoted spans are
   terminology and scare quotes, and including them would put the
   report's punctuation habits into the denominator.

A fifth result settled a question rather than a constant: PyMuPDF's
base-14 fonts do not reproduce arXiv's extraction artefacts (non-Latin-1
glyphs come back as `?`), so no test ships a generated PDF. The
artefacts are planted in the fixture text directly and listed in its
`_readme`.

### Not yet wired into the campaign

Nothing calls `measure_groundedness` from `runner.py` yet, and
`citation_accuracy` is still the metric the gate reads. Both are
follow-ups with named owners in ADR 0074: replacing `citation_accuracy`
at its call sites belongs to whoever holds `src/eval/metrics.py`, and
feeding parsed PDF text plus the paired outcomes into the campaign
belongs to the work order holding `runner.py` and `stats.py`.

## Regression gate

`src/eval/regression_diff.py` diffs two `summary.jsonl` runs and exits
non-zero on regression — the nightly workflow
(`.github/workflows/eval-nightly.yml`) turns that into a red run.

Since WO-W11 the differ carries **two lanes**, because the research
runner and the learner simulator write different summaries:

| `--lane` | Reads | Keyed by | Nightly job |
|---|---|---|---|
| `research` (default) | `src/eval/runner.py` | `query_id` | `eval` |
| `learning` | `src/eval/simulate_learner.py` | `record_id` | `learning-eval` |

A `MetricLane` holds one campaign's id field, metric set, thresholds
and report vocabulary; the diff logic itself is single-copy. The
research lane is assembled from the same module constants it always
used, its CLI call is unchanged, and its rendered report is byte-for-byte
what it was — the learning lane is additive, not a rewrite. Feeding a
research summary to `--lane learning` fails loudly on the missing
`record_id` rather than producing an empty, green-looking diff.

Metrics are judged by class (ADR
[0044](decisions/0044-eval-cost-accuracy-and-regression-thresholds.md),
revisiting ADR [0010](decisions/0010-nightly-eval-ci.md)'s single
global threshold):

| Metric class | Metrics | Regression rule |
|---|---|---|
| Score (0-1 judge outputs) | `citation_accuracy`, `completeness`, `faithfulness`, `retrieval_recall`, `critic_score` | absolute drop > `--threshold` (default 0.10) |
| Resource (counts / dollars) | `iterations`, `llm_calls`, `cost_usd` | rise > per-metric absolute floor **and** > per-metric relative band (`RESOURCE_THRESHOLDS`) |

Both classes are direction-aware: a score rising or a cost falling
past the same bounds is an *improvement*, never a regression. The
resource bands are floor `+1` / `+50%` for `iterations`, `+4` /
`+25%` for `llm_calls`, and `+$0.10` / `+25%` for `cost_usd` — sized
so one extra critic revision, one extra rankable paper, or a $0.02
cost wiggle can never fail the nightly on its own.

### The learning lane's fields

Three classes, same ADR 0044 system, different metrics:

| Class | Fields | Rule |
|---|---|---|
| Rubric scores | `shame_free_score`, `plan_coherence` | absolute drop > `--threshold` (default 0.10) |
| Deterministic outcome rates | `shame_free`, `downscope_honest`, `progress_events_evidence_linked`, `injection_contained` | same threshold leg; these are per-session booleans, so a flip is a delta of 1.0 and clears any epsilon |
| Resource | `expectation_failures`, `llm_calls`, `cost_usd` | rise > absolute floor **and** > relative band |

The outcome rates are booleans read as 1.0/0.0, which makes their
aggregate the campaign's *rate* for that outcome — the fraction of
sessions that stayed shame-free, contained the injection, and so on.
They sit on the threshold leg deliberately: they are observed rather
than judged, and one session that stopped containing an injection is a
regression at any epsilon.

The resource bands are `+0` / `+0%` for `expectation_failures` (zero
tolerance: a WO-W08 structural expectation that stopped being met is a
regression at +1), `+2` / `+25%` for `llm_calls`, and `+$0.05` / `+25%`
for `cost_usd`. The cost floor is half the research lane's because a
session costs a fraction of a research run — at `01` §6.1's $0.07–0.17
estimate, a $0.10 floor is most of a whole session and a 50% cost rise
could never fire.

**Harness spend is tabulated, never gated.** `learner_cost_usd`,
`judge_cost_usd` and `total_cost_usd` appear in the aggregate table
marked *(not gated)*. ADR 0050's rule is that the gate reads the
product; a judge that got more expensive is not a product regression.
Only `cost_usd` may ever be quoted as what a guided read costs.

The learning report also prints a **cost-per-session row against the
plan's estimate** — the measured baseline and current means beside
`01` §6.1's $0.07–0.17, labelled *not a measurement* in the row itself.
Gate W2's cost question is answered by eval plumbing rather than an
ad-hoc script, and the plan's prior is not allowed to quietly become
data by sitting in a results table. `simulate_learner`'s own
`summary.md` carries the same row.

A **query present in the baseline but missing from the current run** is
also a regression (ADR 0050). The usual cause is a truncated batch, and
the aggregate row re-averages over whatever survived — so "no
regressions" on a shrunken denominator is the most dangerous kind of
green. The report states the denominator it used
(`over the 15 of 20 baseline queries present in both runs`), and
`--allow-removed` opts a deliberate `--queries` subset run out of the
gate without excusing real regressions in the queries it did run.

A **metric the current run stopped scoring** is the same shrunken
denominator one level down: a failed judge leaves the metric `null`, so
its delta is `None`, so the query reads `unchanged`. The gate stays
green on purpose — a flaky judge is a harness fault, not a product
regression — but the report never hides it. Each aggregate row carries
a `Compared` column (`faithfulness … | 2 / 20`), and a metric the
baseline scored while the current run did not gets named in the header.

### The statistics, honestly

The gate compares **two single runs** of a nondeterministic system
(live arXiv results, sampling temperature, a critic that decides
whether to ask for revisions). What that means in practice:

- **Quantization dominates the score epsilon for ratio metrics.**
  `completeness` and `retrieval_recall` move in steps of
  `1/len(expected_topics)` — typically 0.20-0.25 per query. The 0.10
  epsilon therefore filters *nothing* for those two: a single
  borderline topic decision flipping registers as a full step and
  fires the per-query gate. `citation_accuracy` and `faithfulness`
  have finer denominators (citations / claims), where 0.10 is a real
  noise filter.
- **The thresholds are priors, not measured spread.** Nothing in
  `src/eval` computes run-to-run variance today (no stdev, no
  confidence intervals). The bands come from reasoning about the
  mechanics (what one critic revision costs in calls and dollars),
  not from data.
- **What we can detect:** sustained quality collapses (a metric
  dropping ≥ 2 quantization steps, or across several queries), call
  or iteration runaway (loop bugs), and cost creep above 25%.
- **What we cannot detect:** single-query, single-step ratio-metric
  drops are indistinguishable from judge noise; slow drift below the
  bands accumulates silently (ADR 0010 already documents the
  gradual-drift blind spot — each nightly rebaselines on the previous
  night).
- **The fix, when we invest in it:** run the benchmark 3+ times
  against an unchanged `main`, compute per-metric spread, and set the
  thresholds at ~3x the observed noise. Until a 3-repeat baseline
  exists, treat a red nightly on exactly one query and one metric
  with suspicion and read the per-query table before reverting
  anything.

## Guided-read learning metrics (Phase W)

`src/eval/learning_metrics.py` adds the first evaluation layer for guided
paper-reading sessions. It is separate from the research-query runner because
its unit is a learner session rather than a research report, but it follows the
same failure discipline: a judge exception or malformed JSON returns
`metric=null` plus a named `metrics_error`. Invalid output never becomes a
default or partial score.

Three single-call judges are defined:

- **Session-plan coherence** compares the plan with the scenario's declared
  minutes and the paper's close-read/skim guidance. It scores section ordering,
  load against the time budget, comprehension-check placement, and whether a
  shortened session says plainly what was deferred. The paired 10-minute
  fixtures prove the harness can distinguish an honest one-section plan from a
  silent 30-minute plan; all unit-test judge responses are canned.
- **Explain-back gaps** accepts only gaps whose evidence quote appears verbatim
  in the learner's explain-back. It cannot cite tutor copy or invent a mastery
  claim. Its checked-in calibration set contains 20 compact synthetic cases and
  a deterministic exact-set/micro-F1 scorer.
- **Shame-free copy** (added by WO-W10) scores learner-facing tutor and
  check-in copy on three criteria — respects effort, avoids deficit framing,
  offers a next step — and may only report an offending quote that appears
  verbatim in the copy it was given. It is the rubric half of the shame-free
  outcome; `find_shaming_language` below is the deterministic half, and the
  simulation benchmark runs both. Praise that still frames the learner as
  deficient is a failure, not a pass.

The calibration provenance is intentionally limiting, not decorative. The set
was authored as a Codex-assisted implementation fixture on 2026-09-01; it is
not composed of real learner sessions, has not been ratified by the repository
owner/operator, and has not been scored by a live judge. It tests data flow and
agreement arithmetic. It is **not** evidence that the assessment judge agrees
with humans, cannot clear Gate W1, and cannot authorize assessed learner-profile
claims. Owner review and the funded campaign remain W-OD-1.

Two zero-call checks run in ordinary pytest: every progress event must carry a
non-blank `evidence_ref`, and tutor/check-in copy is scanned against the small
forbidden shame lexicon (for example, "you've fallen behind" and "you failed").
The functions report every offending index/phrase so CI failures are actionable.

### Paid calibration remains locked

The production calibration step is deliberately absent from automated CI. It
requires renewed owner approval, a ratified label set, and a campaign run under
`--max-budget-usd`. Until its agreement bar is chosen and met, explain-back
outputs are tutor guidance only. The disabled nightly research eval is not a
substitute for this campaign and remains disabled independently.

## The learner-simulation benchmark (Phase W)

`src/eval/simulate_learner.py` is the regression harness for the guided
read. Where `learning_metrics.py` scores fixed artifacts, this module
*produces* them: it replays a WO-W08 `LearningScenario`'s scripted turns
against WO-W03's compiled session graph, one session per record, and
scores what came back.

What it is for, stated before what it does, because the order matters:
**regression detection, not outcome proof.** A simulated learner is not
a learner ([`01` §7.4](../planning/07-learning-platform/01-LEARNING-AGENT.md#7-eval-story)).
These are process metrics. Their value is that a prompt change which
makes check-in copy shaming, or plans quietly dishonest, fails here
before a pilot learner ever sees it.

### The two tiers

| | Scripted (default) | Funded |
|---|---|---|
| Who plays the learner | the scenario's `turns` | a cheap model |
| What the graph runs | mock mode | real models |
| Cost | **zero** | see below |
| Rubric judges | not run | run |
| Where it runs | any machine, CI | an owner-approved campaign |

The scripted tier is the one that runs today:

```bash
make simulate-learner
# or, explicitly:
USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled \
ENABLE_CHECKPOINTING=true \
  python -m src.eval.simulate_learner
```

`make simulate-learner SCENARIOS=engineer-transformer-time-poor` filters;
`ARGS='--repeats 3'` passes anything else through.

The two tiers refuse to be confused for each other, in both directions.
`--tier funded` without `--max-budget-usd` will not start — an uncapped
paid campaign is not a thing this runner does. `--tier funded` with
`USE_MOCK_DATA=true` is refused because it would bill nothing and measure
nothing. And `--tier scripted` with `USE_MOCK_DATA=false` is refused
because that tier advertises zero spend and would otherwise quietly
charge for it. All three are `EXIT_CONFIG`.

### Judged outcomes

Scoped to what Phase W actually builds, per
[`01` §7.2](../planning/07-learning-platform/01-LEARNING-AGENT.md#7-eval-story).
Four outcomes; two have a deterministic half that runs in every tier,
and the rubric judges only run when the campaign is paying.

- **Shame-free copy.** WO-W09's `find_shaming_language` scans every
  learner-facing line — the plan's language, each tutor turn, the session
  summary — for the forbidden lexicon. The learner's *own* words are
  excluded on purpose: an adversarial script plants shaming text
  deliberately, and failing the product for an attack it contained would
  invert the measurement. The rubric judge
  (`measure_shame_free_copy`) scores the framing the lexicon cannot
  enumerate, and may only quote text that appears verbatim in the copy —
  the same evidence rule the explain-back judge enforces.
- **Honest scope adjustment.** Deterministic: a scenario declaring less
  time than its persona's standing budget must produce a plan that says
  it was cut down and fits `max_plan_sections`. Graded:
  `measure_session_plan_coherence`'s `downscope_honesty` criterion, fed
  the live plan rather than a fixture.
- **Evidence-linked progress events.** Deterministic, every tier: every
  event must carry a non-blank `evidence_ref`.
- **Assessment honesty.** Deterministic, every tier. The adversarial
  scenarios' planted probe must not reach any control field — the plan,
  an assessment status, an event kind, an `evidence_ref`, an inference
  batch entry. Evidence fields are excluded by construction: ADR 0020's
  property is that learner text never becomes an instruction, not that it
  disappears. Separately, an assessment must never carry a `score`,
  `grade`, `mastery` or `level` key, and with the WO-W04 judge off the
  honest record is `recorded_ungraded` (ADR 0060) — never an outcome the
  system did not earn.

### Campaign discipline, inherited

`--resume`, `--max-budget-usd`, per-metric judge isolation, per-scenario
durable records and the exit codes are `runner.py`'s, reached through
`runner.CampaignShape` rather than copied. The research campaign's
behaviour is unchanged: the shape defaults to `RESEARCH_CAMPAIGN` and
`tests/test_eval_runner.py` is untouched. Records land in
`scenarios/<scenario-id>.rN.json` — one file per scenario *per repeat* —
so a kill loses at most the in-flight session and `--resume` re-enters
without re-paying.

### Cost accounting: three payers, not two

ADR 0050 split the product's spend from the harness's. This campaign's
harness has two halves, so `summary.jsonl` carries three columns:

| Field | Who spent it | Side |
|---|---|---|
| `cost_usd` / `llm_calls` | the session graph | **product** |
| `learner_cost_usd` / `learner_llm_calls` | the model playing the learner | harness |
| `judge_cost_usd` / `judge_llm_calls` | the rubric judges | harness |
| `total_cost_usd` | the sum — what the session cost to run | — |

All three count toward `--max-budget-usd`: it is money whichever side of
the product boundary it sits on. Only `cost_usd` may ever be quoted as
what the guided read costs a learner.

### The three-repeat rule

`--repeats N` runs each scenario N times. Below three, the runner prints
a warning naming
[`planning/05-agentic-upgrade-plan.md`](../planning/05-agentic-upgrade-plan.md)'s
"Judge noise mandates repeat runs" and saying plainly that single-run
differences are noise. It warns rather than refuses: one repeat is a
perfectly good smoke run, and it is only a *comparison against a
baseline* that needs three.

### The one recorded divergence, resolved

WO-W10 shipped with a single pinned divergence:
`engineer-rlhf-profile-note-injection` expected at most one plan
section, while `check_in` allocates two for its declared 15 minutes
(`_fallback_plan`: ≤10 min → 1 section, ≤20 min → 2, else 3). WO-W11
resolved it in favour of the **graph's rule**, because nothing about
that scenario is time-poor: its script is an injection through the
profile note, it sets `requires_downscope_statement: false`, and the two
other 15-minute scenarios both expect two sections. The `1` read as a
copy from the 10-minute time-poor scenarios, so the *expectation* moved
to 2 and no graph behaviour changed.

`test_unmet_expectations_are_exactly_the_recorded_baseline` still pins
the set exactly — it now asserts the set is empty, so a *new* divergence
still fails CI rather than being averaged away — and a companion test
pins the general rule: a scenario declaring 15 minutes may not expect
fewer than two plan sections.

### Simulation policy, and its limits

A scenario script is 2–4 turns; the graph always offers four learner
inputs before it asks for the explain-back. Two rules close that gap, and
both are limitations rather than details:

- A closing `explain_back` turn is **held back** until the graph actually
  asks for the explain-back, so the script's last word lands where the
  scenario meant it to.
- When the tutor asks more questions than the script anticipated, the
  scripted tier answers with a fixed, content-free line and counts those
  turns in the record's `filler_replies`. The funded tier asks the cheap
  model instead. Scripted text always wins when the script has a turn for
  the pause — an adversarial probe has to arrive verbatim or the
  containment check measures nothing.

### The first funded campaign is deferred — W-OD-1

**No funded simulation campaign has been run, and this PR does not run
one.** Acceptance criterion 5 of WO-W10 is deferred behind the **W-OD-1**
funding decision, exactly as WO-W09's paid calibration run is. What is
built and merged is the harness and its scripted tier; what is not is the
campaign that would put numbers in it.

Sized on the card when it is funded: the full scenario set is ≈15
sessions at
[`01` §6.1](../planning/07-learning-platform/01-LEARNING-AGENT.md)'s
per-session estimates plus judge and simulated-learner costs — roughly
**$2–6**, with a **$15** ceiling proposed as a judgment call. Its results
enter the Gate W1 pack **as priors**, not as a measurement, for the same
reason every other threshold in this document does: nothing here has ever
had a funded green campaign.

## The per-PR scripted tier

Every PR runs the scripted simulation as a **campaign**, not only as a
unit test, in `ci.yml`'s Python job (step: *Scripted learner simulation
(zero spend)*):

```bash
USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled \
ENABLE_CHECKPOINTING=true \
  python -m src.eval.simulate_learner --output-dir outputs/eval/ci-scripted-tier
python -m src.eval.scripted_tier_check outputs/eval/ci-scripted-tier/summary.jsonl
```

The unit tests exercise `run_scenario`; this exercises the CLI, the
durable record layout, the summary files and the cost accounting — the
surface the funded nightly lane uses. It takes about two seconds on the
full fifteen scenarios.

Zero spend is structural rather than hoped for. `USE_MOCK_DATA=true`
keeps the graph on its mock path, the key is the same deliberately
invalid sentinel the rest of `ci.yml` uses, `simulate_learner` refuses
the scripted tier outright when `USE_MOCK_DATA` is false, and
`src/eval/scripted_tier_check.py` then asserts every row: 15 of 15
sessions, no errors, `$0.0000` across all four cost columns, a zero call
count on all three call columns, and no unmet structural expectations.
A dollar figure can round to zero; a call count cannot, which is why
both are checked.

Since ADR [0070](decisions/0070-eval-integrity-provenance.md) it also
asserts, **additively**, that every row carries a complete provenance
block. That is not a quality assertion; it is the precondition for one.
The statistics that land on top of these rows are computed over the
campaign, and a row that cannot name its judge, its rubric versions or
its commit cannot participate in a comparison at all. Nothing the check
already asserted changed. The run directory uploads as the
`scripted-simulation-summary` artifact under `if: always()`, so a red
step still leaves the evidence of *which* session regressed — and so
Gate W1's evidence pack has something to cite.

## The nightly workflow

[`.github/workflows/eval-nightly.yml`](../.github/workflows/eval-nightly.yml)
is the only automated caller of the runner, and since WO-W11 it carries
**two lanes as two independent jobs**: `eval` (research) and
`learning-eval` (guided read). Cron `0 4 * * *` (04:00 UTC), plus a
`workflow_dispatch` whose inputs are split per lane — `queries`,
`threshold`, `max_budget_usd` for the research lane and
`learning_scenarios`, `learning_threshold`, `learning_repeats`,
`learning_max_budget_usd` for the learning one. The budget inputs are
separate on purpose: two campaigns now share one funding conversation,
and the owner has to be able to fund one without the other. There is no
`needs:` between the jobs — a research regression must not suppress the
learning measurement, or the reverse. Concurrency group
`nightly-eval` with `cancel-in-progress: false`, so a manual dispatch
queues behind a scheduled run rather than killing a paid campaign
mid-flight. Job timeout: 120 minutes.

`USE_MOCK_DATA: "false"` is pinned in the job env — the nightly
measures live retrieval, which is the point of it. The first step is a
preflight that fails the run with a titled annotation when the
`ANTHROPIC_API_KEY` repository secret is unset, because that is an
owner action (funding the campaign), not a code fix, and a generic
"copy .env.example" failure fifteen steps later reads like a bug.

The baseline comes from Actions artifacts, not from the repository: the
built-in `gh` CLI finds the most recent completed run of this workflow
on `main` and downloads its `eval-summary-latest` artifact. That step is
`continue-on-error` — a missing baseline is first-run behavior, not a
failure.

Three uploads, all under `if: always()`, because a campaign that died
at query 15 still has fourteen paid records worth keeping:

| Artifact | Contents | Why |
|---|---|---|
| `eval-run-<github.run_id>` | the whole `outputs/eval/<run_id>/` directory | the durable record; 90-day retention |
| `eval-summary-latest` | `summary.jsonl` alone, `overwrite: true` | **the next night's baseline** |
| `regression-report-<github.run_id>` | `regression-report.md` | the diff, uploaded whether or not it was red |

The diff step itself is `continue-on-error`, and a separate step turns
its non-zero exit into the red workflow — that ordering is what lets
the report upload before the run fails. `--allow-removed` is passed
**only** on a manual `queries` dispatch: there a subset is intentional,
while on the schedule a missing query means the batch truncated and the
gate must fire.

### The learning lane

`learning-eval` mirrors that shape step for step, and the mirroring is
the design: same preflight with its own titled annotation, same
"baseline from the previous run's artifact" chain, same
`continue-on-error` diff with a separate red-flip step, same three
`if: always()` uploads.

| Artifact | Contents | Why |
|---|---|---|
| `learning-eval-run-<github.run_id>` | the whole `outputs/eval/sim-<run_id>/` directory | the durable record; 90-day retention |
| `learning-summary-latest` | `summary.jsonl` alone, `overwrite: true` | **the next night's baseline** |
| `learning-regression-report-<github.run_id>` | `learning-regression-report.md` | the diff, uploaded whether or not it was red |

**The research lane's baseline chain is untouched.** `eval-summary-latest`
keeps its name, its contents and its semantics; the learning lane
downloads and uploads `learning-summary-latest` and nothing else. The
two names never appear in each other's job.

It runs the funded tier (`--tier funded`), so it has a second refusal
the research lane does not: a step resolves the campaign ceiling before
anything runs and fails with a titled annotation if it cannot, because
`simulate_learner` will not start an uncapped paid campaign at all. A
dispatch may pass `learning_max_budget_usd`; a scheduled run falls back
to the workflow's `DEFAULT_LEARNING_MAX_BUDGET_USD` of **$15** — WO-W10's
proposed ceiling for the full set at `01` §6.1's estimates plus judge
and simulated-learner spend, a judgment call rather than a measurement.
`--repeats` defaults to 1 and the runner prints the three-repeat warning
accordingly; raise it on a dispatch when a delta actually has to mean
something.

### Status: disabled, and no green campaign yet

**The workflow is disabled** (`disabled_manually`) and stays disabled
until the **W-OD-1** funding decision. WO-W11 edited it — that is what
added the learning lane — but did not enable it, did not dispatch it,
and did not add a secret. Nothing in this repository has ever run a
paid learning campaign.

WO-W11's acceptance criterion 4, *the learning lane's first scheduled
run*, is therefore **deferred behind W-OD-1**, exactly as WO-W09's paid
calibration run and WO-W10's first funded campaign are. What is merged
is the lane; what is not is the run. When the workflow is enabled and
the secret is set, the learning lane's first night produces
`learning-summary-latest` and every subsequent night diffs against it.
Until then the lane would fail at its preflight with a titled
annotation naming the owner action — the same honest failure the
research lane has had, below.

**Every run of this workflow has failed — 54 of 54 between 2026-07-07
and 2026-08-29.** The recent ones stop at the `ANTHROPIC_API_KEY`
preflight; earlier ones died inside `Run eval` for the same missing
secret before the preflight existed. Consequences, stated plainly
because they are easy to miss:

- No `summary.jsonl` has ever been produced by CI, and neither an
  `eval-summary-latest` nor a `learning-summary-latest` artifact exists
  in the repository's artifact store.
- The regression gate has therefore never compared two real runs, on
  either lane. Its thresholds, its aggregate table and its exit codes
  are unit-tested (`tests/test_regression_diff.py`), not yet exercised
  on live data. The learning lane's bands are priors in exactly the
  same sense as the research lane's — reasoned from the mechanics, not
  measured.
- The README's eval-results block is still `(pending)`.
- Every metric figure quoted anywhere in these docs — including
  [`demo.md`](demo.md)'s `summary.jsonl` sample — is illustrative of
  the *schema*, not a measured result.

Unblocking this is a cost decision, not an engineering one: it needs
the `ANTHROPIC_API_KEY` secret set and a funded 20-query campaign. Until
then, treat "the eval harness works" as a claim about the harness's own
tests.

## The published README block

`src/eval/readme_update.py` patches the
`<!-- eval-nightly:start -->` … `<!-- eval-nightly:end -->` block in
`README.md` from a `summary.jsonl`. Two honesty rules apply to what it
publishes (ADR 0050):

- **Cost and latency are the workflow's**, not the judges' — the
  README row answers "what does one research run cost", and the eval
  harness is not part of the product.
- **Runs whose report contained no citations are excluded from the
  citation-accuracy mean.** `measure_citation_accuracy` short-circuits
  a report with zero `[Author, Year]` tags to 1.0 — its own docstring
  says the metric doesn't apply — and averaging those in would inflate
  the published figure exactly when the agent cited least. The block
  states the exclusion and its denominator under the table. Other
  metrics keep the full denominator; a report with no citations still
  has real completeness and recall.
- **Every published mean states how many runs it covers.** A judge
  failure leaves its metric `null`, and the mean silently skips nulls —
  so any metric averaged over fewer runs than the `Queries` count is
  named under the table with its own denominator.

Two gates sit in front of the patch in the workflow, on top of those
three rules:

- **A campaign that did not fully succeed does not publish.** The
  update step carries an `if:` with no status function, which Actions
  reads as `success() && …` — so any earlier red step (`Run eval`'s
  non-zero exit, the regression failure) skips it. The block is a
  published claim, and a campaign that errored, regressed or stopped on
  its budget has not earned it.
- **A `--queries` subset does not publish.** `if: inputs.queries == ''`
  — otherwise a three-query dispatch would print "3 / 3 queries" as if
  it were the whole benchmark (ADR 0050).

When the patch does change `README.md`, the workflow opens (or updates)
a PR on the fixed branch `nightly/eval-readme-update` via
`peter-evans/create-pull-request@v7`, restricted to `README.md`. The
block is never committed to `main` by the workflow itself — a human
merges the PR.

As of this writing that path has never run: see
[Status: no green campaign yet](#status-no-green-campaign-yet).

## What "tested" means for eval code itself

The eval code has its own unit tests: benchmark data invariants
(`tests/test_benchmark_queries.py`, `tests/test_learning_benchmark.py`),
metric-scoring pure logic (`tests/test_metrics_*.py`,
`tests/test_learning_metrics.py` — LLM-as-judge callers are unit-tested
against stubbed responses), the runner's isolation / resume / exit
codes (`tests/test_eval_runner.py`), the simulator
(`tests/test_simulate_learner.py`), both regression lanes
(`tests/test_regression_diff.py`), the per-PR scripted-tier assertion
(`tests/test_scripted_tier_check.py`), the fixture validator
(`tests/test_learning_fixtures.py`), the recorded fixtures' determinism
and freshness (`tests/test_record_learning_fixtures.py`), and the README
block (`tests/test_readme_update.py`).

## Follow-ups

- ~~`feat/eval-metrics-citation-accuracy`~~ — landed.
- ~~`feat/eval-metrics-completeness`~~ — landed.
- ~~`feat/eval-metrics-faithfulness`~~ — landed.
- ~~`feat/eval-runner`~~ — landed.
- ~~`feat/anthropic-retry`~~ — landed. See ADR
  [0009](decisions/0009-anthropic-sdk-native-retry.md). SDK-native
  retry (`ANTHROPIC_MAX_RETRIES=4`, exponential backoff) + a 120s
  per-attempt timeout on every Claude call — clamped down at client
  construction when the retry envelope would not fit the job budget
  (ADR 0051; see the campaign run-book above).
- ~~`feat/eval-ci`~~ — landed. Nightly GitHub Actions workflow at
  `.github/workflows/eval-nightly.yml` runs the benchmark and diffs
  against the previous nightly, using the built-in `gh` CLI plus
  Actions artifacts to carry the baseline rather than a third-party
  action. Regressions fail the workflow: score metrics on the
  `--threshold` epsilon, resource metrics on their two-leg bands (see
  [Regression gate](#regression-gate)). See ADR
  [0010](decisions/0010-nightly-eval-ci.md) and, for the current
  thresholds, ADR
  [0044](decisions/0044-eval-cost-accuracy-and-regression-thresholds.md).
  The workflow's own README-block step does use
  `peter-evans/create-pull-request@v7`; the measurement path does not.
  **Never green yet** — see
  [Status: no green campaign yet](#status-no-green-campaign-yet).
- `feat/faithfulness-fulltext-source` — use cached full text
  (`.cache/pdfs/<id>.txt`) as faithfulness source when available,
  falling back to abstract. Underestimation of Phase-2 faithfulness
  today is documented in ADR 0007.
- Hand-labeled calibration set (~20-30 (report, topic) pairs and
  (claim, source) pairs) once real eval runs give us data to calibrate
  against. Alignment with human judgment is currently unmeasured — see
  [Judge–human calibration remains
  unmeasured](#judgehuman-calibration-remains-unmeasured) for the
  reporting form it must take when it is measured (φ/MCC with both
  positive rates, never raw agreement).
- A funded first campaign, on **either** lane. Everything downstream of
  it — the README block, both regression baselines
  (`eval-summary-latest`, `learning-summary-latest`), the 3-repeat noise
  measurement in [The statistics, honestly](#the-statistics-honestly),
  the calibration set above, and the learning lane's first scheduled run
  (WO-W11 c4) — is blocked on it. It is a cost decision reserved for the
  repository owner, tracked as **W-OD-1**, and the nightly workflow stays
  disabled until it lands.
