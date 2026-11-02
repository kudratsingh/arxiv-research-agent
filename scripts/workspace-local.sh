#!/usr/bin/env bash
# Loopback-only workspace. Storage survives process restarts and `stop-storage`.
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT"
VENV_PYTHON="${VENV_PYTHON:-/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python}"
export ANTHROPIC_API_KEY=local-preview-disabled
export USE_MOCK_DATA=true ENABLE_WORKSPACE=true ENABLE_API_AUTH=true
export WORKSPACE_SCHEDULE_APPROVED=false
export POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15438/workspace
export API_INTERNAL_BASE=http://127.0.0.1:8137
export WORKSPACE_LIVE=1 WORKSPACE_PREVIEW=1
WORKSPACE_OWNER="${WORKSPACE_OWNER:-personal-local}"
if [[ ! "$WORKSPACE_OWNER" =~ ^[A-Za-z0-9_-]{1,64}$ ]]; then
  echo 'WORKSPACE_OWNER must be a short local operator identifier.' >&2
  exit 2
fi
umask 077
mkdir -p outputs/workspace-live
chmod 700 outputs/workspace-live
if [ ! -f outputs/workspace-live/.api-key ]; then
  "$VENV_PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))' > outputs/workspace-live/.api-key
fi
ARXIV_API_KEY="$(cat outputs/workspace-live/.api-key)"
export ARXIV_API_KEY API_KEYS="$WORKSPACE_OWNER:$ARXIV_API_KEY"
COMPOSE=(docker compose -p arxiv-workspace-live -f compose.workspace.yml)
case "${1:-run}" in
  run|dev)
    "$VENV_PYTHON" - <<'PY'
import socket
for port in (8137, 3137):
    try:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(1)
    except OSError as exc:
        raise SystemExit(f"Local port {port} is already in use; stop the existing workspace before starting another.") from exc
PY
    "${COMPOSE[@]}" up -d --wait
    "$VENV_PYTHON" -m src.workspace migrate
    "$VENV_PYTHON" -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8137 --no-access-log > outputs/workspace-live/api.log 2>&1 &
    API_PID=$!
    trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM
    cd web
    if [ "${1:-run}" = dev ]; then
      npm run dev -- --hostname 127.0.0.1 --port 3137
    else
      if [ ! -f .next/BUILD_ID ]; then npm run build; fi
      mkdir -p .next/standalone/.next/static .next/standalone/public
      cp -R .next/static/. .next/standalone/.next/static/
      if [ -d public ]; then cp -R public/. .next/standalone/public/; fi
      HOSTNAME=127.0.0.1 PORT=3137 node .next/standalone/server.js
    fi
    ;;
  refresh) "$VENV_PYTHON" -m src.workspace refresh --owner "$WORKSPACE_OWNER" ;;
  worker-once) "$VENV_PYTHON" -m src.workspace worker-once ;;
  migrate) "${COMPOSE[@]}" up -d --wait; "$VENV_PYTHON" -m src.workspace migrate ;;
  stop-storage) "${COMPOSE[@]}" down ;;
  *) echo 'Usage: bash scripts/workspace-local.sh [run|dev|refresh|worker-once|migrate|stop-storage]' >&2; exit 2 ;;
esac
