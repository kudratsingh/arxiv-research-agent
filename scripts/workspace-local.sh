#!/usr/bin/env bash
# Loopback-only workspace. Storage survives process restarts and `stop-storage`.
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT"
VENV_PYTHON="${VENV_PYTHON:-/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python}"
export ANTHROPIC_API_KEY=local-preview-disabled
export USE_MOCK_DATA=true ENABLE_WORKSPACE=true ENABLE_API_AUTH=true
export WORKSPACE_SCHEDULE_APPROVED=false
export POSTGRES_URL="${WORKSPACE_POSTGRES_URL:-postgresql://workspace:workspace-local-only@127.0.0.1:15438/workspace}"
export WORKSPACE_RATE_DATABASE_URL="$POSTGRES_URL"
WORKSPACE_API_PORT="${WORKSPACE_API_PORT:-8137}"
WORKSPACE_WEB_PORT="${WORKSPACE_WEB_PORT:-3137}"
WORKSPACE_DATA_DIR="${WORKSPACE_DATA_DIR:-$TASK_ROOT/outputs/workspace-live}"
export WORKSPACE_API_PORT WORKSPACE_WEB_PORT
export API_INTERNAL_BASE="http://127.0.0.1:$WORKSPACE_API_PORT"
export NEXT_TELEMETRY_DISABLED=1
export WORKSPACE_LIVE=1 WORKSPACE_PREVIEW=1
WORKSPACE_OWNER="${WORKSPACE_OWNER:-personal-local}"
if [[ ! "$WORKSPACE_OWNER" =~ ^[A-Za-z0-9_-]{1,64}$ ]]; then
  echo 'WORKSPACE_OWNER must be a short local operator identifier.' >&2
  exit 2
fi
umask 077
mkdir -p "$WORKSPACE_DATA_DIR"
chmod 700 "$WORKSPACE_DATA_DIR"
if [ ! -f "$WORKSPACE_DATA_DIR/.api-key" ]; then
  "$VENV_PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$WORKSPACE_DATA_DIR/.api-key"
fi
ARXIV_API_KEY="$(cat "$WORKSPACE_DATA_DIR/.api-key")"
export ARXIV_API_KEY API_KEYS="$WORKSPACE_OWNER:$ARXIV_API_KEY"
COMPOSE=(docker compose -p arxiv-workspace-live -f compose.workspace.yml)
case "${1:-run}" in
  run|dev)
    "$VENV_PYTHON" - <<'PY'
import os, socket
for port in (int(os.environ['WORKSPACE_API_PORT']), int(os.environ['WORKSPACE_WEB_PORT'])):
    if not 1024 <= port <= 65535:
        raise SystemExit('Workspace ports must be between 1024 and 65535.')
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
    "$VENV_PYTHON" -m src.workspace initialize --owner "$WORKSPACE_OWNER"
    "$VENV_PYTHON" -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port "$WORKSPACE_API_PORT" --no-access-log > "$WORKSPACE_DATA_DIR/api.log" 2>&1 &
    API_PID=$!
    trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM
    "$VENV_PYTHON" - <<'PY'
import os, time
from urllib.request import urlopen
deadline = time.monotonic() + 45
while True:
    try:
        with urlopen(f"http://127.0.0.1:{os.environ['WORKSPACE_API_PORT']}/healthz", timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        if time.monotonic() >= deadline:
            raise SystemExit('Workspace API did not start within 45 seconds; inspect the private api.log.')
        time.sleep(.25)
PY
    cd web
    if [ "${1:-run}" = dev ]; then
      npx --no-install next dev --webpack --hostname 127.0.0.1 --port "$WORKSPACE_WEB_PORT"
    else
      # Rebuild current checked-out sources; never serve an unnoticed old build.
      npm run build
      mkdir -p .next/standalone/.next/static .next/standalone/public
      cp -R .next/static/. .next/standalone/.next/static/
      if [ -d public ]; then cp -R public/. .next/standalone/public/; fi
      HOSTNAME=127.0.0.1 PORT="$WORKSPACE_WEB_PORT" node .next/standalone/server.js
    fi
    ;;
  refresh) "$VENV_PYTHON" -m src.workspace refresh --owner "$WORKSPACE_OWNER" ;;
  worker-once) "$VENV_PYTHON" -m src.workspace worker-once ;;
  worker-health)
    worker_container="$("${COMPOSE[@]}" ps --status running -q worker)"
    if [ -n "$worker_container" ]; then
      "${COMPOSE[@]}" exec -T worker python -m src.workspace.worker --healthcheck --heartbeat /app/outputs/worker-heartbeat.json
    else
      echo '{"state":"disabled_not_started","recurrence_enabled":false}'
    fi
    ;;
  worker-config) "${COMPOSE[@]}" --profile worker config ;;
  backup)
    backup_db="$("$VENV_PYTHON" - <<'PY'
import os
from psycopg.conninfo import conninfo_to_dict
connection = conninfo_to_dict(os.environ['POSTGRES_URL'])
if connection.get('host') not in {'127.0.0.1', 'localhost'} or connection.get('port') != '15438' or connection.get('user') != 'workspace':
    raise SystemExit('This backup command only supports the explicitly isolated local workspace Postgres service.')
print(os.environ.get('WORKSPACE_BACKUP_DB') or connection['dbname'])
PY
)"
    if [[ ! "$backup_db" =~ ^[A-Za-z][A-Za-z0-9_]{0,62}$ ]]; then echo 'Invalid backup database name.' >&2; exit 2; fi
    mkdir -p "$WORKSPACE_DATA_DIR/backups"
    chmod 700 "$WORKSPACE_DATA_DIR/backups"
    backup_partial="$(mktemp "$WORKSPACE_DATA_DIR/backups/.workspace-XXXXXXXX")"
    if ! "${COMPOSE[@]}" exec -T postgres pg_dump -Fc --no-owner --no-acl -U workspace -d "$backup_db" > "$backup_partial"; then
      echo "Backup failed. Incomplete private file retained: $backup_partial" >&2
      exit 1
    fi
    backup_file="$WORKSPACE_DATA_DIR/backups/workspace-$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$backup_partial" .partial).dump"
    mv "$backup_partial" "$backup_file"
    (cd "$(dirname "$backup_file")" && shasum -a 256 "$(basename "$backup_file")" > "$(basename "$backup_file").sha256")
    echo "Private backup: $backup_file"
    echo "Checksum: $backup_file.sha256"
    ;;
  restore-check)
    backup_file="${2:?Usage: workspace-local.sh restore-check /absolute/path/backup.dump}"
    # Verify the exact supplied bytes, never the original path embedded in a
    # copied/legacy sidecar. This also works after moving a backup directory.
    "$VENV_PYTHON" - "$backup_file" <<'PY'
import hashlib, re, sys
from pathlib import Path
backup = Path(sys.argv[1])
sidecar = Path(str(backup) + '.sha256').read_text().strip()
if not re.fullmatch(r'[0-9a-fA-F]{64} [ *].+', sidecar):
    raise SystemExit('Invalid backup checksum sidecar; nothing restored.')
expected = sidecar[:64].lower()
hasher = hashlib.sha256()
with backup.open('rb') as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        hasher.update(block)
if hasher.hexdigest() != expected:
    raise SystemExit('Backup checksum mismatch; nothing restored.')
print('Exact supplied backup checksum verified.')
PY
    # Always a NEW disposable database; an existing database is never replaced.
    restore_db="workspace_restore_check_$(date -u +%Y%m%d%H%M%S)_$$"
    "${COMPOSE[@]}" exec -T postgres createdb -U workspace "$restore_db"
    trap '"${COMPOSE[@]}" exec -T postgres dropdb -U workspace "$restore_db"' EXIT
    "${COMPOSE[@]}" exec -T postgres pg_restore --exit-on-error --no-owner --no-acl -U workspace -d "$restore_db" < "$backup_file"
    "${COMPOSE[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U workspace -d "$restore_db" -c 'SELECT count(*) AS restored_works FROM workspace_works; SELECT count(*) AS restored_notes FROM workspace_entries;'
    echo 'Restore check passed in a new disposable database; original data was not replaced.'
    ;;
  migrate) "${COMPOSE[@]}" up -d --wait; "$VENV_PYTHON" -m src.workspace migrate ;;
  stop-storage) "${COMPOSE[@]}" down ;;
  *) echo 'Usage: bash scripts/workspace-local.sh [run|dev|refresh|worker-once|worker-health|worker-config|backup|restore-check|migrate|stop-storage]' >&2; exit 2 ;;
esac
