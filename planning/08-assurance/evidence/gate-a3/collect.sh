#!/usr/bin/env bash
# Gate A3 evidence collector.
#
# Why a script and not a checklist: 02-STANDARDS.md §4.4 records that CI
# artifact retention is finite (90 days), so the committed summary — not the
# run — is the durable record. A committed summary is only worth reading if
# every number in it came out of a runner, so this script writes the raw
# output to `raw/` and `summarise.py` reads the numbers back out of those
# files. Nothing in the pack is typed by hand.
#
# Runs at zero model spend: ZERO_SPEND pins an invalid key by construction and
# tests/conftest.py denies the Anthropic client constructor on top of it.
#
# Usage:  bash planning/08-assurance/evidence/gate-a3/collect.sh
# Env:    VENV_BIN=/path/to/.venv/bin (default: ./.venv/bin)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
OUT="${REPO_ROOT}/planning/08-assurance/evidence/gate-a3/raw"
VENV_BIN="${VENV_BIN:-${REPO_ROOT}/.venv/bin}"
PY="${VENV_BIN}/python"

TEST_ENV=(OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONHASHSEED=0)
ZERO_SPEND=(ANTHROPIC_API_KEY=local-preview-disabled)

mkdir -p "$OUT"
cd "$REPO_ROOT" || exit 1

# The tree the numbers describe. A pack without this is unverifiable.
{
  echo "commit=$(git rev-parse HEAD)"
  echo "commit_short=$(git rev-parse --short HEAD)"
  echo "branch=$(git rev-parse --abbrev-ref HEAD)"
  echo "dirty=$(test -n "$(git status --porcelain)" && echo yes || echo no)"
  echo "collected_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "python=$("$PY" -c 'import sys; print(sys.version.split()[0])')"
  echo "src_module=$("$PY" -c 'import src; print(src.__file__)')"
} > "$OUT/provenance.txt"

# Captures are written to a temp file and moved into place, never opened for
# truncation in situ. `tests/test_assurance_docs.py` reads these files, and it
# runs inside the very `pytest -m "not e2e"` step below — a `> "$out"` redirect
# would empty the capture it is reading and fail the gate on an artefact of the
# collection, not on anything true about the repository.
run() {  # run <outfile> <cmd...>
  local out="$OUT/$1"; shift
  local tmp="${out}.partial"
  echo "==> $1 ... -> raw/$(basename "$out")"
  ( set -x; "$@" ) > "$tmp" 2>&1
  echo "exit=$?" >> "$tmp"
  mv -f "$tmp" "$out"
}

# The per-PR gate itself, with coverage. Coverage is measured over exactly the
# selection that gates (`-m "not e2e"`); a floor measured against a different
# set of tests than the one that gates is a number about nothing.
run pytest-not-e2e.txt env "${TEST_ENV[@]}" "${ZERO_SPEND[@]}" \
  "$PY" -m pytest -m "not e2e" tests/ -q \
  --cov=src --cov-report=term-missing:skip-covered

# Per-package floors re-read the same data file, so they cost nothing extra.
#
# The floors are passed explicitly, and must stay equal to the Makefile's COV_*
# values. coverage.py's `fail_under` in pyproject.toml is *global*, so a
# per-package report left to inherit it is judged against the project floor and
# reports a failure that is not one — this pack's first run showed src/api at 88
# against 89 and called it a breach, when the package floor is 86. That is
# precisely the class of hand-read number this script exists to eliminate.
run_cov() {  # run_cov <name> <include-glob> <floor>
  run "coverage-src-$1.txt" "$PY" -m coverage report --include="$2" \
    --fail-under="$3" --format=total
}
run_cov api      'src/api/*'       86
run_cov agents   'src/agents/*'    92
run_cov security 'src/security/*'  97
run_cov eval     'src/eval/*'      91
run coverage-total.txt "$PY" -m coverage report --format=total

# Tier and purpose selectors, each countable on its own.
run pytest-e2e.txt env "${TEST_ENV[@]}" "${ZERO_SPEND[@]}" USE_MOCK_DATA=true \
  "$PY" -m pytest -m e2e tests/ -q
for mark in property fault security contract; do
  run "pytest-${mark}.txt" env "${TEST_ENV[@]}" "${ZERO_SPEND[@]}" \
    "$PY" -m pytest -m "${mark} and not e2e" tests/ -q
done

run mypy.txt "$PY" -m mypy --strict src/
run ruff.txt "$VENV_BIN/ruff" check src/ tests/

# The two campaigns that produce *measured* results at zero spend. They are the
# only quantitative accuracy/safety evidence this repository has: the four
# LLM-judged research metrics have never been run (README "Status: wired, never
# run green"), so the system card's evaluation section is built from these and
# says so.
run safety-suite.txt env "${TEST_ENV[@]}" "${ZERO_SPEND[@]}" \
  "$PY" -m src.eval.safety_suite

# The scripted learner tier runs as a *campaign* — the CLI, the durable record
# layout, the summary files, the cost accounting — which is what ci.yml runs and
# what makes the $0.0000 assertion mean something. Output goes under build/ so
# the pack carries the check's verdict, not a second copy of the campaign.
run scripted-tier.txt env "${TEST_ENV[@]}" "${ZERO_SPEND[@]}" \
  USE_MOCK_DATA=true ENABLE_CHECKPOINTING=true \
  "$PY" -m src.eval.simulate_learner --output-dir build/gate-a3-scripted-tier
run scripted-tier-check.txt env "${TEST_ENV[@]}" "${ZERO_SPEND[@]}" \
  "$PY" -m src.eval.scripted_tier_check build/gate-a3-scripted-tier/summary.jsonl

# SBOM + vulnerability audit from one PyPA tool (02-STANDARDS.md §4.4).
#
# pip-audit is deliberately *not* in requirements-lock.txt: ADR 0045 gives this
# repository one dependency diff per phase and WO-A02 already spent it, and a
# supply-chain auditor that ships inside the set it audits is the wrong shape
# anyway. So it is resolved from PIP_AUDIT or skipped, and the skip is recorded
# in the raw output rather than silently producing a pack with no SBOM in it.
#
# `--no-deps` audits the committed pins exactly as written instead of resolving
# a fresh tree, which is the only way the SBOM describes the set CI installs.
# The lock is not hashed (a recorded ADR 0045 limit), so pip-audit warns; the
# warning is kept in the raw file rather than suppressed.
PIP_AUDIT="${PIP_AUDIT:-$(command -v pip-audit || true)}"
if [ -n "$PIP_AUDIT" ] && [ -x "$PIP_AUDIT" ]; then
  run pip-audit.txt "$PIP_AUDIT" -r requirements-lock.txt --no-deps --format columns
  run pip-audit-runtime.txt "$PIP_AUDIT" -r requirements-runtime-lock.txt --no-deps \
    --format columns
  echo "==> SBOM -> sbom.cyclonedx.json"
  "$PIP_AUDIT" -r requirements-lock.txt --no-deps --format cyclonedx-json \
    -o "$(dirname "$OUT")/sbom.cyclonedx.json" > "$OUT/sbom.txt.partial" 2>&1
  echo "exit=$?" >> "$OUT/sbom.txt.partial"
  mv -f "$OUT/sbom.txt.partial" "$OUT/sbom.txt"
else
  echo "pip-audit not found; set PIP_AUDIT=/path/to/pip-audit" > "$OUT/pip-audit.txt"
  echo "exit=skipped" >> "$OUT/pip-audit.txt"
fi

echo "done -> $OUT"
