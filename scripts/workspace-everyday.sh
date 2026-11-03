#!/usr/bin/env bash
# Stable private credentials/backups; no launchd, cron, recurrence or paid calls.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WORKSPACE_DATA_DIR="${WORKSPACE_DATA_DIR:-$HOME/Library/Application Support/arxiv-workspace}"
if [ "$#" -eq 0 ]; then set -- run; fi
exec bash "$here/workspace-local.sh" "$@"
