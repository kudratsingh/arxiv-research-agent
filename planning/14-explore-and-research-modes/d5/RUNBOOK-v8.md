# D5 v8 offline repair and premise calibration runbook

Current calibration entry point: [independent-review preflight](CALIBRATION-PREFLIGHT.md). A prereview digest alone is insufficient. Four supplied attributed reviews now validate; the actual preflight is READY_FOR_APPROVAL with approved=false. No live grant is recorded.

No paid execution or authorization is performed by these commands. Work from the
isolated `codex/workspace-d5-procedural-v8` checkout. Preserve the active stopped
ledger and owner3137/review3178; all test writes use disposable schemas/databases.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace: workspace-local-only@127.0.0.1: 15488/workspace_d5_tests
$VENV_PYTHON -c 'import src; print(src.__file__)'
$VENV_PYTHON -m pytest -q tests/test_workspace_d5_procedural_intents.py tests/test_calibration_question_premises.py
make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
make test-e2e VENV_PYTHON="$VENV_PYTHON"
make simulate-research VENV_PYTHON="$VENV_PYTHON"
$VENV_PYTHON -m src.contracts.registry parity
```

To build a fresh blinded suite offline, generate an evaluator-only salt in an
ignored local file with mode0600. Do not print or commit it or the evaluator key.
The checked-in test salts are explicitly synthetic, never live blinding keys.
Choose a new output directory and preserve the original packet:

```sh
# Keep fresh calibration and regressions separate. This prepares one fresh set.
$VENV_PYTHON - <<'PYCODE'
from pathlib import Path
from src.workspace.d5_benchmark import read, write
seeds = read(Path("tests/fixtures/d5/question-premises/seeds.json.gz"))["seeds"]
fresh = [s for s in seeds if s["cohort"] == "fresh_calibration"]
write(Path("outputs/d5/premise-calibration/smallest-seeds.json"), {"seeds": fresh[: 1]})
PYCODE
$VENV_PYTHON -m src.calibration.question_premises build \
  --seeds outputs/d5/premise-calibration/smallest-seeds.json \
  --seed 7319 --salt-file outputs/d5/premise-calibration/evaluator-salt.txt \
  --out outputs/d5/premise-calibration/rebuilt-new
# Reviewer labels the exported worksheet BEFORE seeing checker results.
# Score only supplied recorded responses and input-bound attributed reviews:
$VENV_PYTHON -m src.calibration.question_premises score \
  --packet outputs/d5/premise-calibration/rebuilt-new/packet.json.gz \
  --responses outputs/d5/premise-calibration/responses.json \
  --reviews outputs/d5/premise-calibration/reviewer-completed.json \
  --out outputs/d5/premise-calibration/rescored-new.json
```

The build command contains no provider or approval path. Scoring makes no DB or
provider write. Actual worksheet labels remain blank; synthetic scoring reports
are demonstrations only. The production-probe tests use the same protected
D5 request/admission/accounting path with MockTransport and a permanent offline
fixture marker. They do not establish real token fit or checker reliability.

[Premise calibration plan](QUESTION-PREMISE-CALIBRATION.md) describes the
smallest4-probe proposal and independent review. [Fresh full qualification
proposal](PAID-VALIDATION-PROPOSAL-v8.md) is separate and needs larger job/count
caps to guarantee its complete worst-case schedule. Neither authorizes execution.
No old A count establishes fit for changed requests. Every future contact must
bind the exact body/model/settings/schema/source/producer and use its exact
paired count. No blind retry, alternate request identity or source expansion.

Freeze/export the fresh generation cohort only in a **new empty** named D5 DB:

```sh
# D5_POSTGRES_URL must name a newly created disposable workspace_d5_* database
# on the isolated15488 service; never the active validation ledger.
$VENV_PYTHON - --snapshot planning/14-explore-and-research-modes/d5/d5-replay-inputs-v8.json.gz \
  --packet outputs/d5/procedural-v8/new-packet.json.gz \
  --out outputs/d5/procedural-v8/new-freeze \
  < planning/14-explore-and-research-modes/d5/tools/prepare-procedural-v8.py
```

This freezes new question/source partitions before outputs; it creates no
operative authorization. Larger cap policy support and external approval remain
prerequisites for any complete new paid qualification schedule. Current v7r2
remains stopped at 3/8, including all original failures, receipts and human blanks.

The private evaluator key is an annotation proposal only. Never copy its values
into the real blank reviewer worksheet. For error-direction software evidence,
use the clearly labelled synthetic test/demo results, which keep qualification
on HOLD. The actual paid-calibration proposal binds exactly four fresh opaque IDs
and requires independently recorded prereviews and a new external scope. No
approval, cap amendment or dispatch is created by exporting these files.
