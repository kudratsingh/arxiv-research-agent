# Request coverage, atomic findings and qualification retention

Prospective offline response revision `workspace-assistance-request-coverage-v8`,
branched from published `a7d4198f`. This is an engineering repair, not human
qualification, a new held-out result, or paid authorization. Stage D stays deferred.

## Request policy and replay

Both new HTTP write endpoints (`POST /workspace/assistance/preview` and `/jobs`)
use a non-null context model. Explicit `task_context: null` is HTTP422 before
preview/submission execution. Omission retains explain/answer defaults. Internally,
nullable historical inputs and the prior task-bound schema remain available for
archived replay. That compatibility is inaccessible as a new HTTP null request.
Old input/output identities are not attached to this revision.

New previews seal up to eight requested parts, in priority order, before a draft
exists. The Reader offers an editable one-part-per-line field with draft recovery.
Blank means the entire current follow-up/project question is recorded as one part;
there is no claimed automatic semantic decomposition. The parts, intent, required
context, evidence, schemas and producer are bound by preview/submit digests. An
edit requires another preview; the API returns409 on a changed request.

## Response and quality boundaries

The maximum remains **six factual claims**. Each claim references the requested
parts it addresses. Every sealed part must appear exactly once in the response's
coverage object, with `answered`, `lacks_evidence`, or `omitted`. Answer references
and context-only references are separate. Claims and parts have reciprocal,
validated references; unknown/orphan/duplicate references are refused. A comparison
cannot be marked answered by source notes. Omission has bounded budget/priority
reasons and cannot masquerade as evidence absence. Missing assessment context
still permits only full abstention with no claims or claim-reference sections.

The request instructs one independently testable finding per claim, prioritizing
the question over background. Preserve study/task scope, comparator, metric
meaning/denominator and conditions in the cited claim text. Separate outcomes
should be split or lower-priority findings omitted, rather than joined to evade
six claims. These are semantic obligations, not properties a JSON schema can
prove. The mandatory checker therefore receives all selected evidence (including
unused approved passages), the predeclared parts, declared coverage and separately
bound claim/part input digests. It must review atomicity, each of the four
qualification dimensions, coverage and priority as well as whole-claim support
and all procedural/optional prose. Missing, stale or duplicate review records
fail closed. Valid quote/offset identity alone cannot establish these judgments.

A decisive quality defect may use the existing single repair and mandatory
recheck. Repair includes the original coverage and exact quality findings.
Residual bundling, lost/uncertain qualifications, unresolved coverage, unsupported
claims or factual procedural prose blocks acceptance. No new retry, fifth call,
price, cap or approval is introduced. Explicit partial coverage can remain useful
as context; it is not a completed answer. Everyday factual acceptance and checker
qualification remain disabled. Machine review has not been scientifically
qualified; synthetic test verdicts demonstrate software control only.

Both Reader result renderers show every requested part, status, bounded gap and
separate answer/context citation links. A full abstention requests missing
application details. Comparison-only abstention visibly says the comparison
remains unanswered. Source/version/passage navigation is preserved.

## Per-case engineering report

Original v8r4b machine review remains 41 claims,18 bundled findings,two lost
qualifications,7/8 request misses and zero accepted results. The annotations are
Codex-attributed synthetic machine review, never independent human labels. The
original scorer, outputs, source bindings and ledger stay immutable.

| Archived development control | Improvement enforced/tested in this revision | Still fails or remains unavailable |
|---|---|---|
| Retrieval | Comparison part separate from context notes; known c2/c3/c5 bundles trigger the quality gate. | No compatible retrieval-relevance task/judgment basis. Poison-detection and predictive-baseline abstracts do not answer the comparison. Split rate, paired-outcome and baseline results; keep source scope. |
| Safety / insufficient | Application policy forces full abstention: original four factual notes become zero claims. | Vehicle/configuration, operating envelope, safety objectives and validation evidence remain missing. No controller safety finding. |
| Mechanism | Inputs/prerequisites, construction/output and unavailable method details are predeclared. c4's NLL/AUROC bundle blocks. | Split metric-specific results with seven-benchmark/four-LLM and baseline scope. CIR specification, graph-to-prediction/encoder/readout details still need methods. |
| Conditions | Scope, conditional results and missing protocol are separate parts. c1/c3 bundles block. | Keep five-domain/security setting, evaluated frozen models and conditions. Separate plausibility/authorization and recalibration/paired gain; missing protocol breakdowns remain gaps. |
| Reproduce | Prioritize task/dataset, evidence-state/stopping judge details and reproducibility inputs. c1/c4/c5/c6 bundles block. | Abstracts do not provide an executable reproduction plan. State schema/update, training, data access/splits and fixed-round controls need source collection; omit secondary leaderboard findings within six claims. |
| Measurement | Separate measured outcomes from proposed applications. c2's two interventions trigger atomicity failure. | Split prefill from banning-plus-examples and preserve intervention conditions/metric; drop lower-priority background if needed. The previous request-complete label remains historical, not a new success. |
| Memory | Direct persistence evidence and retention metric are separate parts. c3/c4 bundling and c3's metric loss block. A synthetic c3 restoration retains exclusion-from-count semantics. | Gain, exclusion-from-count and stored-member outcomes are independent. The selected abstracts do not directly measure incorrect-memory persistence. Restored wording is a manually authored control, not a provider success. |
| Verification | Uncertainty-aware verification/calibration and counterevidence are separate parts. c2/c3/c4/c6 bundles and c3's study-scope loss block. Synthetic restoration retains ProClaim consensus-verification scope. | Ranking, significance, state effects, judge comparisons and conformity results must be separate or prioritized. Confidence calibration/abstention coverage remains unavailable; supported task-specific notes do not establish general uncertainty-aware verification. |

The automated controls deliberately preserve old scientific statements except for
the full-abstention safety projection. Seven retain known quality defects and are
blocked by supplied synthetic checker findings. All eight remain partial or
unanswered in the synthetic coverage projection. This does **not** count as eight
new corrected model outputs. The two manually restored qualification fixtures
exercise provenance/rendering compatibility; their meaning still needs independent
review in a fresh, separately approved development run.

Run the reproducible eight-case report from the worktree root:

```bash
export ANTHROPIC_API_KEY=local-preview-disabled
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
"$VENV_PYTHON" - < planning/14-explore-and-research-modes/d5/tools/request_coverage_report.py
```

Outputs: `outputs/d5/request-coverage-v8/development/{report.json,REPORT.md}`.
Original public passages and outputs are retained in
`tests/fixtures/d5/stage-c-v8r4b/coverage-controls.json.gz` with source/output digests.
The report never changes the frozen scorer or ledger.

## Preservation and evidence

Read-only programme census:30 jobs,61 Messages,81 counts,USD1.779493 estimated;
pending/unknown0. Caps34/80/99/USD10, concurrency1, expiry
2026-11-14T07:24:01Z. No grant, reservation or contact is created here. Provider
and count contacts for this repair are zero. Owner3137/review3178 remain untouched.
Local browser rendering controls are explicitly intercepted, synthetic and GET-only;
real durable behavior is tested separately through disposable Postgres and HTTP.
Final verification and prospective packet identity are recorded in the gate receipt.
