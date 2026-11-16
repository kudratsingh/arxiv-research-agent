# Executable local offline setup

This replays the existing public packet. It does not freeze, reseal, contact a provider or create provider authority. The public template stays false with expiry unset. Run in a new offline shell; the disabled sentinel below is not a real key.

```sh
cd /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-comparison-v19
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PACKET_DIR="$PWD/planning/15-evaluation-audit-and-recovery/evidence/comparison-v19"
export EXACT_PRESERVED_SNAPSHOT=/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/provider-compat-live-v18-20261116T072641Z/READONLY-POST-RUN.json.gz
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
export PYTHONPATH=/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps${PYTHONPATH:+:$PYTHONPATH}
export PYTHONDONTWRITEBYTECODE=1
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export NEW_PERMANENT_PRIVATE_REPLAY_DIR="/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-comparison-v19-20261116/campaign/offline-replay-$(date -u +%Y%m%dT%H%M%SZ)"
"$VENV_PYTHON" - <<'PYCODE'
import hashlib, json, os
from pathlib import Path
import src
from src.workspace.d5_benchmark import read
from src.workspace.d5_freeze import verify
assert Path(src.__file__).resolve() == Path.cwd() / "src/__init__.py"
package = Path(os.environ["PACKET_DIR"])
identity = read(package / "IDENTITY.json")
packet = read(package / "packet.json.gz")
assert packet["application_commit"] == "b1bad909b112c246b678c0194325ae974e4284bf"
assert packet["packet_digest"] == identity["packet_digest"] == "00cc2c78e66fcc58c16a5afcf24db3c5177b6a8940ef2638c07a841edeacf48d"
assert hashlib.sha256((package / "packet.json.gz").read_bytes()).hexdigest() == identity["packet_file_sha256"]
assert packet["approved"] is False
verify(packet)
print("Frozen source and packet identity verified; no authorization or contact created")
PYCODE
"$VENV_PYTHON" - < planning/15-evaluation-audit-and-recovery/tools/replay-frozen-comparison-v19.py \
  --packet "$PACKET_DIR/packet.json.gz" \
  --snapshot "$EXACT_PRESERVED_SNAPSHOT" \
  --out "$NEW_PERMANENT_PRIVATE_REPLAY_DIR"
"$VENV_PYTHON" -m pytest -q tests/test_workspace_d5_comparison_artifacts.py
```

The helper requires the explicitly disposable workspace_d5_tests database, creates a unique schema, installs the exact preserved snapshot with an offline marker and records only a synthetic fixture grant. It refuses provider authority there. The output directory must be new; if the timestamp already exists, choose a new timestamp rather than overwrite anything. Existing final-freeze-008, frozen-final-008 and all earlier attempts remain immutable. The snapshot contains private accounting/authorization data: do not copy it, fixture grants or raw journals into the public package.

Full replay exercises fourteen identities with maximum repair, 44 Messages and 44 exact paired counts, then checks duplicate dispatch 0. Counts/usage/judgments are synthetic; remote schema acceptance, token fit and scientific or human quality remain unmeasured. An invalid first draft is terminal and is never repaired or replaced. Repair is only available after a locally valid draft and a complete bound checker response; it is capped at one and must be rechecked. Broken development contracts stop before evaluation/probes; complete valid negative quality remains failed content and can permit an unrelated next identity.

Use a **separate fresh provider shell only after the exact explicit owner decision** in APPROVAL-DECISION.md, bounded private receipt recording and baseline revalidation. Do not execute provider record/run commands now. The live command syntax in RUNBOOK.md is conditional on that later decision and requires private D5_POSTGRES_URL and owner-configured credentials. No real key value belongs in any command argument, chat or public artifact.

All rights reserved.
