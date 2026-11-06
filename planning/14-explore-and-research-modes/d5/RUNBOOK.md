# D5 reproducible offline benchmark and local walkthrough

Run from `/private/tmp/arxiv-agent-eng-workspace-assistance`, using Python stdin/`-m`/`-c` so `import src` resolves here. Owner3137 and review3178 are unrelated: do not run everyday-owner launch/stop scripts. This runbook never authorizes provider/count calls, recurrence or paid generation.

## Open the prepared preview

**http://localhost:3193/workspace/today?mode=learn** — API8193, Postgres15488, DB`workspace_d5_review_offline`, principal`d5-validation-run`. Copied real retained public data; experimental questions/projects and outputs are labelled. No fresh intake occurred. The disabled key and `WORKSPACE_D5_OFFLINE=1` are enforced by the preview launcher.

1. Open the [learning result](http://localhost:3193/workspace/items/arxiv%3A2610.40927?mode=learn&version=arxiv%3A2610.40927%3Av1%3Ametadata-b09108e19893972e&qualification=gen-c53129994190d2a96ad02bb8a2dd2dc219188778#understand). Under **Understand**, inspect **Experimental reading results**. It is a persisted, quarantined offline result, not a qualified summary. Inspect the claim, simulated checker abstention, source scope and exact citation disclosure.
2. **Open qualification passage** opens the exact retained abstract range. Return to Understand; **Save experimental learning thread** explicitly saves the shared note/thread. **Open experimental learning thread → Resume saved assistance** returns to the same result. Reload reads it without dispatching.
3. Open the [two-source Research result](http://localhost:3193/workspace/items/arxiv%3A2610.40966?mode=research&version=arxiv%3A2610.40966%3Av1%3Ametadata-55c0a56c8750035c&qualification=gen-841de0350cf216441ca7872fc35c0978c5afb3a2&project=project-37e7c1c6eb4ddc27b857078580b52dd7#understand). Its machine-authored project question and separately cited sources are visible. Comparison compatibility and omissions require review. **Link experimental result to project** is explicit and retry-safe.
4. Library → Notes → **Resume this question** opens the exact source/version/passage. **Your notes → Resume saved assistance** opens the original result. The note/project/thread share Library records rather than copying source identities. Reading entries in this isolated preview are verification examples, not owner-authored notes.
5. For retained PDF text, use the [development ReAct comparison](http://localhost:3193/workspace/items/arxiv%3A2210.03629?mode=research&version=arxiv%3A2210.03629%3Av3&qualification=gen-82b685cacb449f373b1a1ddfa994dd2e996c5ec8&project=project-d323fc7f292539ea490d65421aa0ea75#understand). Its PDF excerpts are partial and contain extraction warnings.

Both desktop1440×1000 and mobile390×844, light/dark, are captured in [evidence](evidence/README.md). All assistance remains visibly simulated/experimental. Opening a panel, changing mode or previewing a request never dispatches a provider.

## Replay from frozen inputs into new disposable storage

The checked-in snapshot contains public works/materials, a redacted saved-interest profile and historical financial records. It excludes owner notes/drafts/history/private question text, credentials and operative budget policies. Install it only into a **new** isolated D5 DB. The offline marker permanently forbids provider mode there. Choose another new D5-prefixed DB/report directory on subsequent runs; never delete or replace existing storage to make a rerun pass.

```sh
cd /private/tmp/arxiv-agent-eng-workspace-assistance
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export PACKET=planning/14-explore-and-research-modes/d5/d5-system-validation-v3.json.gz
export SNAPSHOT=planning/14-explore-and-research-modes/d5/d5-replay-inputs-v1.json.gz
$VENV_PYTHON -c 'import pathlib,src; print(pathlib.Path(src.__file__).resolve())'
$VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
docker compose -p arxiv-d5-20261105 -f scripts/workspace-d5-compose.yml up -d postgres
docker compose -p arxiv-d5-20261105 -f scripts/workspace-d5-compose.yml exec -T postgres psql -U workspace -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE workspace_d5_owner_offline;'
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_owner_offline
$VENV_PYTHON -m src.workspace.d5_benchmark init --packet "$PACKET" --snapshot "$SNAPSHOT" --offline-fixture
$VENV_PYTHON -m src.workspace.d5_benchmark offline --packet "$PACKET" --out outputs/d5/owner-offline
```

`offline` runs the real ranking/selection → sealed request → scoped admission → production adapter with injected MockTransport → draft/check/repair/recheck → persisted result → scoring/accounting/Markdown/HTML. Synthetic authorization is confined to the marked disposable fixture DB; it cannot be copied into provider validation. The current observed v3 result is [published compressed](evidence/review-grading/frozen-results-v3.json.gz); the v2 predecessor stays at its original path. Dynamic stage requests are journalled from actual preceding fixture outputs under the frozen template; their digests are not fabricated ahead of time.

To inspect stored results without rerunning after project/note edits:

```sh
$VENV_PYTHON -m src.workspace.d5_benchmark report --packet "$PACKET" --out outputs/d5/owner-readonly-report
```

Source/project/producer drift can intentionally refuse execution/cached reuse. It never falls back to different evidence. Failed/uncertain identities must not be repeated under new IDs.

## Start, inspect and safely restart the preview

The final frontend must be built (`npm --prefix web run build`). The launcher copies it into a build-ID-specific immutable runtime, forces the sentinel and disables recurrence/redriver. Its 0600 local API key is never committed. It refuses occupied ports and validates PID and worktree/runtime cwd before stopping only its own processes. Use port3193 only for the prepared DB, or another allowed3194–3199 for a new offline replay DB; API is port+5000.

```sh
$VENV_PYTHON - status --port 3193 < scripts/workspace-d5-preview.py
# Stop ONLY this owned D5 API/web pair; preserve Postgres and all data:
$VENV_PYTHON - stop --port 3193 < scripts/workspace-d5-preview.py
# Once its listeners have exited:
$VENV_PYTHON - run --port 3193 --database workspace_d5_review_offline < scripts/workspace-d5-preview.py
```

No worker/recurring job starts. An actual API/web restart preserved29 jobs,2 saved notes,1 learning thread,10 projects,3 reading records and29 reservations, followed by browser Library/result resume on desktop/mobile. Owner3137 and review3178 listeners were checked unchanged. Broader browser-history recovery for unsaved drafts remains the inherited limitation.

## Reproduce verification

```sh
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
make test-e2e VENV_PYTHON="$VENV_PYTHON"
make simulate-research VENV_PYTHON="$VENV_PYTHON"
$VENV_PYTHON -m src.contracts.registry parity
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test -- --run --coverage
npm --prefix web run build
node web/scripts/route-budgets.mjs
D5_BROWSER_REPORT=outputs/d5/benchmark-review-v3/results.json D5_BROWSER_OUT=outputs/d5/browser-new-run NODE_PATH=$PWD/web/node_modules node planning/14-explore-and-research-modes/d5/tools/protected-browser.cjs
```

Browser replay intentionally writes only to the prepared isolated verification principal. Set up a fresh fixture DB/preview for a clean-state run. The unchanged16-case live suite uses a separate exact three-work/four-version CI seed on3190/API8190; it is not the40-work benchmark or owner data. Check `web/package.json` for script spellings and [exact gate logs](evidence/checks/) for actual invocations/results.

## Paid execution remains separate

See [the unexecuted proposal](PAID-VALIDATION-PROPOSAL.md) for exact operator authorization and A/B/C/D commands. The prepared `workspace_d5_review_validation` DB is unmarked, unapproved and contains only the public context plus preserved financial history. A-only approval permits4 named count requests and no Messages. Later funded stages need a separate owner-approved append-only grant unless explicitly included in the original approval. The runner cannot authorize itself. No real key was inspected in this batch.

## Human-review analysis

Use [the review runbook](HUMAN-REVIEW-RUNBOOK.md) for the actual export/validate/import/score commands. Import is filesystem-only, versioned and bound to the original result; it does not edit the Reader job, ledger or approvals. The [synthetic demonstration](evidence/review-grading/README.md) leaves the real worksheet blank. Prior v2 runs can be explicitly rescored with a new-scorer analysis receipt; passing v2 results to a v3 packet is refused.
