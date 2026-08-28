#!/usr/bin/env bash
#
# Lifecycle for the WO-21 end-to-end stack.
#
# Every Compose invocation in this file carries BOTH `-p` (the project name)
# and BOTH `-f` files. That is not style. `docker compose down` without them
# resolves the project from the current directory and the base file's
# hardcoded `container_name` values, and will remove the containers of any
# other worktree or CI job running the same stack
# (`docs/revamp/06-WORK-ORDERS.md` §5.4).
#
#   bash web/e2e/support/stack.sh up     # build + start + wait for healthy
#   bash web/e2e/support/stack.sh seed   # idempotent baseline-* fixtures
#   bash web/e2e/support/stack.sh url    # print the base URL for Playwright
#   bash web/e2e/support/stack.sh logs
#   bash web/e2e/support/stack.sh down   # stop + remove, keeping volumes
#
# `up` is idempotent: re-running it against a healthy stack is a no-op plus
# a rebuild check, which is what makes `npm run e2e:stack:up && npm run e2e`
# safe to type twice.

set -euo pipefail

project="${E2E_COMPOSE_PROJECT:-arxiv-wo21-e2e}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../../.." && pwd)"
base_file="${repo_root}/docker-compose.yml"
overlay_file="${here}/compose.e2e.yml"
web_port="${E2E_WEB_PORT:-13210}"
base_url="${E2E_BASE_URL:-http://127.0.0.1:${web_port}}"

# The base file declares `ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:?...}`, so
# Compose refuses to interpolate without *something* in the environment even
# though the overlay then pins the value. Supply the disabled sentinel here
# so an operator with no key set can still bring the stack up, and so an
# operator WITH a real key exported never sees it reach the interpolation.
export ANTHROPIC_API_KEY=local-preview-disabled

compose() {
  docker compose -p "${project}" -f "${base_file}" -f "${overlay_file}" "$@"
}

case "${1:-}" in
  up)
    # `--wait` blocks on the healthchecks the base file already declares, so
    # the seed below never races an unmigrated Postgres or a booting app.
    compose up -d --build --wait
    echo "stack up: ${base_url} (project ${project})"
    ;;
  seed)
    E2E_COMPOSE_PROJECT="${project}" bash "${here}/../fixtures/seed.sh"
    ;;
  url)
    echo "${base_url}"
    ;;
  logs)
    shift || true
    compose logs "$@"
    ;;
  down)
    # No `-v`: the named volumes are project-scoped
    # (`arxiv-wo21-e2e_postgres-data`), so leaving them costs nothing and
    # keeps a re-`up` fast. `docker compose -p arxiv-wo21-e2e ... down -v`
    # if you want them gone.
    compose down
    ;;
  *)
    echo "usage: stack.sh {up|seed|url|logs|down}" >&2
    exit 2
    ;;
esac
