# D5 v4 fresh measurement/development proposal — UNAPPROVED

No provider or token-count call is authorized by this document. The v3 Stage B scope remains stopped. Do not renew/replay it, reuse its authorization, run held-out cases, or infer permission from a key or remaining money. Everyday generation, recurrence and notifications remain disabled.

Packet: **`d5-system-validation-v4.json.gz`**, digest **`f21f4b66e1eb99ab75c7c242a9bfa46acb78ccabc13fb885477e8160425fd95a`**. Application **`9bd25a82d313070e810038c8de42c0dc3d9cb8b1`**. [Identity/bindings](d5-packet-identity.json), [exact requests and schemas](evidence/contract-repair-v4/prospective-requests.json), [failure lineage and quotas](d5-quota-v4.json). Predecessor v3 **e1ed94498ce74231621f5c1394ddabd0aee11d3c42b7f88f5983e78d22c6d1da** and its stopped result/authorization remain historical. The v3 proposal is [preserved separately](PAID-VALIDATION-PROPOSAL-v3.md).

## Smallest runnable stages under the existing runner

| Stage | Exact operations | New funded jobs max | Messages max | Count contacts max | New spend cap |
|---|---|---:|---:|---:|---:|
| A, fresh measurement only | measure-1/dev-learn; measure-2/dev-compare; measure-3/research-retrieval; measure-4/research-insufficient |0|0|4|$0|
| B, fresh development only, requires separate explicit permission or an approval expressly including A+B | dev-learn, then dev-compare, each under the changed v4 request identity |2|8|8 paired|$0.80 total, $0.40 all-in per job|
| Proposed A+B envelope | No other named case/stage |**2**|**8**|**12**|**$0.80**|

A is four requests because the protected runner requires all four initial named measurements before B. Counts are for the changed exact wires. Old v3 counts do not prove v4 token fit. Measurement is not a workflow job or Messages-schema acceptance. Draft/check/repair/recheck each require their own actual paired count before dispatch; checker/repair wires are derived only from the actual preceding output. Their future exact digests cannot be known before those outputs exist.

No C or D permission is proposed. Development remains outside the held-out denominator. dev-learn v4 would be a **new explicitly approved attempt related to failed v3 dev-learn**, never a retry of its stopped identity. dev-compare v3 was unrun, not a success. Current frozen system cases are retained as definitions, not silently funded or scored.

## Request and contract bindings

Model **claude-sonnet-5-5** for workflow and mandatory checker, thinking **between_tools**, effort **medium**, no temperature, cache, batch, external tools, search, model fallback or source expansion. Workflow output<=4000 tokens; checker<=1800; raw input<=20000, paired measured count<=16000 (1.25 margin), four Messages maximum per workflow, at most one repair and one recheck. One job/call at a time; no automatic HTTP retry. Producer, profile/question, source/version/material/parser/hash/Unicode offsets, selected units, settings, local and transformed wire schemas and prompt hashes are sealed. Strict wrong-version/quote/offset/unselected-evidence checks remain.

Single-paper Learn and one-source Research omit cross-source comparison fields. Within-paper contrasts remain attributed cited claims. Applicable Research comparison_basis uses distinct emitted c1–c6 claim IDs, with independent source bases. Optional factual prose is still checked; an unverified label is no exemption. Human support, atomicity, qualifications, omissions, comparison compatibility and counterevidence remain independent review fields.

Only the selected retained public evidence and frozen machine-authored questions are sent. Private notes, owner question text, preferences, reading history and drafts stay excluded. The same40 public works/42 materials and two bounded PDF samples are replayed; this is neither fresh intake nor complete-paper acquisition. Review [initial public request bodies](evidence/contract-repair-v4/requests/).

## Cumulative budget and feasibility — no reset

Current ledger: **10 Messages,20 counts, estimatedUSD0.125611**, workflowUSD0.110299/checkerUSD0.015312, pending/unknown0. Original historicalUSD0.109967 plus rejected Stage B USD0.015644 are preserved. Eight cumulative funded identities include the original parent qualification; **7/20 programme jobs are consumed**, including the failed new attempt. Remaining programme capacity: **13 funded jobs,70 Messages,60 counts,USD9.874389**. Preserving the existingUSD1 uncertainty headroom leavesUSD8.874389 available for admission, not permission.

The proposed A+B worst limits yield18 cumulative Messages/32 counts,9/20 programme jobs consumed,11 remaining funded slots, and cumulative spend at mostUSD0.925611. Conservative reservationsUSD0.80 + preserved headroomUSD1 + currentUSD0.125611 =USD1.925611, below the unchangedUSD10 ceiling. The complete metered two-workflow envelope is at mostUSD0.552 at sealed rates:8×20000 input +4×4000 workflow output +4×1800 checker output. An illustrative no-repair shape (5000/700 workflow +2000/75 checker per job) isUSD0.0435 total; this is an assumption, not measured token fit or a forecast. Count requests are pricedUSD0 in the sealed contract; verify current documented access/pricing before any future execution.

The original unrun C/D schedule requires12 funded jobs (8 system +4 checker batches). After two fresh development jobs only11 slots remain. **The full original schedule cannot then fit.** Do not increase the20-job ceiling, remove a failed job, assume probe negatives, lower the20-fact/20-probe minimum, add cases or run a partial schedule and call it qualified. A later reviewable plan must address this before any C/D approval. This A/B-only proposal establishes development readiness at most, not qualification.

Rates remain the sealed **estimates** ofUSD2/input million andUSD10/output million, verified in the prior packet on November6UTC; this offline batch did not refresh them or contact a provider. [Official pricing](https://platform.claude.com/docs/en/about-claude/pricing) and [model/settings documentation](https://platform.claude.com/docs/en/models/sonnet-5-5/overview) are the future preflight references. Invoice reconciliation, real token fit of changed requests, remote schema acceptance and response quality remain unmeasured. Any pricing/settings/model/source/schema/code drift requires stop and a new binding; never substitute silently.

## Concrete commands — future paid commands NOT RUN

Run from the worktree root. The prospective unmarked DB `workspace_d5_contract_v4_validation` has the exact latest public/financial snapshot but **no budget policy, scope authorization or grant**. It is not the active ledger. The active stopped ledger remains `workspace_d5_review_validation`, named by outputs/d5/ACTIVE-QUALIFICATION-LEDGER.json. Before any future grant, compare their full census hashes and the current programme; if they differ, stop rather than use a stale copy. A separately approved handoff must update the active ledger pointer before dispatch; do not run ledgers concurrently. The old scope remains stopped.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export PACKET=planning/14-explore-and-research-modes/d5/d5-system-validation-v4.json.gz
# Offline, no permission or contact:
ANTHROPIC_API_KEY=local-preview-disabled $VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
# Exports approved=false; does not enable dispatch:
ANTHROPIC_API_KEY=local-preview-disabled $VENV_PYTHON -m src.workspace.d5_operator template --packet "$PACKET" --stages A --receipt outputs/d5/owner-authorization-v4.json
```

Only **after new explicit approval** and a verified cumulative-ledger handoff, an operator may fill that exact receipt from the owner's instruction, with an expiry and unchanged exact limits. Never copy fixture permission. The two named prospective principals (`d5-v4-validation-measure`, `d5-v4-validation-run`) remain members of the same immutable programme. Their historical baseline includes the failed v3 identity; new names cannot reset capacity or evade a stopped attempt.

```sh
# UNEXECUTED. Requires separate explicit A-only approval and matching receipt.
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_contract_v4_validation
unset WORKSPACE_D5_OFFLINE
# Configure credential only in the separate approved operator shell; never print it.
$VENV_PYTHON -m src.workspace.d5_operator record --packet "$PACKET" --receipt outputs/d5/owner-authorization-v4.json
$VENV_PYTHON -m src.workspace.d5_benchmark run --packet "$PACKET" --stage A --out outputs/d5/paid-v4-A
# STOP for measurement review unless that same new approval expressly permits A+B.
# A later new B approval uses an append-only grant preserving parent expiry:
$VENV_PYTHON -m src.workspace.d5_operator stage-template --packet "$PACKET" --stages B --receipt outputs/d5/owner-B-v4.json
# After independently supplied explicit B approval only:
$VENV_PYTHON -m src.workspace.d5_operator grant --packet "$PACKET" --receipt outputs/d5/owner-B-v4.json
$VENV_PYTHON -m src.workspace.d5_benchmark run --packet "$PACKET" --stage B --out outputs/d5/paid-v4-B
# Revocation (no provider call):
$VENV_PYTHON -m src.workspace.d5_operator revoke --packet "$PACKET" --receipt outputs/d5/owner-authorization-v4.json
```

Stop at the first contract/provider/admission/accounting failure, drift, cancellation, timeout, revocation, expiry or uncertain completion. Failed/uncertain contacts consume limits. Preserve complete-response usage and unknown holds; invalid content never becomes ready to release money. Do not replay under an alternate ID, automatically repair invalid responses, renew expiry or broaden permission. An authorized bounded repair is possible only after a valid draft and checker outcome under the sealed workflow.

## Acceptance and review

For development only: each admitted result must complete its declared path with exact provenance and no hidden unscored factual prose; review every actual claim, qualification, comparison, counterevidence/omission and abstention. Blank labels remain missing. Agreement is not human support. A small two-job trial cannot establish checker reliability or everyday usefulness; development facts never fill held-out20-fact minimums. The predeclared fresh-system 8/8 completion,20 reviewed generated facts,20 decisive reviewed probe items and zero false-pass rules remain unchanged and HOLD while unfulfilled. No actual human or owner usefulness judgments are supplied.

[Offline repair/verification runbook](CONTRACT-REPAIR-v4.md), [original review import/scoring workflow](HUMAN-REVIEW-RUNBOOK.md). Any new reviews bind the original v4 paid outputs, not the synthetic replay or v3 attempt. This document grants nothing.
