# 0074. Measure groundedness deterministically, against the run's own corpus

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: Phase A assurance program (WO-A16)

## Context

This repository can measure hallucination without a model call, and does
not.

The corpus is arXiv papers. That is not incidental — it means two of the
most valuable accuracy signals are **decidable**:

- does every cited arXiv identifier resolve to a paper?
- does every quoted span appear **verbatim** in the paper's text?

Neither needs a judge. Both are cheaper than a judge, do not drift when
a model is upgraded, cannot be argued with, and produce a per-claim
binary outcome — which is exactly the paired variable WO-A09's McNemar
path needs ([`03-ARCHITECTURE.md`](../../planning/08-assurance/03-ARCHITECTURE.md)
§4.2, §4.4; [`02-STANDARDS.md`](../../planning/08-assurance/02-STANDARDS.md)
§2.6).

What exists today instead:

1. **`citation_accuracy` returns `1.0` for a report with zero
   citations.** It awards a perfect score to the exact failure it was
   written to catch. The README compensates by excluding the metric from
   one table; nothing compensates in the gate.
2. **`citation_accuracy` never looks at an identifier.** It matches
   `[Author, Year]` tags in the report against a `(lastname, year)` set
   built from `state["citations"]` — the same list the synthesizer
   wrote. A model that invents a whole citation entry, plausible authors
   and a fabricated `paper_id` included, scores 1.0. Measured on this
   repository's own e2e fixture, which does exactly that (below).
3. **Faithfulness is a judge call against abstracts only.** ADR 0007
   records the under-estimation that buys. It costs money, it moves when
   the judge moves, and content-preserving wrappers flip 57–100% of
   LLM-judge verdicts, so a judge inside a gate is an attack surface
   rather than a control.

## Decision

`src/eval/groundedness.py` — a new module, no dependency, no I/O, no
model call.

### 1. Identifiers resolve against the papers the run retrieved

Not against arxiv.org. The harness blocks non-loopback sockets, but the
design reason is stronger than the harness reason: **a citation to a real
paper the run never fetched is still a fabricated citation**, and that is
the interesting failure. The oracle is `build_corpus_index(papers)` over
`state["papers"]`.

Three outcomes, deliberately distinct, because they have different
owners:

| reason | meaning |
|---|---|
| `citation_resolved` | well-formed, and the run retrieved it |
| `citation_not_retrieved` | well-formed, and the run never fetched it |
| `citation_malformed` | not a well-formed arXiv identifier |

Both citation surfaces are checked: identifiers in the report body
(`arXiv:…` or an `arxiv.org` URL — a bare number in prose is *not*
extracted, because numeric text is common and the recall is not worth
the false positives), and the identifier each `state["citations"]` entry
asserts. The second is the surface `citation_accuracy` cannot see.

Canonical form is `arxiv:<id>`, matching what
`src/eval/learning_benchmark.py` already calls canonical. Version
suffixes are stripped — a citation to v2 of a paper fetched at v1 is not
a fabrication, and treating it as one would make the metric measure
arXiv's revision history. Old-style ids (`cs.CL/0301001`) are case-folded
whole. Semantic Scholar papers keep their `s2:` identity so a citation to
one still resolves.

### 2. Quotes are located verbatim, under a stated normalization

Three match levels, and **which level matched is recorded on every
quote**:

| level | rule |
|---|---|
| `exact` | raw substring, no transformation |
| `folded` | format chars stripped → NFKC → line-break de-hyphenation → quote/dash folding → whitespace collapse → case-fold |
| `skeleton` | `folded`, then everything that is not a letter or digit removed |

Nothing else is normalized. No stemming, no stopword removal, no
edit distance, no abbreviation expansion. One changed word, one changed
number or a reordered clause fails at every level, and
`TestWhatIsNotNormalized` holds that edge.

Two choices inside this are worth naming.

**De-hyphenation is knowingly incomplete, and paired with a fallback.**
`inter-\nnational` → `international` is right; the same rule turns
`state-\nof-the-art` into `stateof-the-art`, which is wrong. No
dictionary-free rule can tell the two apart. Rather than pretend, the
`skeleton` level removes hyphens outright and subsumes the case. A cheap
rule plus a fallback that covers its failure beats a rule that claims a
distinction it cannot make.

**Elided quotations are split, not skipped.** A quote containing `...`
is a sequence of spans, and its fragments are searched **in order** —
fragment *n+1* from the end of fragment *n*, so fragments appearing in
the wrong order are correctly not found. A fragment under three words is
evidence-free, and such a quote is reported undecidable rather than
scored.

### 3. Source completeness gates the denominator

A quote can only be *falsified* against a complete source. Given only an
abstract, "not found" means "not in the abstract".

- `full` — parsed document text. A miss is a real miss.
- `partial` — ranked evidence chunks (ADR 0016) or the abstract. A hit
  still proves the quotation; a miss is `quote_source_incomplete`, which
  leaves the denominator instead of failing.

`source_coverage` is published beside the rate so the exclusion cannot
quietly empty the metric, and `excluded` is a field on every metric.

`SourceText` keeps its text as `segments` and never matches across two of
them: the evidence chunks are non-contiguous, and since whitespace
collapses at `folded` and vanishes at `skeleton`, no separator survives
to keep two excerpts apart. A quote bridging two chunks is text that was
never written.

One more outcome falls out of this and is worth having: when the
attributed paper's source is `full` and the quote is absent from it but
present verbatim in another paper's `full` source, the verdict is
`quote_misattributed` — a specific defect no judge reliably names.

### 4. Metrics that cannot report a score they did not earn

`citation_resolution_rate`, `quote_verbatim_rate` and
`unsupported_claim_count`, all in one envelope: `value`, `numerator`,
`denominator`, `excluded`, `reason`. **`value` is `None` exactly when
`denominator` is 0**, with a reason code — `no_citations`, `no_quotes`,
`no_checkable_quotes`, `no_checkable_claims`.

`no_quotes` and `no_checkable_quotes` are separate on purpose: "the
report quoted nothing" and "the report quoted and we had no complete
source" are different facts about a run, and collapsing them would hide
an empty PDF cache behind a clean-looking metric.

`unsupported_claim_count` obeys the same rule though it is a count: zero
problems found in zero claims checked is "nothing measured", not
"nothing wrong".

### 5. A per-claim outcome WO-A09 can pair on

Each claim yields `{claim_id, kind, subject, locator, grounded, reason,
detail}`. `claim_id` is `<kind>:<sha256(subject)[:16]>` — content-derived,
so the same claim has the same id across arms and across runs, and moving
a sentence does not move the id. `paired_outcomes()` projects a result to
`{claim_id: bool}`, dropping undecided claims rather than defaulting
them.

What this module deliberately does **not** decide: whether a claim id
present in one arm and absent from the other is discordant or out of
scope. That is a statistical judgement and belongs to `src/eval/stats.py`,
which WO-A09 owns. This side's only contract is that the ids are stable.

### 6. The check names itself

`GROUNDEDNESS_CHECK_VERSION` plus a digest of `NORMALIZATION_SPEC`, on
every result as `check`. This is ADR 0070's rubric-versioning mechanism
applied to a check that has no prompt: the normalization *is* the thing
whose change invalidates a comparison, and
`TestCheckIdentity::test_the_normalization_spec_is_locked_to_its_version`
fails if the spec moves without a version bump. A `RunProvenance` block
passed by the caller rides on the result under the same key every other
eval row uses.

## What calibration against the fixtures actually found

The work order's trap is that a quote check which is too strict measures
the PDF parser rather than the agent. Four findings, all measured:

1. **The repository's own e2e fixture contains a citation to a paper the
   run never retrieved, and today's metric scores it 1.0.**
   `tests/fixtures/e2e/research_llm_responses.json` cites
   `http://arxiv.org/abs/2311.05232`; in mock mode the retrieved corpus
   is `search.MOCK_PAPERS`, whose survey paper is `2311.09000`.
   `measure_citation_accuracy` returns `score=1.0` (the `[Ji, 2023]` tag
   matches the citation list that asserted it);
   `citation_resolution_rate` returns `0.0` over a denominator of 1, with
   reason `citation_not_retrieved`. This is not a synthetic example — it
   is a checked-in fixture, found by running the new check over it.

2. **No recorded fixture in this repository contains a single multi-word
   quoted span.** A scan of all 30 JSON fixture files (1,143 strings)
   found 17 quoted spans, every one of them a single word from a JSON
   key listing in `tests/fixtures/contracts/shared_kernel_v1.json`. So
   over today's recorded corpus `quote_verbatim_rate` is `None` with
   reason `no_quotes` — which is the right answer and is exactly the
   behaviour `citation_accuracy` gets wrong. The quote path is
   calibrated against `tests/fixtures/groundedness/run.json` instead,
   which is hand-authored and says so.

3. **Whitespace is the whole game; without normalization the check would
   measure the extractor.** `fitz.Page.get_text()` returns a hard newline
   at every rendered line break — confirmed by round-tripping a
   generated PDF through PyMuPDF offline. In that probe, three of four
   quotations that genuinely appear in the source matched at `folded` or
   `skeleton` and **none** matched as a raw substring. A check without
   `folded` would report a hallucination rate close to 100% on true
   quotations. This is the single strongest argument for normalizing at
   all, and the reason `exact_quote_count` is reported separately rather
   than being the metric.

4. **The minimum-quotation length is doing real work.** Quoted spans
   below `MIN_QUOTE_WORDS` (6) are terminology and scare quotes — `the
   "attention" mechanism`, `a "hallucination"` — not quotations.
   Including them would put the report's punctuation habits into the
   denominator. Six is a calibration constant, published on every result
   as `min_quote_words` so a reader can see what the denominator was
   built from.

A fifth thing the probe settled: generating a PDF with PyMuPDF's base-14
fonts does **not** reproduce arXiv's extraction artefacts (non-Latin-1
glyphs come back as `?`), so no test ships a synthetic PDF. The artefacts
are planted in the fixture text directly, listed in its `_readme`, and
each has its own test.

## Alternatives considered

- **Resolving identifiers against arxiv.org.** Rejected twice over: the
  harness blocks non-loopback sockets, and it is the wrong oracle. "This
  identifier exists" is a weaker claim than "this run read it", and the
  weaker one lets a fabricated citation to a real paper pass.
- **Fixing `citation_accuracy` in place.** Not available:
  `src/eval/metrics.py` belongs to WO-A08 in this wave. Given the choice
  it would still be wrong to make the metric mean something new under
  its old name — every baseline scored with it would silently become
  incomparable. See Follow-ups.
- **Fuzzy quote matching (edit distance, token-set overlap).** Rejected.
  It would make the check un-arguable-with in the wrong direction: the
  entire value of a verbatim check is that a changed word is a failure.
  A threshold would be a second calibration constant with no principled
  value, and normalization already covers the artefacts that are not the
  agent's doing.
- **Treating markdown blockquotes as quotations.** Rejected. In this
  repository's reports a `>` block is as often the model's own summary as
  a citation of source text; failing on it would measure formatting.
- **Scoring a miss against an abstract-only source as unsupported.**
  Rejected — it is precisely the trap the work order names, and it would
  make the metric a report on PDF-cache coverage. The miss is excluded
  and the exclusion is counted.
- **Counting an unattributed quotation as unsupported.** Rejected. We
  will not guess which paper a quotation came from and then fail the
  report for our guess. It is reported as `quote_unattributed` and
  excluded.
- **Importing `metrics._CITE_PATTERN` and `_normalize_first_author`.**
  Rejected: they are private members of a module another work order owns
  this wave. The `[Author, Year]` pattern is duplicated here, which is
  named as a follow-up rather than hidden.
- **Registering the normalization spec as a `provenance.Rubric`.**
  Rejected for now. `tests/test_eval_rubric_versions.py` asserts the lock
  file names no rubric the harness dropped and vice versa, and both
  registries live in files this work order may not touch. The equivalent
  lock lives in `tests/test_groundedness.py` instead; folding it into the
  shared lock is a follow-up.

## Consequences

- **Positive.** Hallucination is now measurable at `$0.0000`, offline,
  deterministically, with a per-claim binary outcome and a published
  denominator on every number. The check does not move when a model is
  upgraded. Three defects that no judge names reliably —
  `citation_not_retrieved`, `citation_malformed`, `quote_misattributed`
  — are now named exactly. A report with zero citations can no longer
  score 1.0 anywhere in this module.
- **Negative.** `quote_verbatim_rate` is only as strong as the corpus's
  parsed text: with abstracts alone almost every quotation is excluded,
  and the metric will honestly say so rather than produce a number. The
  `skeleton` level is a real weakening — it makes `the rapist` and
  `therapist` one string — which is why the level is recorded per quote
  instead of being folded into the rate. The `[Author, Year]` pattern is
  duplicated from `metrics.py`. And the check is deliberately blind to
  paraphrase: a report that fabricates a claim without quoting anything
  is invisible here, which is why this complements the faithfulness
  judge rather than replacing it.
- **Follow-ups.**
  - **Replace `citation_accuracy` at its call sites** with
    `citation_resolution_rate`, and delete the README's compensating
    exclusion. **Owner: WO-A08's owner**, who holds
    `src/eval/metrics.py`; it cannot be done from this work order's file
    set. Doing it invalidates every baseline scored with the old metric,
    so it lands with a dataset/version note, not quietly.
  - **Wire the per-claim outcomes into the paired comparison.** Owner:
    WO-A09, which owns `src/eval/stats.py` and `regression_diff.py`. The
    shape is `paired_outcomes()`; the open question A09 decides is how to
    treat a claim id present in only one arm.
  - **Feed parsed PDF text into the check.** Owner: WO-A09 (it holds
    `src/eval/runner.py`). Until a caller passes `full_texts`, the quote
    path reports `no_checkable_quotes` on live runs. This is the same
    follow-up `docs/eval.md` already tracks as
    `feat/faithfulness-fulltext-source`.
  - **Fold the normalization spec into the shared rubric lock**, once a
    work order owns both `metrics.py` and the lock file.
