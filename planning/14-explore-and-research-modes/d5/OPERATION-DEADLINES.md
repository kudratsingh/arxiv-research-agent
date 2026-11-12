# Offline operation-deadline repair

Application `92c5a9eafa81bbaa279a5b44312f1519a1bd522c`, branch
`codex/workspace-d5-operation-deadlines`, from publication
`e046fba8ec023e65a55378881a9fc7057cf2b27f`. This revision does not dispatch,
reconcile accounting, renew authority or resume v10. Human qualification is out
of scope. [Preserved uncertainty and resolution options](UNCERTAINTY-RESOLUTION.md),
[blocked one-case proposal](OPERATION-DEADLINES-PROPOSAL.md),
[sealed identity](evidence/operation-deadlines-v11/IDENTITY.json).

## Policy and implementation

| Operation | Legacy deadline | New sealed deadline |
| --- | ---: | ---: |
| Token count | 30 s | 30 s |
| Sonnet draft / repair | 30 s | 30 s each |
| Opus High check / recheck | 30 s | 120 s each |
| Whole workflow | Historical behavior retained | 480 s from durable reservation creation |

`d5_deadlines.py` validates the complete versioned policy. It is part of the
sealed input, packet and producer hashes. The request body, models, effort,
source selection, schemas, quality checks, token caps, prices and repair count
are unchanged. Inputs without the new policy retain their scalar deadline and
historical replay behavior.

The provider adapter supplies the same effective timeout to its asyncio bound
and HTTP client. It journals that timeout before dispatch. Every operation is
also capped by the remaining workflow time. The 480-second horizon covers four
30-second counts, two 30-second draft/repair calls and two 120-second checker
calls (420 seconds), with 60 seconds for local work. It starts at the persisted,
timezone-aware reservation timestamp and survives adapter/service restart.
Missing, naive or future timestamps refuse; elapsed time is not reset on resume.
This is a wall-clock bound: backward clock movement before the origin refuses;
it does not establish immunity to arbitrary OS clock changes or stalled processes.

Expiry/revocation/cancellation checks, exact paired counts, reservations and
unknown-liability guards remain in the production adapter. A request dispatched
without a complete validated receipt remains uncertain after timeout. Cancelling
the local task does not prove upstream cancellation. A response after authority
or workflow expiry cannot silently become an accepted result. No automatic
retry, alternate job identity or duplicate dispatch is introduced.

The operator now refuses an unresolved ledger before preparing project context,
as well as the existing refusal when recording authorization. The prospective
packet retains the real hold and sets `reconciliation_required=true`.

## Offline verification commands

Run from this worktree root. No real key is loaded:

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-calibration-preflight-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
"$VENV_PYTHON" -c 'import src; print(src.__file__)'
"$VENV_PYTHON" -m pytest -q tests/test_workspace_d5_deadlines.py tests/test_workspace_timeout_packet.py --no-cov
make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
```

Tests use disposable Postgres schemas and the actual production adapter with
MockTransport. Controlled virtual time advances inside the transport; there are
no long sleeps or test-timeout increases. A 31-second checker completes under
120 seconds and fails under legacy 30 seconds. A 121-second checker, cancellation,
expiry and process loss retain uncertainty and the synthetic reservation across
restart. An almost-expired workflow limits a new check to five seconds. The
four-stage repair/recheck path records operation deadlines 30/120/30/120, each
preceded by a 30-second paired count. Duplicate starts and uncertain restarts
cannot send another request.

The tests demonstrate transport and accounting controls, not real Opus latency,
token fit, quality or checker qualification. Synthetic usage and verdicts never
become owner labels or historical provider evidence.

Read-only census and packet verification (the capture command refuses any
baseline other than the preserved uncertain checkpoint):

```sh
export D5_LEDGER_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation
"$VENV_PYTHON" -m src.workspace.d5_timeout_packet --capture \
  --snapshot outputs/d5/operation-deadlines-v11/SNAPSHOT-CURRENT.json.gz
"$VENV_PYTHON" -c 'from pathlib import Path; from src.workspace.d5_benchmark import read; from src.workspace.d5_freeze import verify; verify(read(Path("planning/14-explore-and-research-modes/d5/evidence/operation-deadlines-v11/packet.json.gz"))); print("verified, blocked")'
```

Do not run operator `prepare`, record a grant, migrate the live ledger or execute
qualification. The packet is a review artifact while the hold is unresolved.
Regenerating it at another application head produces another identity.

## Evidence and publication

[Verification record](evidence/operation-deadlines-v11/VERIFICATION.md) distinguishes
the application from the publication and exact-head CI. Detailed local logs stay
under `outputs/d5/operation-deadlines-v11/`. Owner3137, review3178, the original
v10 artifacts and ledger pointer remain untouched. Everyday generation,
recurrence and notifications stay disabled; no PR, merge or deployment.
