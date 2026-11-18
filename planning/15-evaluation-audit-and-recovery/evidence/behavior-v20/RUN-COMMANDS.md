# Canonical frozen replay and later provider environment

This supplements the initial immutable runbook. The frozen packet is never regenerated. The helper uses the production runner/admission/adapter, creates a random schema only inside the existing isolated `workspace_d5_tests` database on15488, and forces MockTransport and the disabled key. Raw journals and a retention receipt are written before successful cleanup; a failure leaves its schema available for investigation.

Run from the isolated worktree root. The following offline command is the one verified for this publication; choose a new permanent output path for each run.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export WORKSPACE_TEST_POSTGRES_URL='postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests'
export PACKET_DIR=planning/15-evaluation-audit-and-recovery/evidence/behavior-v20
export NEW_PERMANENT_REPLAY_DIR="/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-behavior-v20-20261117/manual-replay-$(date -u +%Y%m%dT%H%M%SZ)"
"$VENV_PYTHON" - --packet "$PACKET_DIR/packet.json.gz" \
  --snapshot /Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-behavior-v20-20261117/READONLY-BASELINE.json.gz \
  --out "$NEW_PERMANENT_REPLAY_DIR" \
  < planning/15-evaluation-audit-and-recovery/tools/replay-frozen-behavior-v20.py
```

Do not run two fixture-based campaign checks concurrently against the same test database: programme advisory locks are database-wide across schemas. A schema is dropped only after a readable raw-journal export; originals and output evidence remain permanently. `RESULTS.json.gz`, `REPORT.md`, `REPORT.html`, exact input bindings, synthetic grant, raw journals and retention/cleanup receipts are the deliverables. Synthetic counts and opinions establish no actual provider token fit or factual quality.

The provider commands in RUNBOOK.md remain unexecuted and conditional on a new exact owner decision and resolution of required CI. Use a separate approved process/environment. Do not reuse the fixture URL, marker, synthetic authorization or disabled key as live authority. In that separately approved process, clear `WORKSPACE_D5_OFFLINE` and supply the private active validation URL and configured credential without displaying it. This does not enable everyday generation.

```sh
# ONLY AFTER the exact external approval and required gates:
unset WORKSPACE_D5_OFFLINE
: "${D5_POSTGRES_URL:?private approved validation URL required}"
: "${ANTHROPIC_API_KEY:?approved provider credential environment required}"
# Then use the exact operator record/run commands from RUNBOOK.md.
```

The runner performs automatic exact count → fit check → Message within the approved ten-case scope. There is no separate preliminary count-only stage. The stopped v19 scope and every earlier grant remain stopped/expired; no financial or expiry adjustment is authorized by these examples.
