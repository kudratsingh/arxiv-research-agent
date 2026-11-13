# Audit source map and validation

Use this index to reproduce the findings without confusing an older main checkout, an archived result and the current campaign implementation.

## Source revisions

| Surface | Identity |
| --- | --- |
| Older main checkout | dbd4bb8e1c8afceba92caf983f018db74cbdcd14 |
| Audited D5 campaign application | 587492d55105914f69524aa32979988508e83c3b |
| Documentation follow-up checkout | 1259ddb37cbb738c290a22d64a7bbaeffe386c71 |
| Campaign packet before the proposed reporting repair | fe3d1d63f0886f1d7d3b48153f2fb696fbd3938b34c0328050ad31d407572afa |
| Proposed capacity and historical-contact exception | 9965e906ee7ff684f3e6be71257ed6d3a09a547bf34048265a44384da1d197f3 |
| Prior timeout-policy application | 92c5a9eafa81bbaa279a5b44312f1519a1bd522c |
| Latest follow-up CI at this snapshot | [43370477206](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/43370477206), in progress |

These identities are provenance, not approval. A later source repair or scoring change requires verification of its own bindings and result.

## Source reference index

Links below are pinned to the audited application. File line numbers refer to that revision.

| Finding | Code or evidence |
| --- | --- |
| AUD 01 Stale checker report | [d5_campaign_report.py at line 99](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/workspace/d5_campaign_report.py#L99), particularly completed-check selection and digest comparison through line 173 |
| AUD 02 Factual primary metric | [campaign/execute.py at line 382](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/campaign/execute.py#L382); eval/groundedness.py, measure_groundedness and paired_outcomes |
| AUD 03 Source identity join | [eval/metrics.py at line 1126](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/eval/metrics.py#L1126); agents/synthesizer.py, lines 250–281 |
| AUD 04 Forced approval | [agents/critic.py at line 198](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/agents/critic.py#L198); graph/workflow.py, lines 143–172; campaign/execute.py, lines 940–960 |
| AUD 05 Truncation | [llm.py at line 681](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/llm.py#L681); agents/synthesizer.py, lines 417–487 |
| AUD 06 Extraction coverage | [eval/metrics.py at line 1342](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/eval/metrics.py#L1342) |
| AUD 07 Retention | Installed /usr/libexec/tmp_cleaner, lines 8–18 and 29–30; /System/Library/LaunchDaemons/com.apple.tmp_cleaner.plist; local recovery manifests |
| AUD 08 Evaluated system | [d5_campaign.py](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/workspace/d5_campaign.py); d5_adapter.py; original GraphEpisodeRunner |
| AUD 09 Answerability | [d5_campaign_packet.py at line 124](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/workspace/d5_campaign_packet.py#L124), selection at line 240; d5_campaign_report.py, lines 245–299 |
| AUD 10 Checker references | [d5_campaign_packet.py at line 308](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/workspace/d5_campaign_packet.py#L308); d5_campaign_report.score_probes |
| AUD 11 Contract boundary | [assistance_coverage.py](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/workspace/assistance_coverage.py); assistance_contract.py; archived v10 draft/schema |
| AUD 12 Runtime provenance | .python-version; .github/workflows/ci.yml; d5_adapter.qualification_producer; actual interpreter and launcher metadata |
| AUD 13 Fixture lifetime | [test_campaign_execution.py at line 443](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/tests/test_campaign_execution.py#L443), module fixtures through line 494 |
| AUD 14 Timeout | [d5_deadlines.py](https://github.com/kudratsingh/arxiv-research-agent/blob/587492d55105914f69524aa32979988508e83c3b/src/workspace/d5_deadlines.py); original v10 request/contact/result receipts; power logs |

The mock-judge and missing-denominator corrections are supported by eval/mock_judge.py and its fixture, campaign/scoring.py at lines 439–456, campaign/report.py at lines 663–709 and 830–879, and eval/readme_update.py at lines 175–201.

## Local evidence locations

Resolve moved originals through the permanent location indices. Do not interpret a historical /private/tmp path as the required current storage location. Keep raw private artifacts and instructions out of public commits.

| Evidence | Current owner-local location |
| --- | --- |
| Active campaign checkout | /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-campaign-complete |
| Captured full ledger | Active checkout, outputs/d5/consolidated-campaign-v12/LEDGER-AFTER.json.gz |
| Captured ledger SHA-256 | d3314c35356fac0efbed42d8cdff8343006bf51f1bfd426e437e9aa5cd3f6397 |
| Initial permanent copy index | /Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-campaign-20261112/LOCATION-INDEX.json |
| Initial retention receipt | Same archive, RETENTION-RECEIPT.json |
| Broader recovery manifest | /Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/recovered-temp-20261112/MANIFEST.json.gz |
| Symlink evidence mapping | Same recovery archive, SYMLINK-RESOLUTION.json |
| Canonical ledger pointer | /Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/research-evaluation-20261105-v1/ACTIVE-QUALIFICATION-LEDGER.json |
| Stale-report reproduction source fixture | Active checkout, outputs/d5/consolidated-campaign-v12/final-real-snapshot-replay/results.json |
| Original v10 timeout receipt | Original-path mapping for outputs/d5/coverage-authority-stage-b-20261111/STAGE-B-RESULTS.json |
| Original v10 timeout receipt SHA-256 | 9b07b94d62683ea512d8b10795c99a82d97fbc9439abf753d57db0b6bfd41bb6 |
| Four owner-attributed prereviews | Recovery mapping for calibration-preflight outputs/d5/premise-preflight-v1-human/reviewer-completed.json |

The 287-file location index and 28,222-file recovery counters were inspected at the documentation refresh. Their existence and counters are not a replacement for the W0 completeness check.

## Read-only reproduction conditions

The audit used Python with bytecode disabled, worktree-specific imports, disabled provider credentials and no live database connection. Public documentation browsing was limited to read-only source verification.

Before any source-level reproduction, confirm:

~~~sh
cd /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-campaign-complete
git rev-parse HEAD
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD:/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps" \
  ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1 \
  /Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python -B -c \
  'import sys, src; print(sys.version); print(src.__file__)'
~~~

This command creates no provider client. Full test suites may create caches and disposable database state; those belong to an authorized implementation batch, not a strict read-only audit.

### Stale report control

Use an owned in-memory copy of the retained synthetic production replay. Retain a valid draft and completed check. Add a repair that changes only coverage roles/status while keeping factual claims unchanged. Add an uncertain recheck with no response. Call score_workflow with the same retained materials.

The audited implementation returns completion false but incorrectly attaches old machine coverage, claim quality and prose findings. The repaired implementation must make current assessments unavailable until a bound completed recheck exists.

### Original metric controls

Call the actual deterministic scorer with one invented assertion citing a retrieved arXiv ID, then ten different assertions reusing that ID, then an empty report. The audited results are 1.0/one measured claim, 1.0/one measured claim and null, respectively.

### Identifier controls

Use one paper stored under its full arXiv URL and cite it through matching URL, bare ID and arxiv-prefixed ID. The audited dossier source counts are one, zero and zero while deterministic citation resolution remains 1.0.

### Gateway and critic controls

Supply a fake SDK response with max_tokens and valid nonempty JSON to the actual completion handler. Separately, give the actual critic a zero-quality revision response at its final allowed iteration. These are software probes; they are not fabricated provider successes.

### Wire boundary controls

Validate the preserved actual v10 draft against its own exact schema and local policy. Mutate one property at a time. Duplicate IDs, orphan claims, unknown/duplicate references, answer/context overlap, an extra claim and excessive claim length remain locally invalid even when accepted by the transformed wire schema.

Match the original task, evidence and revision during replay. Rejection under another task or schema is not a historical failure-rate measurement.

## External documentation checked

- [Claude Sonnet 5.5 overview](https://platform.claude.com/docs/en/models/sonnet-5-5/overview): model identifier and supported thinking behavior.
- [Claude Opus 5.5 overview](https://platform.claude.com/docs/en/models/opus-5-5/overview): model identifier and adaptive thinking.
- [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing): standard input/output rates of $2/$10 and $4/$20 per million tokens.
- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs): constrained output schema and documented limitations.

Official documentation validates configuration claims, not invoice totals, the truth of research outputs or the reason a particular request timed out.

All rights reserved. No license or reuse permission is granted.
