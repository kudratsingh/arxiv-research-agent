# D5 review import and reproducible quality grading

This workflow makes **no provider or token-count contact**. Reviews live in external, append-only sidecars. Importing a review neither changes the immutable packet/raw outputs nor writes to the database, ledger, source material, approvals or everyday-generation state.

The evaluator is `d5-reviewed-quality-v1`; the sidecar format is `d5-human-review-v1`. See [the active packet identity](d5-packet-identity.json), [offline quality report](OFFLINE-QUALITY.md) and [unexecuted paid proposal](PAID-VALIDATION-PROPOSAL.md). The preceding packet v2 and its blank worksheet remain preserved. A v2 run can be explicitly reanalyzed by the new evaluator; it is never relabelled as a v3 run.

## Export, validate, import and score

Run from the worktree root. Use the original observed `results.json`, not an already rescored report. The committed gzip raw result is also supported. Choose new output paths; exports/reports refuse overwrite.

```sh
cd /private/tmp/arxiv-agent-eng-workspace-assistance
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export PACKET=planning/14-explore-and-research-modes/d5/d5-system-validation-v3.json.gz
export RESULTS=outputs/d5/benchmark-review-v3/results.json

# Readable blank JSON: no reviewer, timestamp or judgment is invented.
$VENV_PYTHON -m src.workspace.d5_reviews export --packet "$PACKET" --results "$RESULTS" --out outputs/d5/review-owner-blank.json
# Optional: include candidates from the whole frozen pool for relevance/reference labels.
$VENV_PYTHON -m src.workspace.d5_reviews export --packet "$PACKET" --results "$RESULTS" --retrieval --out outputs/d5/review-owner-with-retrieval.json

# Edit a COPY, supplying only reviews actually performed. These commands do not label it.
$VENV_PYTHON -m src.workspace.d5_reviews validate --packet "$PACKET" --results "$RESULTS" --review outputs/d5/review-owner-completed.json
$VENV_PYTHON -m src.workspace.d5_reviews import --packet "$PACKET" --results "$RESULTS" --review outputs/d5/review-owner-completed.json --store outputs/d5/reviews-owner
$VENV_PYTHON -m src.workspace.d5_reviews score --packet "$PACKET" --results "$RESULTS" --store outputs/d5/reviews-owner --out outputs/d5/quality-owner-v1
```

The score command writes `results.json`, `REPORT.md`, `index.html` and `analysis-receipt.json`. An empty/missing store is valid and produces an unreviewed HOLD report. Validation accepts partial reviews but does not pretend they are complete. Identical canonical re-imports return `idempotent=true` and do not append or reactivate an earlier adjudicated label.

## What a review binds

The top-level packet digest, run ID and full original-result digest must match. Every item binds its kind, case/job/claim or probe identity, the exact observed output/claim digest, and the relevant evidence identity (source version, material/parser/hash, scope, quotation and Unicode offsets). Case items disclose the entire observed output, including optional prose. Retrieval items bind the frozen candidate, ranking and edition.

Keep `target`, `binding`, `observed`, packet/run/result fields unchanged. Unknown items/fields, duplicate targets or JSON keys, cross-case identities, changed evidence, stale outputs and mismatched runs are rejected. Attribution is required whenever any judgment is non-null: `reviewer`, timezone-aware `reviewed_at`, `reviewer_role`, `provenance` and `method`. Provenance is `independent_human`, `machine_assisted_human` or `synthetic`; synthetic reviews require the synthetic role. Attribution is a reviewer's declaration, not cryptographic proof of identity or independence.

## Rubric and denominator rules

| Item | Labels | Treatment |
|---|---|---|
| Claim/probe | `support`: supported / unsupported / insufficient / unreviewable; `atomic`; `qualifications_retained` | Missing remains null. Insufficient/unreviewable are visible reviewed items but not decisive positives or negatives. Claim eligibility remains in the denominator. |
| Case | `complete`; `material_omissions`; `comparison_compatible`; `counterevidence_handled`; `appropriate_abstention`; `prose_support` | All required judgments must be supplied. Applicability fields accept an explicit `not_applicable`; a declared comparison or abstention needs its corresponding positive judgment. Optional factual prose cannot escape review. |
| Usefulness | Optional useful / maybe / irrelevant | Separate from factual acceptance. Only an attributed owner review populates owner usefulness; synthetic choices remain proposed fixture labels. |
| Retrieval | Relevant / irrelevant / insufficient / unreviewable; `known_reference` | Judged precision and review coverage reported separately. Full selected precision needs every selected item judged. Known-reference recall needs reference labels across the entire frozen pool; no positive references or incomplete labels gives null. This is pool recall, never literature recall. |

Factual support uses supported / (supported + unsupported), with insufficient/unreviewable/missing counts and coverage alongside it. Atomicity and qualification reviews use their own explicit denominators. Minimum generated-fact evidence counts unique text/evidence facts with decisive support plus atomicity and qualification reviews, **fresh system cohort only**. Development facts and exact duplicates cannot fill that minimum. The unchanged minima are20 generated facts and20 decisive observed probe judgments; fewer means HOLD, without adding cases after results.

Checker comparisons use the actual last check/recheck verdicts, not the proposed negative label. False-pass and false-failure rates and agreement are conditional on both a decisive human support label and a decisive checker judgment. Checker abstentions are excluded from those conditional denominators and separately counted/rated. Missing machine verdicts and indeterminate human judgments remain visible. Positive-only or negative-only cohorts leave the unavailable error-rate denominator unscored. Per-cohort results and disagreements retain case/claim identities; correlated claims are not independent samples.

## PASS, FAIL and HOLD

- Failed/unscored required mechanical provenance prevents factual acceptance, even with positive semantic labels. Reanalysis resolves the actual output against the original sealed units/materials again; it does not trust an old report's passing badge.
- Unsupported claims, non-atomic claims, lost qualifications, material omissions, incompatible comparisons, mishandled counterevidence/abstention or unsupported substantive prose fail the corresponding case gate.
- Required missing or indeterminate labels produce HOLD/UNSCORED. A valid quote alone cannot pass. An empty output needs an explicit, appropriately reviewed abstention; it cannot become an accepted answer.
- A run passes the observed-label grading policy only if the frozen completion/provenance/rubric/minimum/zero-false-pass conditions are met. An observed failure takes precedence over a missing-sample HOLD. No missing denominator is manufactured as perfect.
- A synthetic or machine-assisted grading PASS is **not independent human qualification**. Simulated outputs also keep qualification on HOLD. `checker_qualified` and `everyday_generation` remain false in every report, including a scoped grading PASS. This small set cannot statistically certify a checker or everyday usefulness.

Cost per accepted result uses all fresh workflow plus mandatory-checker spend divided by accepted fresh results, including costs of failed fresh attempts. Missing/invalid costs, unknown liability or zero accepted results make it unscored. Development/probe overhead and the complete financial view remain in the unchanged accounting block. Grading never releases a reservation or turns invalid content ready.

## Conflicts and versioned adjudication

Imports are locked and append-only. A conflicting record is refused unless a new review file increments `review_revision` and supplies:

```json
{"adjudication":{"supersedes":["EXACT_ACTIVE_PRIOR_REVIEW_DIGEST"],"reason":"Who resolved the disagreement and on what evidence"}}
```

Use the digest returned by import. Include only the changed targets when practical. Each changed target must supersede its **current active** predecessor; a stale ancestor does not suffice. Original receipts and labels remain retained. Reviewer's attribution/timestamp/method should describe the actual adjudication. Blank fields never erase an earlier supplied label. A second expert's disagreement must be preserved and explicitly resolved rather than silently averaged.

## Analysis receipts and historical rescoring

Every analysis receipt binds the original packet/run/raw-result digests, current scorer version and code hashes, runtime version, imported review-file digests and active review-set digest, report version, frozen scoring policy and unchanged accounting digest. Repeated scoring over identical inputs produces identical substantive results. New scorer/source bindings create a prospective packet revision; old jobs retain their original packet and producer.

For a v2 historical D5 analysis, use `d5-system-validation-v2.json.gz` together with `evidence/benchmark-results.json.gz`, and a separate review store/output directory. The exported/graded report explicitly retains that v2 identity. The stopped q01–q04 programme and original0/9 diagnostic are not replayed. Historical estimated spend stays$0.109967; this batch adds$0 and0 provider/count contacts.

Actual owner worksheets remain blank. Synthetic demonstrations and tests use separate stores/files with synthetic reviewer provenance. Review import updates analysis reports only; it does not edit the original Reader job record or enable generation. Paid validation still needs its separate exact packet-bound approval.
