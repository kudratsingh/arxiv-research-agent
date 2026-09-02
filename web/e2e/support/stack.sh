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
#
# `E2E_PILOT=1` ADDS A THIRD `-f` AND A THIRD KIND OF STACK (WO-W17).
#
#   E2E_PILOT=1 bash web/e2e/support/stack.sh up
#   E2E_PILOT=1 bash web/e2e/support/stack.sh seed
#   E2E_PILOT=1 npx playwright test -c playwright.pilot.config.ts
#
# `support/compose.pilot.yml` puts the committed production edge
# (`deploy/pilot/Caddyfile`) in front of `web`, turns `PILOT_EDGE_AUTH` on,
# EMPTIES `ARXIV_API_KEY`, and issues two principals instead of one. It is not
# a superset of the ordinary tier and cannot serve it: the `baseline-*`
# fixtures belong to `E2E_PRINCIPAL` and are invisible to both pilots under
# ADR 0036. Run one or the other, and `down` before switching — the two use
# the same container names unless you also change `E2E_COMPOSE_PROJECT` and
# the `E2E_*_CONTAINER` variables.
#
# `up` also GENERATES the edge's bcrypt user file, into `web/build/e2e/`,
# which is git-ignored. Nothing bcrypt-shaped is committed by this repository,
# for the deployment or for the tier that tests it.

set -euo pipefail

project="${E2E_COMPOSE_PROJECT:-arxiv-wo21-e2e}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../../.." && pwd)"
base_file="${repo_root}/docker-compose.yml"
overlay_file="${here}/compose.e2e.yml"
pilot_file="${here}/compose.pilot.yml"
web_port="${E2E_WEB_PORT:-13210}"
base_url="${E2E_BASE_URL:-http://127.0.0.1:${web_port}}"

# WO-W17. Off unless exactly `1`, matching the resolver's own refusal to be
# enabled by inference (`web/lib/server/pilot.ts`, guard 1).
pilot="${E2E_PILOT:-}"
pilot_edge_port="${E2E_PILOT_EDGE_PORT:-13290}"
pilot_users_file="${E2E_PILOT_USERS_FILE:-./web/build/e2e/pilot-users.caddy}"
if [ "${pilot}" = "1" ]; then
  base_url="${E2E_PILOT_BASE_URL:-http://127.0.0.1:${pilot_edge_port}}"
fi

# The base file declares `ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:?...}`, so
# Compose refuses to interpolate without *something* in the environment even
# though the overlay then pins the value. Supply the disabled sentinel here
# so an operator with no key set can still bring the stack up, and so an
# operator WITH a real key exported never sees it reach the interpolation.
export ANTHROPIC_API_KEY=local-preview-disabled

compose() {
  if [ "${pilot}" = "1" ]; then
    docker compose -p "${project}" \
      -f "${base_file}" -f "${overlay_file}" -f "${pilot_file}" "$@"
  else
    docker compose -p "${project}" -f "${base_file}" -f "${overlay_file}" "$@"
  fi
}

# Write the edge's basic-auth file: one `username bcrypt-hash` line per pilot.
#
# GENERATED, NEVER COMMITTED. The plaintext passwords are local sentinels
# declared in `support/env.ts` so a spec can type them; the hashes are
# produced here, into a git-ignored directory, by the same
# `caddy hash-password` invocation `docs/runbooks/pilot.md` gives an operator.
# A committed hash would be a credential in the repository, which is the one
# thing `deploy/pilot/README.md` says this design never does.
write_pilot_users() {
  local out="${repo_root}/${pilot_users_file#./}"
  mkdir -p "$(dirname "${out}")"
  : >"${out}"
  local names=("${E2E_PILOT_A_USER:-pilot-a}" "${E2E_PILOT_B_USER:-pilot-b}")
  local secrets=(
    "${E2E_PILOT_A_PASSWORD:-pilot-a-local-preview-disabled}"
    "${E2E_PILOT_B_PASSWORD:-pilot-b-local-preview-disabled}"
  )
  local i hash
  for i in 0 1; do
    hash="$(docker run --rm caddy:2.11.4-alpine \
      caddy hash-password --plaintext "${secrets[$i]}")"
    printf '%s %s\n' "${names[$i]}" "${hash}" >>"${out}"
  done
  echo "pilot users written: ${out} (git-ignored)"
}

case "${1:-}" in
  up)
    if [ "${pilot}" = "1" ]; then write_pilot_users; fi
    # `--wait` blocks on the healthchecks the base file already declares, so
    # the seed below never races an unmigrated Postgres or a booting app.
    compose up -d --build --wait
    echo "stack up: ${base_url} (project ${project})"
    ;;
  seed)
    E2E_COMPOSE_PROJECT="${project}" E2E_PILOT="${pilot}" \
      bash "${here}/../fixtures/seed.sh"
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
