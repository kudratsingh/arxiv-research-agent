# Evaluation recovery and implementation plan

Finish a credible machine-only evaluation of the daily research workspace with one focused offline batch and one consolidated execution decision. Keep the original-agent correctness repairs moving separately so unrelated legacy work does not delay the workspace diagnostic.

The destination remains a useful personal application: Explore and Learn for daily discovery, Research for project questions, and grounded summaries and guided dives connected to the Reader, saved questions and exact sources.

## Workstream order

| Order | Work order | Purpose | Blocks |
| --- | --- | --- | --- |
| 1 | W0 Verify permanent evidence | Establish which originals are already preserved and fill only real gaps | Destructive cleanup or retirement of old locations |
| 2 | W1 Bind reports to the checked response | Remove stale current-response assessments | Trusting D5 reports and the refreshed campaign |
| 3 | W2 Freeze answerability and scoring | Separate retrieval gaps, appropriate abstention and answer failures | Interpreting the next campaign |
| 4 | W3 Complete offline verification and final freeze | Deliver one concrete execution package | Paid campaign approval |
| 5 | W4 Execute approved diagnostic | Obtain complete case-level machine evidence | Decisions about further generation investment |
| 6 | W5 Product walkthrough and real-day pilot | Establish usability and daily value beyond the snapshot harness | Claiming daily-use readiness |
| Separate track | L1 and L2 Original-agent corrections | Make original-agent metrics and completion semantics honest | Trusting original LangGraph evaluations |
| Supporting work | E1 Runtime and test isolation | Make evidence reproducible across local and CI | Claims requiring runtime parity |

W0–W3 are the next implementation batch. Run focused regressions while editing and one complete final gate on the final source. Repeat broad testing when new changes or failures justify it, rather than regenerating the whole documentation chain for every small correction.

## W0 Verify existing preservation before copying

Start with the two current permanent archives and their manifests. The campaign worktree has already moved to arxiv-workspaces. Do not perform another blanket relocation.

Deliverables:

- An inventory linking each required original receipt, frozen packet, failed response, source snapshot, reviewer export, report and verification artifact to a permanent copy and checksum.
- A reconciliation of the earlier at-risk inventory with existing copies. Mark missing originals, missing copies, mismatches and unresolved coverage explicitly.
- Retained branch heads and raw-output locations as separate categories; a Git commit is not a backup of ignored outputs.
- Copies of missing required evidence only, preserving originals and original-to-durable mappings.

Acceptance:

1. Required originals have verified durable copies, or an explicit unresolved inventory entry.
2. Originals and historical financial/scope records remain unchanged.
3. Any future teardown can identify its protected evidence before proceeding.
4. Manifest counters are not presented as an independent rehash unless that rehash actually ran.

This work does not alter the live ledger or settle the uncertain request.

## W1 Repair the D5 checker report binding

Address AUD 01 in the report and its tests. Do not weaken executor acceptance.

Bind current machine assessments to:

- The exact selected draft or repair.
- The current factual claims and selected evidence.
- The current coverage, sections and remaining prose.
- The correct completed checker contact following that response.

Prefer existing canonical request/context identities and journal order over a new parallel identity system. Recompute the expected checked context from the selected response where necessary.

Required controls:

| Control | Expected report |
| --- | --- |
| Draft with its completed, bound checker | Current assessments available |
| Coverage-only repair with identical claims; recheck uncertain | Current assessments unavailable; completion false |
| Prose-only or section-only repair; no completed recheck | Current assessments unavailable |
| Claim or evidence change after check | Earlier verdict cannot assess the changed content |
| Completed recheck bound to the latest response | Latest assessments available |
| Malformed, missing, duplicated or out-of-order checker binding | Explicit unscored/binding-error state; no quality pass |

Previous verdicts may appear as clearly historical annotations. They must not be presented as judgments on the current response. Store recomputed historical reports as versioned derivatives; do not overwrite their raw inputs or original reports.

Acceptance: the exact coverage-only reproduction in AUD 01 fails to acquire current machine judgments, while valid draft/check and repair/recheck controls continue to report correctly.

## W2 Freeze per-part answerability and the prospective rubric

Create one matrix for the eight current evaluation cases and their three sealed requested parts. Each row records:

- Exact case, requested part, source versions and retained scope.
- Answerability: answerable, partially answerable or insufficient.
- The retained support and the missing information.
- Expected behavior: answer, bounded partial answer, comparison-only abstention or full application abstention.
- Whether the limitation originates in corpus coverage, ranking, selection, extraction or available text.
- Machine-reference author/method, timestamp and locked matrix digest.

Keep reference judgments hidden from live producer/checker payloads when they serve as evaluation labels. The owner can review the matrix, but human qualification is not a required gate.

In particular:

1. A missing common benchmark must not become a fabricated performance comparison.
2. Faithful comparison abstention can be correct grounding behavior while the research request remains unmet.
3. A source containing an answer that the model omitted is different from missing evidence.
4. Missing vehicle context requires full abstention without background claim sections.
5. A reproducibility question may support only a high-level outline from an abstract; absent protocol details remain absent.

Report separate axes rather than hiding them in one pass bit:

| Axis | Question |
| --- | --- |
| Execution | Did the intended pipeline complete under the bound controls? |
| Retrieval and evidence | Did the system select material capable of answering the question? |
| Support and qualifications | Are factual statements supported within their cited scope? |
| Coverage | Which requested parts were answered, omitted or unsupported? |
| Abstention | Was refusal or partial answering appropriate to the frozen evidence? |
| Checker diagnostic | How did the checker perform against locked machine controls? |
| Product usefulness | Did the result help the owner's actual research task? |

Version any prospective rubric change. Preserve the old v7r2, v8r4b and development outcomes, and show any new reanalysis beside its original score rather than replacing it.

Do not handpick better reference papers into the end-to-end selection. Fixed-evidence development controls can test successful comparison separately. Keep the eight-case denominator, the twenty generated-claim evidence minimum and the twenty-probe minimum visible. If the evidence does not support enough facts, report HOLD instead of generating filler.

Acceptance: every part has a locked expected behavior before execution; honest abstention and unmet research needs can be seen separately; no exposed case is relabelled as fresh independent held-out evidence.

## W3 Verify once and prepare one approval package

Use a permanent isolated worktree. Verify the exact interpreter, working directory and imported source path. Add the focused W1 and W2 controls, preserve production-adapter mocked replay, then run the required full gate and exact-head CI.

Record Python version, executable and critical dependency versions with the verification evidence. Keep fixture lifetime controls explicit; avoid adding gateway tests inside the module-scoped campaign-client patch.

Future provider receipts should distinguish dispatch, first response byte, full response and timeout/cancellation times, using elapsed time for duration and UTC for correlation. Do not invent timings for old contacts. Timing changes should remain small and be included in the same source freeze where practical.

The final handoff contains:

- Final source head, runtime producer and packet/schema/source bindings.
- W1 regression evidence and the W2 answerability/rubric identity.
- Preservation status and the actual latest financial census.
- Exact-head CI conclusion, including configured skips.
- One proposed owner authorization covering capacity, the precise historical uncertainty policy, automatic paired counts, permitted generation/checking and bounded repair.
- Per-case order, limits, automatic progression and hard stops.

No grant or amendment is activated by preparing these artifacts. A source or scoring change invalidates a previous freeze where it affects its bindings; do not approve a superseded packet.

## W4 Execute one bounded campaign after approval

Retain the consolidated shape unless the owner chooses a different scope:

| Component | Jobs | Maximum Messages | Maximum paired counts | New reservation cap |
| --- | ---: | ---: | ---: | ---: |
| Learn and comparison development | 2 | 8 | 8 | $0.90 |
| Eight exposed-corpus evaluations | 8 | 32 | 32 | $3.60 |
| Four checker-control batches | 4 | 4 | 4 | $0.60 |
| **Total new** | **14** | **44** | **44** | **$5.10** |

Against the captured baseline this reaches 47 programme jobs, 109 Messages and 134 counts. Those are proposed capacity limits, not the existing activated limits of 34, 80 and 99.

Budget arithmetic:

| Item | Amount |
| --- | ---: |
| Known historical estimated usage | $1.853811 |
| One retained historical hold | $0.425066 |
| Maximum new campaign reservation | $5.10 |
| Existing buffer | $1.00 |
| **Total conservative planning exposure** | **$8.378877** |

Keep $10 as the current spending ceiling. The owner is willing to reconsider it when it becomes a practical constraint. Bring one consolidated adjustment with completed results, remaining work and maximum cost before exceeding approved capacity or spend. Do not repeatedly shrink the benchmark to avoid that decision.

Execution rules:

- One approval can cover the frozen sequence and its conditional progression. Automatic paired count → fit check → Messages dispatch stays inside that approved scope.
- Every Messages request requires its exact measured count, at or below 16,000 input tokens. No separate preliminary-count handoff is necessary in this prospective consolidated scope.
- Preserve sealed Sonnet draft/repair and Opus High check/recheck settings, current output limits, one repair and mandatory recheck, and the implemented bounded deadlines.
- Fully metered content rejection remains a failed result and can allow unrelated cases to continue under the approved policy.
- Stop for binding or accounting corruption, exhausted limits, expiry/revocation, cancellation, provider errors or any new uncertain completion.
- No automatic retry, replacement identity, adaptive case expansion, mid-cohort tuning or replay of a historical failure into a pass.

The historical $0.425066 exception requires explicit approval and remains an admission policy decision, not financial settlement or proof of remote cancellation. Preserve its original state and hold. Never apply it to a new uncertain contact.

The recorded programme expires at 2026-11-14T07:24:01Z. If it is no longer valid when execution is considered, obtain a reviewed prospective authorization preserving the old programme history. Do not silently extend expired authority or reset its counters.

Acceptance: return all fourteen outcomes, including failures and unrun cases, per-part coverage, claim support, qualification/atomicity findings, checker error denominators, timings and reconciled spend. Distinguish machine-only diagnostic results from general scientific validation.

## W5 Validate the product and actual daily use

After the diagnostic, show accepted or clearly quarantined results in an isolated workspace:

1. Today or Radar → selected paper → Reader.
2. Inspect retained source scope, grounded output and unavailable portions.
3. Open an exact source/version/passage.
4. Save a question or next action; reload and resume through Library or Research.
5. Complete the same journey at desktop and 390-pixel mobile width.

Use controlled data for failure/recovery checks and retained public sources for the content walkthrough. Label simulations and experimental model outputs.

Then observe an initial five distinct actual-use dates, with editable owner interests and research questions. Record useful discoveries, time spent, missed topics, saved follow-ups, dead-end reading, source gaps and generation cost. A mechanical session replay does not count as a day of use. This initial checkpoint does not satisfy any separate fourteen-day pilot requirement.

Fresh intake, scientific full-text qualification, guided dives and ordinary daily generation each need the relevant operational and spending scope. Evaluation approval does not enable recurrence, notifications or everyday generation.

## L1 Repair original-agent measurement and source identity

Run this track separately from workspace campaign preparation.

For AUD 02, make citation resolution explicitly an identity diagnostic and select a versioned semantic primary metric when actual support judgments exist. A false claim with a valid citation must not receive a factual-support pass. Missing judgments remain missing; ten assertions cannot silently become one measured assertion because they share a citation.

For AUD 03, use canonical identity joins with version-safe evidence binding. Test full URL, bare ID, prefixed ID, matching version and ambiguous/mismatching version controls.

Acceptance: the audit's fabricated-claim and normalized-ID reproductions no longer produce misleading factual results or silently empty dossiers. Preserve historical metrics under their original definitions.

## L2 Repair original-agent termination and judge coverage

For AUD 04, separate completed, iteration-exhausted, verification-failed and quality-accepted outcomes. A score-zero final pass must not say approved simply because revision capacity is exhausted.

For AUD 05, account for terminal stop reasons in synthesis acceptance. Test malformed truncation and valid JSON returned with max_tokens; preserve legitimate intermediate tool behavior.

For AUD 06, expose how much of the original report was extracted and judged. Do not interpret support among a returned subset as coverage of the entire report.

These repairs need their own original-graph integration tests. Workspace adapter success is not a substitute, and any future original-agent live baseline requires its own scope.

## E1 Maintain runtime and test isolation

Record the local Python 3.13.7 versus CI Python 3.14 difference until an actual parity test resolves it. Test under the intended locked environment and report the exact imported source. Do not reinstall or alter another worker's shared interpreter.

The campaign-client fixture should not conceal new gateway integration tests. A test must be meaningful in isolation and in the required full suite.

## Scope of this planning package

Creating these documents authorizes no provider calls, grant or cap changes, financial reconciliation, source repair, merge or deployment. The [starting message](04-coding-agent-start.md), when assigned by the owner, defines the next offline implementation batch. It requires one subsequent concrete approval for live execution.

All rights reserved. No license or reuse permission is granted.
