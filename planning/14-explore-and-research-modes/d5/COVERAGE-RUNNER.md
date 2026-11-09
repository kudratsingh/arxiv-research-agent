# Runnable request-coverage development controls

**Offline implementation only. No provider authorization has been recorded.**

Application `6803cd34b90943f2c70974615e2ea51e58f02010` starts from published
`bec2a42c`. The predecessor review manifest remains unchanged at
`14e761c2bb3139428a0093caae022a175b37f81bd6ce35f5a0082367a358b101`.
The runnable packet is versioned separately as
`d5-request-coverage-development-packet-v1`. See the final binding receipt for its
exact digest, scope, source/schema/code bindings and verification.

## Scope and classification

These three cases remain **development controls**, never held-out validation:

1. `development-v8-learn-conditions`
2. `development-v8-research-retrieval`
3. `development-v8-research-insufficient`

The original sealed public contexts, task policy, requested parts and v8 local/wire
response schemas come from the predecessor. The prototype fixture equated canonical
metadata hashes with retained-text source hashes. This successor derives only
`version_hashes` and `source_version_hash` from canonical public version rows.
Every other sealed field, including passages and the three count bodies, remains
unchanged; new local input digests bind the correction. The original proposal is
preserved. See the [binding correction proof](evidence/request-coverage-runner-v4/BINDINGS.json)
and [read-only active-storage check](evidence/request-coverage-runner-v4/LIVE-READINESS-READONLY.json).
No private notes, preferences, drafts
or reading history are added. This is fixed-evidence replay, not discovery/ranking
or fresh intake. Full-paper coverage is not implied by an abstract/excerpt.

`d5_freeze.verify` and `compile_inputs` now accept this separately versioned packet.
The existing `d5_benchmark` CLI, D5 adapters, admission, contact journals,
reservations, accounting and stop rules execute it. Unique run/count principals
and a new `d5-<packet-prefix>` scope prevent reuse of old financial identities.
The frozen v8r4b packet/results/scorer and v7r2 diagnostic remain untouched.

The new profile narrows the existing shared policy:

| Stage | Identities | Funded jobs | Messages | Count contacts | New spend ceiling |
|---|---|---:|---:|---:|---:|
| A | measure-1, measure-2, measure-3 |0|0|3|USD 0|
| B, separately granted | Three named development workflows |3|12|12|USD 1.35 total /0.45 per job|
| Combined scope | A then B |3|12|15|USD 1.35|

A parent authorization may grant only A. B requires its own append-only grant and
all three successful, exact-input-bound A receipts. Each must contain one completed
count contact, a matching model/settings/schema/context body, full-generation and
count digests, a matching result and at most16,000 input tokens. Tampered/stale
receipts cannot establish fit. No historical measurements are reused. C, D, probes,
unknown cases and extra identities are rejected for this packet/profile.

The programme remains authoritative: **34 funded jobs,80 Messages,99 counts,
USD 10 cumulative,concurrency1**, expiry **2026-11-14T07:24:01Z**. It is not reset
by the new principals. The scope is pinned to the original programme authorization
and active capacity receipt. A expires at the earlier of24 hours after approval
and programme expiry. B cannot renew/extend A or the programme. Expiry/revocation,
source/project/settings/schema/producer drift, provider/contract errors, oversized
measurements, exhausted capacity or uncertain completion stop execution. No
adaptive retry, alternate request ID, model substitution or source expansion.

The full original programme chain/history audit still runs in shared admission on
each dispatch. The new layer rechecks pinned metadata/expiry and applies narrower
stage limits, without redundantly re-running that recursive audit. Profiling additionally found that each amendment validator
verified its predecessor, then immediately repeated the same recursive audit
while rebuilding the proposal. Each now passes that already-verified tuple into
a private proposal builder in the same synchronous call. No validation result
is cached across operations or transactions; the full predecessor/history/expiry/
revocation audit still executes on every admission. A regression verifies one
parent audit per validation and a fresh audit on the next validation. No timeout,
guard or floor was relaxed. Historical owner capacity receipts can be mirrored by exact digest in an
irreversibly fixture-marked database, as the earlier amendment layers already
could. Such a database categorically rejects provider mode; its synthetic grants
are never owner authorization.

## Cost and token envelope

Routes stay Sonnet5.5 for draft/repair and Opus5.5 adaptive High for check/recheck.
Output caps remain4,000 and3,200 respectively (Opus includes thinking). Counts must
fit16,000 input tokens; monetary reservations conservatively cover20,000 per call.
At the existing **ESTIMATE** prices (recorded2026-11-06, not reverified offline),
two Sonnet calls plus two Opus calls bound a job atUSD 0.448; reserve0.45. Three jobs
reserveUSD 1.35. All mandatory checks, one permitted repair and mandatory recheck
are included. Dynamic checker/repair/recheck bodies are derived from actual prior
outputs and journaled with their exact digests when created, never invented now.

Starting ledger:30 programme jobs,61 Messages,81 counts,USD 1.779493 estimated,
pending/unknown0. After A:30/61/84, same spend. A+B worst case:33/73/96,
USD 3.129493 including B's reservation; retaining the existingUSD 1 headroom gives
USD 4.129493, below10. Invalid completed content is not made ready to release money;
known charges and uncertain completion remain distinct. Pricing or request drift
requires a new reviewed binding, not a silent price/model change.

## Offline replay — safe to run with no key

Run from the new worktree root using the locked interpreter. Do not run a script
from another directory: use module mode or stdin so `src` resolves to this worktree.

```bash
cd /private/tmp/arxiv-agent-eng-workspace-coverage-runner
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export PACKET=planning/14-explore-and-research-modes/d5/evidence/request-coverage-runner-v4/packet.json.gz
"$VENV_PYTHON" -m src.workspace.d5_benchmark verify --packet "$PACKET"
```

The read-only captured snapshot is kept locally at
`outputs/d5/coverage-runner-v1/canonical-snapshot-v3.json.gz`; it contains historical financial
receipts and is deliberately not committed. Its exact digest is sealed in the
packet. Preserve it; do not recapture an advanced ledger to impersonate the sealed
baseline. Canonical public rows come from the active qualification ledger,
restricted to the same five selected source versions/materials. No source or
passage was added. The initial synthetic-metadata snapshot remains diagnostic;
it is not the live storage identity. Capturing uses read-only transactions and
checks30/61/81/USD 1.779493.

Create a **new empty** `workspace_d5_*` database on the isolated port15488;
never drop, reset or reuse a database with prior evidence. This concrete local
command fails if the name already exists; choose a fresh name in both places
rather than resetting it:

```bash
"$VENV_PYTHON" - <<'PY'
import psycopg
with psycopg.connect(
    "postgresql://workspace:workspace-local-only@127.0.0.1:15488/postgres",
    autocommit=True,
) as conn:
    conn.execute("CREATE DATABASE workspace_d5_coverage_runner_replay_new")
PY
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_coverage_runner_replay_new
"$VENV_PYTHON" -m src.workspace.d5_coverage_replay replay \
  --packet "$PACKET" \
  --snapshot outputs/d5/coverage-runner-v1/canonical-snapshot-v3.json.gz \
  --out outputs/d5/coverage-runner-v1/replay-new
```

This separate offline driver marks the empty database as a permanent fixture,
imports the original public/financial history without operative budget policies,
records a clearly synthetic A fixture through the operator recorder, runs A,
proves B refusal, then records a separate synthetic B fixture and runs B. The
runner itself never creates its authorization. The ordinary new-packet
`d5_benchmark offline` command also requires an already-recorded fixture grant;
it does not auto-grant A/B. Current UTC expiry still applies to replay. After the
programme expires, inspect saved artifacts or use explicit controlled-clock tests;
do not renew the historical approval.

Reports distinguish synthetic counts from provider measurements. Mock verdicts,
repair success and mechanically valid citations are software evidence, not model
quality or human qualification. All three are development cases; these results
cannot fill held-out or20-item human/checker-quality minimums.

## Unexecuted provider path — only after separate explicit approval

Use the **single active ledger** identified by
`outputs/d5/ACTIVE-QUALIFICATION-LEDGER.json` in the assistance checkout, currently
`workspace_d5_prose_v6_validation`. Do not initialize/reseed it or copy fixture
authority into it. Only new scope principals/project contexts may be prepared.

With the sentinel still set, the following commands have **not** been run on that
ledger:

```bash
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation
"$VENV_PYTHON" -m src.workspace.d5_operator prepare \
  --packet "$PACKET" --receipt outputs/d5/coverage-runner-v1/LIVE-PREPARE.json
"$VENV_PYTHON" -m src.workspace.d5_operator template \
  --packet "$PACKET" --stages A --receipt outputs/d5/coverage-runner-v1/A-template.json
```

Preparation checks the exact public storage, active programme and sealed history,
creates only isolated project contexts and records no authority/contact. The
operator then records the independently supplied matching A approval through:

```bash
"$VENV_PYTHON" -m src.workspace.d5_operator record \
  --packet "$PACKET" --receipt outputs/d5/coverage-runner-v1/A-owner-receipt.json
```

The template starts approved=false. Never turn a synthetic fixture receipt into
owner permission. After real A-only approval is recorded and all bindings/pricing
are rechecked, only the isolated qualification process may load the configured
credential without displaying it and execute:

```bash
# UNEXECUTED: requires the independently approved credential environment.
"$VENV_PYTHON" -m src.workspace.d5_benchmark run \
  --packet "$PACKET" --stage A --out outputs/d5/coverage-runner-v1/provider-A
```

Then stop for A review. B remains unauthorized. Its separate, append-only path is:

```bash
# UNEXECUTED: export only after A; the real parent/basis digest cannot be invented now.
"$VENV_PYTHON" -m src.workspace.d5_operator stage-template \
  --packet "$PACKET" --stages B --receipt outputs/d5/coverage-runner-v1/B-template.json
# Only after separate explicit B approval:
"$VENV_PYTHON" -m src.workspace.d5_operator grant \
  --packet "$PACKET" --receipt outputs/d5/coverage-runner-v1/B-owner-receipt.json
"$VENV_PYTHON" -m src.workspace.d5_benchmark run \
  --packet "$PACKET" --stage B --out outputs/d5/coverage-runner-v1/provider-B
```

No execution, authorization, key configuration, recurrence, notifications, merge or
deployment is performed by this handoff. Owner3137/review3178 stay untouched.
