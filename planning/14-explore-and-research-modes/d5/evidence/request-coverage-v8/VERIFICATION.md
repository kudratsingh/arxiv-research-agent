# Request-coverage v8 — offline verification

Application: `ea3a4a19ce824385bfc11a97b2018dcbe7a71b6c`. Base: `a7d4198f`. Branch: `codex/workspace-d5-request-coverage`.

Prospective, unapproved packet: **`sha256:14e761c2bb3139428a0093caae022a175b37f81bd6ce35f5a0082367a358b101`** ([manifest](proposal.json.gz)). It binds the application and current producer/source/schema/request hashes. It is a review manifest, not a stage grant or dispatchable approval.

## Local checks

| Check | Actual result |
|---|---|
| Full Python `make test-cov-diff` | 6,952 passed;54 inherited skips;53 separately run E2E deselections;94.61% total;97% patch |
| Per-package floors | API88≥86, agents96≥92, security100≥97, eval95≥91 |
| New coverage module | 198/203 statements (97.54%);67/72 branches (93.06%);97.5% patch |
| New controls + harness |77 passed|
| Full frontend |4,288 passed;98.18 statements,94.32 branches,94.14 functions,99.52 lines; unchanged floors|
| Result components + coverage presentation |56 passed|
| Ruff / strict mypy / typecheck / generated types |pass;199 source files; contract snapshot regenerated|
| Production build / budgets |pass; CSS24,868/25,600 bytes; Reader165,931/169,984; Today169,848/169,984; no ratchet|
| Workflow E2E |53 passed|
| Research simulation |20/20, USD0|
| Registry |260 objects,0 mismatches; no registry mutation|
| Documentation/hygiene |95 passed|
| Chromium |24 render/reload controls across two viewers × three dispositions × dark/light ×1440/390;0 console exceptions or serious/critical axe findings|

Browser input was explicitly synthetic and GET-only. Real persistence/ownership, HTTP422 null rejection,409 preview drift, staged checker/repair/recheck, restart/read-model and schema bindings were independently tested in disposable Postgres. Browser screenshots do not establish real semantic quality or a complete live browser-to-database journey. The mobile retrieval and desktop full-abstention captures were visually inspected; original captures remain under ignored outputs.

[Mobile comparison/coverage](screenshots/coverage-qualification-retrieval-light-390.png) · [Desktop full abstention](screenshots/coverage-assistance-safety-dark-1440.png)

## Exact prospective initial requests

| Case | Wire/request digest | Source units |
|---|---|---:|
| development-v8-learn-conditions | `sha256:219ed35921c21ad734ae83058be57fcf2cc5a69c2edccbb6a17b898d54b18ed0` | 1 |
| development-v8-research-retrieval | `sha256:b7d9c42e9d6f6a4b57e9278d6f78ae0c1b5ab0cd67e987b5eff01a5307d67d0d` | 2 |
| development-v8-research-insufficient | `sha256:62f4114656c76e3bfbd67a705e9e7393b08249437822835387389d40003f931f` | 2 |

The count body is exactly the production request projection excluding max_tokens and temperature. All three changed requests require fresh measurement; none has been submitted. Actual output-dependent checker/repair/recheck bodies will be created and journaled only from observed outputs under the bound code; no future digests are invented.

## Preservation / limits

Read-only before/after hashes match:30 programme jobs,61 Messages,81 counts,USD1.779493 estimated, pending/unknown0. Frozen packet, raw outputs, scorer, machine exports, active ledger pointer and permission-table rows match. Stage D remains ungranted/deferred. No owner3137/review3178 writes or service changes. No provider/count contacts, paid grants, new spend, human labels, merge or deployment.

The [eight-case engineering report](DEVELOPMENT-REPORT.md) retains all41 original claims and synthetic baseline findings. Seven deliberately unrepaired controls block, and the safety projection has zero claims. Manually restored qualification fixtures and mocked verdicts are not corrected provider results. Human qualification and checker reliability remain unmeasured.

## Publication / diagnostics

Local results above apply to the exact source committed as the application. The later publication commit contains evidence/status/manifest only. Exact publication-head CI is recorded separately in ignored `outputs/d5/request-coverage-v8/PUBLICATION.json` and the final handoff; local green is not remote CI.

Retained development logs include sandbox-denied loopback attempts and incorrect new-test expectations (409 status, added requested_parts, previous_prose_review). Stable corrected runs pass without lowering assertions, timeouts, coverage or budgets. An optional global format diagnostic reported328 inherited files; unrelated formatting was not changed. Repository-wide Ruff lint passes.

## Offline commands

Run from worktree root with the disabled sentinel and locked Python. Tests use `WORKSPACE_TEST_POSTGRES_URL` pointing only to disposable local test storage.

```bash
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
"$VENV_PYTHON" - < planning/14-explore-and-research-modes/d5/tools/request_coverage_report.py
"$VENV_PYTHON" - --verify planning/14-explore-and-research-modes/d5/evidence/request-coverage-v8/proposal.json.gz < planning/14-explore-and-research-modes/d5/tools/request_coverage_packet.py
```

These commands do not approve, count or generate remotely. See the [separate proposal](../../REQUEST-COVERAGE-VALIDATION-PROPOSAL.md) for the unexecuted A/B decision and remaining capacity/quality limits.
