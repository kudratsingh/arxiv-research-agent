"""Run/inspect/stop a generation-disabled loopback D5 preview.

From the worktree root: locked-python - < scripts/workspace-d5-preview.py run
No provider execution, seeding, owner ports, recurrence or automatic replacement.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

os.environ["ANTHROPIC_API_KEY"] = "local-preview-disabled"
import src  # noqa: E402


def listeners(port: int) -> list[int]:
    result = subprocess.run(["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"], capture_output=True, text=True)
    return [int(value) for value in result.stdout.split()]


def ready(url: str, process: subprocess.Popen, key: str | None = None) -> dict:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Preview exited; inspect its local log")
        try:
            request = urllib.request.Request(url, headers={"X-API-Key": key} if key else {})
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response) if key else {"status": response.status}
        except (OSError, ValueError):
            time.sleep(.25)
    raise RuntimeError("Preview did not become ready; no other process was stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["run", "status", "stop"])
    parser.add_argument("--database", default="workspace_d5_benchmark_final")
    parser.add_argument("--port", type=int, default=3192)
    parser.add_argument("--principal", default="d5-validation-run")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if not Path(src.__file__).resolve().is_relative_to(root) or not (root / "web/package.json").exists():
        raise RuntimeError("Run from the worktree root using Python stdin; import src must resolve here")
    if not 3192 <= args.port <= 3199 or not re.fullmatch(r"workspace_d5_[a-z0-9_]+", args.database) or not re.fullmatch(r"d5-[a-z0-9-]+", args.principal):
        raise RuntimeError("Only isolated D5 ports/databases/principals are allowed")
    out = root / "outputs/d5"
    out.mkdir(parents=True, exist_ok=True)
    receipt_path = out / f"preview-{args.port}.json"
    if args.verb != "run":
        value = json.loads(receipt_path.read_text())
        if value["root"] != str(root) or value["web_port"] != args.port:
            raise RuntimeError("Preview receipt belongs to another checkout")
        if args.verb == "stop":
            for role in ("web", "api"):
                port, pid = value[role + "_port"], value[role + "_pid"]
                active = listeners(port)
                if not active:
                    continue
                cwd = subprocess.check_output(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], text=True)
                expected = value["runtime"] if role == "web" else str(root)
                if active != [pid] or "n" + expected + "\n" not in cwd:
                    raise RuntimeError("Port/process ownership changed; nothing was stopped")
                os.kill(pid, signal.SIGTERM)
        print(json.dumps({**value, "web_listeners": listeners(value["web_port"]), "api_listeners": listeners(value["api_port"])}))
        return
    api_port = args.port + 5000
    if listeners(args.port) or listeners(api_port):
        raise RuntimeError("D5 preview port occupied; inspect status, never replace another process")
    build = (root / "web/.next/BUILD_ID").read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", build):
        raise RuntimeError("Build the frontend first")
    runtime = root / "outputs/d5-preview" / build
    if not runtime.exists():
        shutil.copytree(root / "web/.next/standalone", runtime, symlinks=True)
        shutil.copytree(root / "web/.next/static", runtime / ".next/static", dirs_exist_ok=True)
        if (root / "web/public").exists():
            shutil.copytree(root / "web/public", runtime / "public", dirs_exist_ok=True)
    key_path = out / f"preview-{args.port}.key"
    if not key_path.exists():
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as target:
            target.write(secrets.token_urlsafe(32))
    key = key_path.read_text().strip()
    env = {**os.environ, "ANTHROPIC_API_KEY": "local-preview-disabled", "WORKSPACE_D5_OFFLINE": "1", "USE_MOCK_DATA": "true", "ENABLE_WORKSPACE": "true", "ENABLE_API_AUTH": "true", "API_KEYS": args.principal + ":" + key, "POSTGRES_URL": "postgresql://workspace:workspace-local-only@127.0.0.1:15488/" + args.database, "WORKSPACE_SCHEDULE_APPROVED": "false", "ENABLE_JOB_REDRIVER": "false", "API_KEY_HOURLY_LIMIT": "10000", "PYTHONPATH": "/private/tmp/arxiv-qualification-schema-deps:" + str(root), "OMP_NUM_THREADS": "1", "NEXT_TELEMETRY_DISABLED": "1"}
    with (out / f"preview-api-{api_port}.log").open("ab") as log:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(api_port)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    state = ready(f"http://127.0.0.1:{api_port}/workspace/state", api, key)
    if state["principal_key_id"] != args.principal or state["schedule"]["enabled"]:
        api.terminate()
        raise RuntimeError("Unexpected principal or enabled recurrence")
    env.update(API_INTERNAL_BASE=f"http://127.0.0.1:{api_port}", ARXIV_API_KEY=key, WORKSPACE_LIVE="1", WORKSPACE_PREVIEW="1", WORKSPACE_DESIGN_PREVIEW="0", HOSTNAME="127.0.0.1", PORT=str(args.port))
    with (out / f"preview-web-{args.port}.log").open("ab") as log:
        web = subprocess.Popen(["node", str(runtime / "server.js")], cwd=runtime, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    ready(f"http://127.0.0.1:{args.port}/workspace/today?mode=learn", web)
    value = {"root": str(root), "runtime": str(runtime), "database": args.database, "principal": args.principal, "build_id": build, "web_pid": web.pid, "api_pid": api.pid, "web_port": args.port, "api_port": api_port, "provider_sentinel": True, "recurrence": False}
    receipt_path.write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps({**value, "url": f"http://localhost:{args.port}/workspace/today?mode=learn"}))


if __name__ == "__main__":
    main()
