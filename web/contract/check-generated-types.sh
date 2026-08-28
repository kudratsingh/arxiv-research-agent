#!/usr/bin/env bash
#
# Drift check 2 of 4 (04-ARCHITECTURE.md §3.5): the committed
# `lib/api/generated/schema.d.ts` must be exactly what `openapi-typescript`
# produces from the committed `contract/openapi.json`.
#
# Run by `npm run contract:check`, which CI runs in the `web` job. It needs no
# API and no network — both inputs are in the repository.
#
# The generator is pinned to an exact version in `package.json`
# (`openapi-typescript` 7.13.0, no caret) precisely because this check
# compares bytes: a floating minor that changed its formatting would fail an
# unchanged main with no commit to revert.
#
# When this fails, the fix is `npm run generate:types` and committing the
# result — never hand-editing the generated file.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMMITTED="./lib/api/generated/schema.d.ts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# `--no-install` so a missing dependency is an error rather than a silent
# download of some other version.
npx --no-install openapi-typescript ./contract/openapi.json \
  --output "$TMP/schema.d.ts" >/dev/null

if diff -u "$COMMITTED" "$TMP/schema.d.ts"; then
  echo "contract:check — generated types match contract/openapi.json"
  exit 0
fi

cat >&2 <<'MSG'

contract:check FAILED — lib/api/generated/schema.d.ts is not what
contract/openapi.json generates. The diff above is committed-vs-regenerated.

Fix: npm run generate:types, then commit the result.
MSG
exit 1
