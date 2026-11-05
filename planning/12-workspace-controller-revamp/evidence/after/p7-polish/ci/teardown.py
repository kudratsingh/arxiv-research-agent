"""Remove only this receipt-owned disposable CI stack after exact PID/DB guards."""

import datetime
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

import psycopg
from psycopg import sql

root = Path("planning/12-workspace-controller-revamp/evidence/after/p7-polish")
out = root / "ci"
meta = json.loads((out / "setup.json").read_text())
assert meta["database"] == "workspace_controller_p7_ci" and meta["principal"] == "controller-p7-ci"


def listeners(port):
    p = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpcn"], capture_output=True, text=True
    )
    return p.stdout


report = {
    "startedAtUtc": datetime.datetime.now(datetime.UTC).isoformat(),
    "database": meta["database"],
    "principal": meta["principal"],
    "ownedRunId": meta["runId"],
    "before": {
        str(p): listeners(p)
        for p in [3137, 8137, 3148, 8148, 3158, 8158, 3168, 8168, 3169, 8169, 15438, 15458]
    },
    "stopped": [],
}
with urllib.request.urlopen("http://127.0.0.1:3169/api/workspace/state") as response:
    state = json.load(response)
assert (
    state["principal_key_id"] == meta["principal"]
    and len(state["works"]) == 3
    and all(w["work_id"].startswith("ci:workspace-") for w in state["works"])
    and not state["schedule"]["enabled"]
)
(out / "final-owned-state.json").write_text(json.dumps(state, indent=2) + "\n")
for port, pid, comm in [(3169, 82833, "node"), (8169, 10951, "Python")]:
    raw = listeners(port)
    assert f"p{pid}\n" in raw and f"c{comm}\n" in raw, (port, raw)
    os.kill(pid, signal.SIGTERM)
    report["stopped"].append({"port": port, "pid": pid, "verifiedListener": raw})
    for _ in range(100):
        if not listeners(port):
            break
        time.sleep(0.1)
    assert not listeners(port), f"Own port{port} still listening"
admin = "postgresql://workspace:workspace-local-only@127.0.0.1:15458/postgres"
with psycopg.connect(admin, autocommit=True) as conn:
    row = conn.execute(
        "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s",
        (meta["database"],),
    ).fetchone()
    assert row and row[0] == meta["runId"], row
    connections = conn.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (meta["database"],)
    ).fetchone()[0]
    assert connections == 0, connections
    report["databaseOwnershipCommentVerified"] = row[0]
    report["databaseConnectionsBeforeDrop"] = connections
    conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(meta["database"])))
    assert not conn.execute(
        "SELECT 1 FROM pg_database WHERE datname=%s", (meta["database"],)
    ).fetchone()
    report["databaseDropped"] = True
report["after"] = {
    str(p): listeners(p)
    for p in [3137, 8137, 3148, 8148, 3158, 8158, 3168, 8168, 3169, 8169, 15438, 15458]
}
for port in [3137, 8137, 3148, 8148, 3158, 8158, 3168, 8168, 15438, 15458]:
    assert report["after"][str(port)] == report["before"][str(port)], (
        f"Sibling listener changed:{port}"
    )
report["status"] = "pass"
report["endedAtUtc"] = datetime.datetime.now(datetime.UTC).isoformat()
(out / "teardown.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k not in ["before", "after"]}, indent=2))
