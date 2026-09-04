# 0070. Pin the judges, version the rubrics, record run provenance

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: Phase A assurance program (WO-A08)

## Context

The eval harness is well built — durable per-record writes, per-metric
failure isolation, product-vs-harness cost accounting, a two-lane
regression differ. Its defect is not architecture. It is that **no row
it writes can say what produced it**, and a number that cannot name its
instrument cannot support a comparison.

Three specific facts, all measured on `main` before this change:

1. **The judges were not pinned.** `metrics.py` called `call_llm_json`
   with no `model_name`, so `src/llm.py` fell through to
   `settings.anthropic_model`. Upgrading the product model changed the
   judge in the same commit — the system graded itself with a moving
   ruler, and nothing in the output said so. The same held for all three
   learning judges.
2. **No rubric carried a version.** `COMPLETENESS_SYSTEM_PROMPT` and its
   five peers are ordinary string constants. Editing one silently
   rebaselines every score that prompt produces, and the regression
   differ reads the change as a quality movement.
3. **No summary row recorded the model, the rubric, the commit or the
   dataset.** So a red nightly could not distinguish "the product got
   worse" from "somebody upgraded the model", "somebody tightened the
   prompt" or "somebody added a benchmark query".

WO-A09 adds statistics — McNemar, paired bootstrap, Wilson intervals,
`pass^k`. Statistics computed over unattributable rows are worse than no
statistics, because they are *confidently* wrong. Integrity therefore
lands first, and this ADR is what it lands.

NIST AI RMF **MEASURE 2.1** ("test sets, metrics and TEVV tooling are
documented") is the external form of the same requirement, and the
provenance block is the artifact that satisfies it.

## Decision

### 1. A judge model that is not a fallback

`settings.eval_judge_model` (env `EVAL_JUDGE_MODEL`), defaulting to
`claude-sonnet-4-6` — the model the judges are calibrated against today.
Every judge call site passes it explicitly, via
`src/eval/provenance.py:judge_model()`.

It is deliberately **not** shaped like the per-agent routing fields of
ADR 0021. Those default to `""` meaning "inherit `anthropic_model`";
this one is `min_length=1` and rejects the empty string at settings
load, because inheritance is precisely the defect being removed. It is
still picked up by `resolved_model_ids()`, so an off-table judge model
is detected and priced like any other routed id.

**Changing `EVAL_JUDGE_MODEL` invalidates every existing baseline.** A
regression diff across a judge swap compares two different instruments
and its verdict means nothing. The provenance block records the value so
that swap is visible in the data rather than only in someone's memory.

### 2. Versioned rubrics, enforced by a lock

Each judge prompt gets a version constant beside it
(`COMPLETENESS_RUBRIC_VERSION` and peers) and a `Rubric(name, version,
prompt)` binding the two. `tests/fixtures/eval/rubric_lock.json` records
the shipped history per rubric as `(version, sha256-of-prompt)` entries.

`tests/test_eval_rubric_versions.py` asserts that the live text matches
the newest locked entry, that the live version matches it, and that no
rubric's history reuses a version or a digest. So the only way to change
a prompt is to append an entry under a version that has never been used
— which is what "bump the version when you change the text" means,
expressed as a failing test rather than as a convention.

**The bound, stated plainly:** a determined edit can overwrite the last
lock entry in place instead of appending. That is the standard limit of
any checked-in baseline — it defends against forgetting, not against
intent — and the overwrite shows up as an overwrite in the diff.

`citation_accuracy` has no rubric and gets no version: it is regex and
set membership. A version constant for a deterministic metric would be
provenance theatre.

### 3. A provenance block on every record

One additive nested key, `provenance`, on every record and every summary
row of both lanes. Eleven fields:

| Field | What it answers |
|---|---|
| `harness_version` | which row schema this is |
| `judge_model` | what graded it |
| `product_model` | what was graded |
| `rubric_versions` | `{name: version}` for the rubrics this campaign ran |
| `code_commit` | which checkout produced it |
| `code_dirty` | `true` / `false` / `null` when nobody could check |
| `dataset_version` | which benchmark, at which contents |
| `tier` | `research`, or the learning lane's `scripted` / `funded` |
| `seed` | the harness seed applied |
| `mock_mode` | whether the run was against mock papers |
| `captured_at` | when |

Captured **at record creation**, not at summary-render time.
`rebuild_summaries` re-derives `summary.jsonl` from the durable records
— possibly days later on a `--resume` — and a block captured then would
describe the rebuild rather than the run.

`scripted_tier_check` asserts the block is present and complete on every
row, purely additively: it does not touch a single existing assertion.

Both campaigns' `summary.md` render the block, and say **MIXED** when
rows disagree — a `--resume` can re-enter a campaign under a different
judge or commit, and a summary that quoted only the first row would
present two instruments as one measurement.

### 4. A dataset version nobody has to remember to bump

`dataset_fingerprint(name, items)` returns
`"<name>@<count>:<sha256[:12]>"` over the dataset's own contents.
`RESEARCH_DATASET_VERSION` and `LEARNING_DATASET_VERSION` are computed
at import. Editing a query moves the fingerprint; forgetting to bump a
constant is not a failure mode that exists.

### 5. Dataset provenance on `BenchmarkQuery`

`author`, `created`, `license` added beside the existing `notes`, and
populated honestly for all twenty queries: two authoring dates
(2026-07-05 for the original ten, 2026-07-07 for the Sprint 1
expansion), one author, and `license: "UNLICENSED"` — this repository
ships no `LICENSE` file, so the queries carry no grant, and inventing an
SPDX id here would be a licensing claim the repository does not make.

The annotation on `hallucination-mitigation` — "well-covered by the
built-in mock papers" — is a **contamination note**, not a comment, and
a test now asserts it survives. That query's retrieval recall is scored
against papers hand-picked to match it.

### 6. What the seed does and does not buy

`settings.eval_seed` is applied by `seed_campaign()` at the start of both
campaigns and recorded on every row. It pins `random` and numpy — the
generators anything under `src/` draws from.

It does **not** make a campaign reproducible. The Anthropic Messages API
exposes no sampling seed and the judges are sampled at temperature 0.3.
Recording the seed says what was pinned; it must not be read as a claim
of determinism.

## Alternatives considered

- **Flat provenance fields on the row** (`prov_judge_model`, …) — eleven
  new top-level keys instead of one. Rejected: WO-A09 and WO-A11 are
  both adding fields to these rows in the next wave, and one additive
  key is the smallest surface to hand them. The nesting also keeps the
  block obviously separable from the metrics.
- **A declared `DATASET_VERSION` constant** — rejected. It is a number
  somebody forgets to bump, and a benchmark whose contents moved under a
  stable version is exactly the unattributable row this ADR exists to
  prevent.
- **Reusing the per-agent routing convention for the judge** (`""`
  means inherit) — rejected. That convention *is* the bug. An empty
  `EVAL_JUDGE_MODEL` now fails at settings load.
- **Storing rubric digests in source beside the prompt** — rejected as
  the primary mechanism: the digest would sit two lines from the text it
  pins, so the same edit that changes the prompt naturally updates it.
  A separate lock file with a history is a second party.
- **Failing the scripted tier on `code_commit == "unknown"`** —
  rejected for now. `unknown` is an honest answer from a checkout with
  no `.git` and no `GITHUB_SHA`, and hardening the only gate in this
  repository that has ever caught anything against an environment
  question is a bad trade. The value is recorded and visible; tightening
  it is a follow-up with a measured CI environment behind it.
- **Building verbosity-bias controls into the judges** — rejected on
  evidence. Verbosity bias has collapsed below 0.011 across a 21-judge
  study; the 2023-era folk model is out of date. Position bias has not
  collapsed, but none of these judges runs a pairwise comparison, so
  there is no position to swap. `02-STANDARDS.md` §2.2.

## Consequences

- **Positive.** Every row can name its judge, its rubrics, its commit,
  its dataset and its tier. A regression diff can now tell a quality
  change from a configuration change, which is the precondition for
  WO-A09's statistics being worth computing. A prompt edit without a
  version bump is a red test. A judge swap is visible in the data.
  Mixed-configuration campaigns announce themselves.
- **Negative.** Each record costs one cached `git` subprocess pair per
  process and eleven extra fields on disk. A campaign resumed from
  records written before this change produces rows with an empty block,
  which the scripted-tier check fails — correct, but it means such a
  campaign must be re-run rather than resumed. Changing a rubric is now
  a three-file edit (prompt, version constant, lock entry), which is
  friction by design.
- **Follow-ups.** **Judge–human calibration remains unmeasured** on all
  four research metrics and is deferred: it needs labelled human
  verdicts, which nobody has produced. When it is measured it must be
  reported as **φ/MCC with both positive rates**, never raw agreement —
  raw agreement overstates chance-corrected agreement by 33–41 points
  (85% exact match is a κ of about 0.48) — and the abstention handling
  must be stated, because it swings measured accuracy by 10–34 points on
  identical verdicts. WO-A09 consumes the provenance block; WO-A16 owns
  `citation_accuracy`'s zero-citation behaviour, untouched here.
