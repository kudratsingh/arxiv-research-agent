# Research evaluation audit findings

The current evaluation infrastructure can execute and preserve guarded workflows, but mechanical completion does not establish accurate or useful research. The highest-priority workspace defect is stale checker information in reports. The original agent also retains a misleading factual metric, inconsistent source joins and completion wording that can imply approval.

The findings below combine read-only inspection with in-memory reproductions. No live generation, token-count request, database mutation or code repair was part of the audit. References and revision identities are collected in the [source map](03-source-map.md).

## Scope and evidence

The primary source revision is campaign application 587492d55105914f69524aa32979988508e83c3b. The subsequent checkout at 1259ddb37cbb738c290a22d64a7bbaeffe386c71 contains no changes under src relative to that application. The follow-up includes publication, tests and frontend theme work; its CI status must be checked independently.

The main checkout remains an older, dirty checkout at dbd4bb8e1c8afceba92caf983f018db74cbdcd14. Its absence of newer workspace code is not evidence that the workspace was never implemented. It was not changed by the investigation.

Evidence labels mean:

- **Confirmed**: directly inspected behavior or a reproduced result.
- **Strongly supported limitation**: the code and retained inputs support the conclusion, but no statistical generalization is established.
- **Unresolved**: the available evidence cannot settle the question.

P1 indicates misleading scientific conclusions or material evidence-retention risk. P2 indicates correctness, reproducibility or reporting problems with narrower impact. These priorities describe consequences, not automatic blockers for every workstream.

## Reconstructed paid execution

The complete captured ledger contains 30 workflow attempts, four checker-only premise probes and 23 count-only jobs. That is 57 raw jobs. One original funded identity predates the programme job baseline, explaining 33 consumed programme jobs rather than 34.

| Packet group | Workflow attempts | Ready | Failed | Uncertain | Messages attempts | Known estimated cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original workspace qualification | 7 | 1 | 6 | 0 | 9 | $0.109967 |
| D5 v3 | 1 | 0 | 1 | 0 | 1 | $0.015644 |
| Opus v5 | 1 | 0 | 1 | 0 | 2 | $0.070748 |
| v6r2 | 2 | 1 | 1 | 0 | 5 | $0.155602 |
| v7r2 | 6 | 5 | 1 | 0 | 14 | $0.473104 |
| v8r4b | 10 | 10 | 0 | 0 | 26 | $0.875440 |
| Coverage v8 | 1 | 0 | 1 | 0 | 1 | $0.023284 |
| Shapes v9 | 1 | 0 | 1 | 0 | 1 | $0.026100 |
| Authority v10 | 1 | 0 | 0 | 1 | 2 | $0.024934 |
| **Workflow total** | **30** | **17** | **12** | **1** | **61** | **$1.774823** |
| Four premise probes | 4 probes | 4 | 0 | 0 | 4 | $0.078988 |
| **Total with Messages** | **34 identities** | — | — | — | **65** | **$1.853811** |

There are 90 count contacts across all jobs. The single $0.425066 hold brings known spend plus held exposure to $2.278877. Pending and unknown represent the same hold and are not added twice.

“Ready” is a mechanical state. In particular, v8r4b's eight evaluation workflows completed mechanically while their later machine-only quality review failed. The census does not convert those results into accepted research.

The snapshot SHA-256 is d3314c35356fac0efbed42d8cdff8343006bf51f1bfd426e437e9aa5cd3f6397. It was read from the durable campaign outputs, not recaptured from the live database.

## Finding register

### AUD 01 Stale checker assessments can attach to an unrechecked repair

**Confirmed, P2. Workspace critical path.**

The D5 report independently selects the latest draft or repair and the last completed check. It validates that check against its own original context and compares factual claim digests, but does not establish that its coverage and prose assessments concern the selected repaired response.

An in-memory reproduction changed only p1 coverage from “lacks evidence with context c1” to “answered by c1,” kept the factual claims identical, and left the final recheck dispatching without a response. The report attached the earlier coverage, claim-quality and prose assessments to the newer response. Completion remained false and the executor did not accept it.

The repair must bind the whole checked response and context, including coverage and prose, and establish that a completed check follows the selected draft or repair. Unbound current assessments must be unavailable. Historical verdicts may be shown as historical.

Source: d5_campaign_report.score_workflow, lines 99–173. Required regression and acceptance criteria: W1 in the [plan](02-implementation-plan.md).

### AUD 02 The original primary metric is not factual support

**Confirmed, P1. Original-agent evaluation track.**

The actual deterministic scorer returned primary score 1.0 for an invented assertion with a retrieved citation. Ten different invented assertions reusing that citation also returned 1.0 with claim_count 1 and supported_claim_count 1. The empty-report control correctly returned null.

The scorer measures deduplicated identifier or quotation outcomes, not every natural-language assertion's semantic support. Its description as supported-claim precision is materially misleading.

Retain citation resolution as an identity diagnostic. A semantic primary metric must use explicitly identified support judgments and a meaningful assertion denominator. Missing semantic evidence must not become a factual pass.

Sources: campaign/execute.py, deterministic_scorer; eval/groundedness.py, measure_groundedness and paired_outcomes.

### AUD 03 Equivalent identifiers can remove sources from the judge dossier

**Confirmed, P2. Original-agent evaluation track.**

build_faithfulness_sources joins raw citation.paper_id to raw paper.id. With a paper stored as a full arXiv URL, an identical citation URL produced one dossier source; equivalent bare and arxiv-prefixed IDs produced zero. Citation-resolution scoring returned 1.0 in all three cases.

Normalize identity consistently before the join while preserving exact version provenance and rejecting ambiguity. Do not silently mix two retained versions when a citation omits its version.

Sources: eval/metrics.py, lines 1126–1137; agents/synthesizer.py also contains raw-ID lookups.

### AUD 04 Iteration exhaustion can be described as approval

**Confirmed, P2. Original-agent execution and reporting.**

At the critic ceiling, revision_needed is forced false. The same flag determines the word “approved.” A controlled reproduction produced “Quality score: 0.00 — approved. (iteration 2/2)” and terminated after a failed-verification route.

The graph and API also distinguish successful execution mainly through nonempty, exception-free output. Quality fields remain available, but completion wording can imply a successful quality decision.

Separate execution completion, iteration exhaustion, verification outcome and quality acceptance. Retain failed verification or unresolved quality when the loop ends.

Sources: agents/critic.py, lines 198–225; graph/workflow.py, lines 143–172; campaign/execute.py, lines 940–960; api/runner.py, lines 2362–2370.

### AUD 05 Valid JSON can hide a truncated terminal answer

**Confirmed, P2. Original-agent gateway and synthesis.**

The original gateway treats stop_reason as observability data. A fake completed SDK reply with max_tokens and a valid, nonempty JSON draft passed the actual completion handler.

Malformed JSON truncation is detected, thinking-only replies are rejected, and parse degradation is recorded. The surviving problem is syntactically valid partial output. Terminal answer acceptance should explicitly account for provider stop reasons; intermediate tool-use responses need their own valid behavior.

Sources: llm.py, lines 109–120 and 681–727; agents/synthesizer.py, lines 417–487.

### AUD 06 Faithfulness extraction can omit the denominator it should judge

**Confirmed instrumentation limitation, P2. Original-agent evaluation.**

The faithfulness judge extracts claims and judges them. Aggregation receives the returned claim list, not an independently established inventory of all assertions in the report. One returned supported claim can score 1.0 without establishing that the report's other assertions were extracted.

Report extraction coverage separately from support among extracted claims. Do not present the latter as whole-report factual accuracy.

Source: eval/metrics.py, _aggregate_claims, lines 1342–1416.

### AUD 07 Temporary evidence storage created real retention risk

**Confirmed risk, P1. Partially mitigated after the initial audit.**

At inspection, 284 D5 output files matched the installed cleaner's access, modification and status-change predicates. The installed cleaner is scheduled at midnight. The outputs include reports and fixtures as well as receipts; the count is not a count of distinct paid responses.

Twenty Git registrations were prunable because their worktree .git link files were missing. Seventeen directories remained and three were wholly absent. Missing files cannot individually be attributed to the cleaner from that observation alone. Committed code in the permanent common Git store is distinct from ignored raw-output durability.

The latest campaign worktree was subsequently moved to arxiv-workspaces. A location index reports 287 verified original files; a broader recovery manifest reports 28,222 files from temporary locations with originals retained. This documentation refresh inspected those manifest counters and the captured ledger hash, not every recovered file's contents.

Verify the existing archives against the at-risk inventory before making more copies. Preserve any missing originals and their original-to-durable mapping; do not relocate everything again or delete predecessors.

Sources: /usr/libexec/tmp_cleaner, lines 8–18 and 29–30; launchd configuration; .gitignore outputs rule; durable recovery manifests listed in the source map.

### AUD 08 D5 and the original research graph are different evaluated systems

**Confirmed architectural boundary, P2.**

The observed paid jobs use workspace qualification adapters. The captured ledger contains no LangGraph campaign adapter. This supports a workspace-only conclusion for that ledger, not a universal claim that no original-agent live run exists anywhere.

D5's snapshot path covers ranking, evidence selection, generation, checking, bounded repair and persistence. Fresh intake, scientific full-text extraction, browser interactions and real-day usefulness require their own evidence. A D5 pass does not validate the original planner, search, reader, synthesizer and verifier/critic graph.

Sources: d5_campaign.py; d5_adapter.py; original campaign GraphEpisodeRunner.

### AUD 09 Selected evidence and requested tasks are not uniformly compatible

**Strongly supported limitation, P1 for interpreting quality.**

All eight current evaluation workflows select abstract-scoped evidence. Research retrieval selects a conversational RAG relevance-label study and a poisoning/conformity study, without a common performance experiment. Verification selects preference-personalization and RAG poisoning abstracts. These can support limited source notes; they do not establish every requested comparison, verification claim or protocol.

The current aggregate requires answered primary requests except the application-insufficiency case. A warranted comparison abstention can therefore prevent a quality pass. That mixes retrieval sufficiency, answerability and model adherence.

Freeze expected answerability per requested part before execution. Preserve unmet user needs as failures of coverage or retrieval while scoring faithful abstention separately. Do not replace retrieved evidence with reference papers to manufacture end-to-end success.

Sources: d5_campaign_packet.py, QUESTIONS and discovery; d5_campaign_report.py, lines 245–299; sealed packet selected units.

### AUD 10 Machine controls do not establish broad checker qualification

**Confirmed evidence boundary, P2.**

Four owner-attributed prereview records exist: two accepts and two rejects over correlated variants of one claim and abstract. They do not establish broad factual accuracy or independent reviewer agreement.

The prospective campaign has twenty machine-reference probes: ten supported and ten unsupported, ten matched pairs and six shared passages. That permits both error directions to be observed. It does not make twenty independent samples or provide human gold.

Keep generated-answer quality, checker-control performance, owner usefulness and human qualification separate. The owner's current choice is machine-only evaluation; human qualification is not an implementation prerequisite.

Sources: premise reviewer export and calibration results; d5_campaign_packet.make_probes; d5_campaign_report.score_probes.

### AUD 11 Provider schema conformance still differs from semantic validity

**Confirmed design constraint, P2.**

The original v10 draft passed its transmitted schema and local semantic checks. Seven adversarial mutations were accepted by that schema but rejected locally: duplicate IDs, orphan claims, unknown references, duplicate references, answer/context overlap, a seventh claim and a 361-character claim.

These examples establish remaining boundaries, not a model-output rejection rate. Some relationships cannot be guaranteed by the supported wire schema alone. The newer implementation also contains archived-response regressions; it is inaccurate to describe all tests as generated from the same happy-path fixture.

Never estimate fourteen-job completion probabilities from a hand-selected mutation set or from failures pooled across changing contracts.

Sources: assistance_contract.py; assistance_coverage.py; actual v10 schema and draft; coverage-authority regression tests.

### AUD 12 Interpreter and dependency provenance need strengthening

**Confirmed reproducibility gap, P2; effect on outputs unresolved.**

The locked local interpreter is Python 3.13.7 while the repository and CI select Python 3.14. The producer binding captures key dependency versions but not the interpreter version.

The editable installation points at the older main checkout, but that alone does not identify what a paid invocation imported. From the intended worktree, the audited stdin invocation imported that worktree. From main, the current directory can still win even when PYTHONPATH mentions another checkout.

Record Python version, executable, working directory, imported src path and critical dependency versions in future receipts. Test version parity deliberately; do not attribute existing failures to the difference without a reproduction.

Sources: interpreter pyvenv.cfg; .python-version; CI workflow; d5_adapter qualification_producer; preserved launchers.

### AUD 13 Module fixture lifetime can conceal test isolation problems

**Confirmed lifecycle risk, P2.**

The campaign test module's full_matrix and mock_judge_matrix are module-scoped generator fixtures. Their MonkeyPatch contexts wrap yield, leaving the model-client and socket stubs installed until module teardown once initialized.

The patches are not autouse, but later tests in that module can inherit them. Place gateway integration tests outside that fixture lifetime or explicitly isolate the fixture. Verify the regression under the full suite as well as in isolation.

Source: tests/test_campaign_execution.py, lines 248–254, 443–470 and 474–494.

### AUD 14 The timeout remains uncertain and latency evidence is insufficient

**Confirmed operational uncertainty, P1 for execution admission.**

The v10 draft passed local contract, coverage and provenance checks. Its Opus request had a 10,769-token preliminary input estimate and timed out under the old 30-second client deadline with no response. The full $0.425066 remaining hold is preserved.

The exact job interval was November 10, 7:08:30–7:09:19 PM PST. Power logs place it between full wake at 6:57:42 PM and sleep at 7:36:18 PM. Sleep is not supported as the cause.

Twenty-seven completed historical Opus responses used 418–1,683 output tokens including thinking, with median 1,079; all ended normally. Those outputs concern earlier requests. They do not establish the enlarged checker's token fit or a 120-second success probability. Existing contact journals lack dispatch, first-byte and completion timings.

The versioned successor's 120-second checks and 480-second workflow bound are implemented software controls. The proposed historical-contact admission exception explicitly retains uncertainty and its hold; it is not a billing reconciliation. Any activation still requires the corresponding approved scope.

Sources: v10 Stage B receipts; d5_deadlines.py; historical contact snapshot; proposed campaign extension.

## Corrections to the supplied audit

| Headline | Corrected conclusion |
| --- | --- |
| 13 of 18 paid attempts failed | Available census is 30 workflow attempts: 17 ready, 12 failed, one uncertain. Four checker probes are separate. The denominator 18 was not established. |
| No human label exists anywhere | Four owner-attributed premise judgments exist. General factual-quality and usefulness labels remain absent from this cohort. |
| Held-out results were erased | Case reuse and exposure are real; historical failed results remain. The latest cohort explicitly discloses exposed source material. |
| Machine-only scoring was an unexplained goalpost change | The owner explicitly requested that scope. It remains machine evidence, not human qualification. |
| Editable installation proves the paid process imported main | Actual invocation matters; audited launchers use the intended worktree. |
| Thirty-six sleep events caused the timeout | The paid interval was awake. A day-level count is not causal evidence. |
| Mock judge passes every row | A deliberate abstention exists. Synthetic positive verdicts still do not establish factual accuracy. |
| Judge failures vanish from current reports | Current reports expose missing metrics and denominators. Conditional averages still require missingness analysis. |
| Twenty prunable worktrees means twenty vanished directories | Only three were wholly absent at inspection; seventeen partially remained. |
| Nine branches without upstream means nine unpublished histories | One such head was reachable from known remote refs; local tracking cannot prove global remote absence. |

## Current publication and preservation update

The latest inspected campaign head is 1259ddb37cbb738c290a22d64a7bbaeffe386c71. CI run 43370477206 was in progress at the documentation refresh. A preceding run failed. Neither previous local success nor older v11 green CI establishes this final head's result.

The current permanent evidence roots are arxiv-evidence/d5-campaign-20261112 and arxiv-evidence/recovered-temp-20261112. The captured ledger hash still matches the audit. The recovery manifests report originals retained. Verify completeness before closing AUD 07.

## Unresolved questions

- Actual usage and completion of the timed-out Opus request, including invoice attribution.
- Latency and output-size behavior of the enlarged checker under real dispatch.
- Independent semantic accuracy of generated answers beyond the small existing controls.
- Comparative quality and cost of the original LangGraph policies.
- Scientific full-text extraction and reasoning quality.
- Whether the workspace helps the owner on actual research days.

Current official documentation supports the configured model IDs, thinking settings and base prices; no model-ID or standard-price mismatch was found. This is not invoice reconciliation. See the external references in the source map.

All rights reserved. No license or reuse permission is granted.
