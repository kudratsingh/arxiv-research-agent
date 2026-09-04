# Gate A3 — evidence pack

**Assurance.** A reviewer can open one index and follow every claim in the
README to the artifact that enforces it, including the framework mapping and
the system card.

> **This page is generated.** `collect.sh` runs each gate and writes its raw
> output to [`raw/`](raw); `summarise.py` reads those files back and writes this
> page. No number below was typed by a person. Regenerate with:
>
> ```bash
> VENV_BIN=/path/to/.venv/bin PIP_AUDIT=/path/to/pip-audit \
>   bash planning/08-assurance/evidence/gate-a3/collect.sh
> python planning/08-assurance/evidence/gate-a3/summarise.py
> ```

⚠ **CI runs are not the record.** Artifact retention is finite (90 days on this
repository), so a link to a green workflow run is evidence that expires. This
committed, dated summary is the durable artifact — `02-STANDARDS.md` §4.4.

## Provenance

| | |
|---|---|
| Commit | `ed71098b2c7854f8608a9194c8f82201e941c87b` |
| Branch | `assurance/wo-a14-evidence` |
| Working tree dirty at collection | yes |
| Collected (UTC) | 2026-09-04T22:41:19Z |
| Python | 3.13.7 |
| `src` resolved to | `/private/tmp/arxiv-asr-a14/src/__init__.py` |

The last row is not decoration. It is the check that these numbers describe
*this* worktree rather than a sibling checkout on the same machine.

The tree was **dirty** at collection: this work order's own additions (`docs/assurance/`, `tests/test_assurance_docs.py`, and this directory) were uncommitted when the gates ran, so the tier counts include them while every `src/` file measured is at the commit above.

## Tiers

| Selection | Result |
|---|---|
| `pytest -m "not e2e"` — the per-PR gate | 3235 passed, 55 skipped |
| `pytest -m e2e` | 16 passed |
| `pytest -m property` | 152 passed |
| `pytest -m fault` | 157 passed, 3 skipped |
| `pytest -m security` | 314 passed |
| `pytest -m contract` | 98 passed |

The gate deselects 16 e2e tests, which the `-m e2e` row
then runs separately. Every tier is offline and spends nothing: the harness
denies the model client and pins an invalid key by construction.

## Coverage

Branch coverage, measured over exactly the selection that gates. A floor
measured against a different set of tests than the one that gates is a number
about nothing.

| Scope | Floor | Measured |
|---|---|---|
| project (`fail_under` in `pyproject.toml`) | 89% | **91.31%** |
| `src/api` | 86% | 88% |
| `src/agents` | 92% | 92% |
| `src/security` | 97% | 100% |
| `src/eval` | 91% | 94% |

Per-package floors come from the Makefile's `COV_*` variables and are passed
explicitly, because `coverage.py`'s `fail_under` is global — a per-package
report left to inherit it is judged against the project floor and reports a
failure that is not one.

## Types and lint

| Gate | Result |
|---|---|
| `mypy --strict src/` | Success: no issues found in 93 source files |
| `ruff check src/ tests/` | All checks passed! |

## Measured results

The only quantitative accuracy and safety evidence this repository has. The
four LLM-judged research metrics have never been run — see
[`../../../../docs/assurance/system-card.md`](../../../../docs/assurance/system-card.md) §5.2.

### Adversarial safety suite (42 authored attacks, model-free, offline)

```
attack success    3/42 = 7.14%  (Wilson 95% 2.46%..19.01%)
decision          PROMOTE  (advisory)
```

Hard violations, gated at absolute zero:

```
egress_to_non_allowlisted_host   0
secret_exfiltrated               0
unauthorised_tool_call           0
```

The three successes are named residuals recorded in the corpus before the run,
not discoveries: asi01-soft-phrased-goal-nudge, asi08-attacker-named-section, asi08-unbounded-section-list.

Full report: [`raw/safety-suite.txt`](raw/safety-suite.txt).

### Scripted learner tier (the campaign, not the unit tests)

```
Scripted tier OK: 15/15 sessions, $0.0000 spent, 0 unmet expectations, 15 attributable row(s).
```

Run as a campaign — the CLI, the durable record layout, the summary files and
the cost accounting — because that is the surface a funded lane would use. The
`$0.0000` assertion is what makes it a zero-spend gate rather than a hope.

## Supply chain

SBOM and vulnerability audit from one PyPA tool, over `requirements-lock.txt`
with `--no-deps` — the pins CI installs, not a fresh resolve nobody ran.

| | |
|---|---|
| Format | CycloneDX 1.4 |
| Components | 126 |
| Vulnerabilities recorded in the SBOM | 5 |
| SBOM timestamp | 2026-09-04T22:47:19.656973+00:00 |
| `pip-audit` exit | 1 (non-zero: findings, listed below) |

| Package | Pinned | Advisory | Fixed in |
|---|---|---|---|
| `langgraph-checkpoint-postgres` | 3.1.0 | PYSEC-2026-3635 | 3.1.1 |
| `langgraph-checkpoint-sqlite` | 3.1.0 | PYSEC-2026-3636 | 3.1.1 |
| `setuptools` | 81.0.0 | PYSEC-2026-3447 | 83.0.0 |
| `torch` | 2.12.1 | PYSEC-2025-194 | 2.13.0 |

`requirements-runtime-lock.txt` yields the identical finding set
([`raw/pip-audit-runtime.txt`](raw/pip-audit-runtime.txt)). None is fixed on
this branch: ADR 0045 gives this repository one dependency diff per phase and
WO-A02 already spent it, so this work order reports rather than moves the lock.
Only one of the four is recorded in `pyproject.toml` today (the sqlite
checkpointer's); its postgres sibling shares the fix version and is not. Commentary in
[`../../../../docs/assurance/framework-mapping.md`](../../../../docs/assurance/framework-mapping.md) §4.

## What this pack does not prove

Stated here so the numbers above are not read for more than they are worth.

- **No accuracy number.** Nothing in this pack measures whether a briefing is
  correct, complete or faithful. That needs a funded campaign (W-OD-1).
- **No runtime number.** Nothing is deployed, so there is no latency, error-rate
  or saturation evidence, and every SLO is *declared, not earned*.
- **No independent review.** Every artifact here was produced by the same
  program that wrote the code it measures.
- **Coverage is not correctness.** Nine branches in ten execute under test;
  that says nothing about whether the assertions around them are the right
  ones.
- **These are desk numbers, and the runner's are different.** CI has Postgres
  on PATH, so integration tests that skip on a laptop actually run: `docs/
  testing.md` records the runner reporting 2 skipped where a desk reports 55,
  and a correspondingly higher coverage total. The floors are deliberately left
  at the desk measurement — a floor lifted to the CI number is a floor no
  developer can meet before pushing.

## Related

- [`../../../../docs/assurance/README.md`](../../../../docs/assurance/README.md) — the index and the claim → enforcement table.
- [`../../05-GATES.md`](../../05-GATES.md) — the Gate A1/A2/A3 criteria.
- [`../../STATUS.md`](../../STATUS.md) — the phase record and the defect register.
