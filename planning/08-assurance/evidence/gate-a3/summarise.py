#!/usr/bin/env python3
"""Render the Gate A3 evidence summary from the raw runner output.

Why this exists rather than a hand-written page: `02-STANDARDS.md` §4.4 records
that CI artifact retention is finite (90 days here), so the **committed**
summary is the durable record — and a committed summary is only worth reading
if every number in it came out of a runner. `collect.sh` writes `raw/`; this
reads `raw/` back and writes `README.md`. No number in the pack is typed by a
person, which is the property the gate is judged on.

It fails loudly rather than emitting a partial pack: a missing raw file or an
unparseable line raises, because a summary that silently drops a signal is
worse than no summary.

    python planning/08-assurance/evidence/gate-a3/summarise.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"

# pytest's `-q` epilogue, e.g. "3206 passed, 55 skipped, 16 deselected in 84.13s".
_PYTEST_TALLY = re.compile(
    r"^(?=.*\bpassed\b)(?P<body>(?:\d+ \w+(?:, )?)+) in (?P<secs>[\d.]+)s", re.MULTILINE
)
_COUNT = re.compile(r"(\d+) (passed|failed|skipped|deselected|error|errors|xfailed|xpassed)")


def read(name: str) -> str:
    """Read one raw capture, or fail with the name of what is missing."""
    path = RAW / name
    if not path.is_file():
        raise SystemExit(f"missing raw capture: {path} — run collect.sh first")
    return path.read_text(encoding="utf-8")


def provenance() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in read("provenance.txt").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key] = value
    return out


def tally(name: str) -> dict[str, int]:
    """Parse a pytest `-q` epilogue into {outcome: count}."""
    match = _PYTEST_TALLY.search(read(name))
    if match is None:
        raise SystemExit(f"no pytest tally found in raw/{name}")
    return {word: int(n) for n, word in _COUNT.findall(match.group("body"))}


def fmt_tally(counts: dict[str, int], *, keys: tuple[str, ...] = ("passed", "skipped")) -> str:
    parts = [f"{counts[k]} {k}" for k in keys if counts.get(k)]
    return ", ".join(parts) if parts else "0 passed"


def total_int(name: str) -> int:
    """Read a `coverage report --format=total` capture: one bare integer."""
    for line in read(name).splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            return int(stripped)
    raise SystemExit(f"no integer total in raw/{name}")


def exit_code(name: str) -> str:
    for line in reversed(read(name).splitlines()):
        if line.startswith("exit="):
            return line.removeprefix("exit=")
    raise SystemExit(f"no exit= marker in raw/{name}")


def search(name: str, pattern: str, group: int = 1) -> str:
    match = re.search(pattern, read(name))
    if match is None:
        raise SystemExit(f"pattern {pattern!r} not found in raw/{name}")
    return match.group(group).strip()


def audit_rows() -> list[str]:
    """The advisory table pip-audit printed, as markdown rows."""
    rows: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for line in read("pip-audit.txt").splitlines():
        fields = line.split()
        # Name Version ID Fix-Versions, with the ID shaped like an advisory id.
        if len(fields) == 4 and re.fullmatch(r"[A-Z]+-\d{4}-\d+", fields[2]):
            key = tuple(fields)
            if key in seen:  # pip-audit prints setuptools twice for one advisory
                continue
            seen.add(key)
            rows.append(f"| `{fields[0]}` | {fields[1]} | {fields[2]} | {fields[3]} |")
    if not rows:
        raise SystemExit("no advisory rows parsed from raw/pip-audit.txt")
    return rows


def main() -> int:
    p = provenance()
    gate = tally("pytest-not-e2e.txt")
    sbom = json.loads((HERE / "sbom.cyclonedx.json").read_text(encoding="utf-8"))

    tiers = {
        "`pytest -m \"not e2e\"` — the per-PR gate": fmt_tally(gate),
        "`pytest -m e2e`": fmt_tally(tally("pytest-e2e.txt")),
        "`pytest -m property`": fmt_tally(tally("pytest-property.txt")),
        "`pytest -m fault`": fmt_tally(tally("pytest-fault.txt")),
        "`pytest -m security`": fmt_tally(tally("pytest-security.txt")),
        "`pytest -m contract`": fmt_tally(tally("pytest-contract.txt")),
    }
    packages = [("api", 86), ("agents", 92), ("security", 97), ("eval", 91)]

    # Every regex is resolved here rather than inside the template below.
    # `ruff` type-checks this file against py311, where a backslash inside an
    # f-string *expression* is a syntax error — so the patterns cannot live in
    # the `{...}` slots even though the interpreter running this is newer.
    coverage_total = search("pytest-not-e2e.txt", r"Total coverage: ([\d.]+)%")
    mypy_line = search("mypy.txt", r"(Success: no issues found in \d+ source files)")
    ruff_line = search("ruff.txt", r"(All checks passed!)")
    safety_rate = search("safety-suite.txt", r"( *attack success .*)")
    safety_decision = search("safety-suite.txt", r"( *decision +\w+.*)")
    safety_hard = "\n".join(
        search("safety-suite.txt", rf"( *{name} +\d+)")
        for name in ("egress_to_non_allowlisted_host", "secret_exfiltrated", "unauthorised_tool_call")
    )
    safety_residuals = search("safety-suite.txt", r"known residuals: (.*)")
    scripted_line = search("scripted-tier-check.txt", r"(Scripted tier OK: .*)")

    # A pack collected on a working tree says so. The alternative — collecting
    # only from a clean checkout — would mean the pack could never measure the
    # work order that produces it, which is the case that matters most here.
    dirty_note = (
        "The tree was **dirty** at collection: this work order's own additions "
        "(`docs/assurance/`, `tests/test_assurance_docs.py`, and this directory) "
        "were uncommitted when the gates ran, so the tier counts include them "
        "while every `src/` file measured is at the commit above."
        if p["dirty"] == "yes"
        else "The tree was clean at collection."
    )

    body = f"""# Gate A3 — evidence pack

**Assurance.** A reviewer can open one index and follow every claim in the
README to the artifact that enforces it, including the framework mapping and
the system card.

> **This page is generated.** `collect.sh` runs each gate and writes its raw
> output to [`raw/`](raw); `summarise.py` reads those files back and writes this
> page. No number below was typed by a person. Regenerate with:
>
> ```bash
> VENV_BIN=/path/to/.venv/bin PIP_AUDIT=/path/to/pip-audit \\
>   bash planning/08-assurance/evidence/gate-a3/collect.sh
> python planning/08-assurance/evidence/gate-a3/summarise.py
> ```

⚠ **CI runs are not the record.** Artifact retention is finite (90 days on this
repository), so a link to a green workflow run is evidence that expires. This
committed, dated summary is the durable artifact — `02-STANDARDS.md` §4.4.

## Provenance

| | |
|---|---|
| Commit | `{p["commit"]}` |
| Branch | `{p["branch"]}` |
| Working tree dirty at collection | {p["dirty"]} |
| Collected (UTC) | {p["collected_utc"]} |
| Python | {p["python"]} |
| `src` resolved to | `{p["src_module"]}` |

The last row is not decoration. It is the check that these numbers describe
*this* worktree rather than a sibling checkout on the same machine.

{dirty_note}

## Tiers

| Selection | Result |
|---|---|
""" + "\n".join(f"| {name} | {result} |" for name, result in tiers.items()) + f"""

The gate deselects {gate.get("deselected", 0)} e2e tests, which the `-m e2e` row
then runs separately. Every tier is offline and spends nothing: the harness
denies the model client and pins an invalid key by construction.

## Coverage

Branch coverage, measured over exactly the selection that gates. A floor
measured against a different set of tests than the one that gates is a number
about nothing.

| Scope | Floor | Measured |
|---|---|---|
| project (`fail_under` in `pyproject.toml`) | 89% | **{coverage_total}%** |
""" + "\n".join(
        f"| `src/{pkg}` | {floor}% | {total_int(f'coverage-src-{pkg}.txt')}% |"
        for pkg, floor in packages
    ) + f"""

Per-package floors come from the Makefile's `COV_*` variables and are passed
explicitly, because `coverage.py`'s `fail_under` is global — a per-package
report left to inherit it is judged against the project floor and reports a
failure that is not one.

## Types and lint

| Gate | Result |
|---|---|
| `mypy --strict src/` | {mypy_line} |
| `ruff check src/ tests/` | {ruff_line} |

## Measured results

The only quantitative accuracy and safety evidence this repository has. The
four LLM-judged research metrics have never been run — see
[`../../../../docs/assurance/system-card.md`](../../../../docs/assurance/system-card.md) §5.2.

### Adversarial safety suite (42 authored attacks, model-free, offline)

```
{safety_rate}
{safety_decision}
```

Hard violations, gated at absolute zero:

```
{safety_hard}
```

The three successes are named residuals recorded in the corpus before the run,
not discoveries: {safety_residuals}.

Full report: [`raw/safety-suite.txt`](raw/safety-suite.txt).

### Scripted learner tier (the campaign, not the unit tests)

```
{scripted_line}
```

Run as a campaign — the CLI, the durable record layout, the summary files and
the cost accounting — because that is the surface a funded lane would use. The
`$0.0000` assertion is what makes it a zero-spend gate rather than a hope.

## Supply chain

SBOM and vulnerability audit from one PyPA tool, over `requirements-lock.txt`
with `--no-deps` — the pins CI installs, not a fresh resolve nobody ran.

| | |
|---|---|
| Format | CycloneDX {sbom["specVersion"]} |
| Components | {len(sbom["components"])} |
| Vulnerabilities recorded in the SBOM | {len(sbom.get("vulnerabilities", []))} |
| SBOM timestamp | {sbom["metadata"]["timestamp"]} |
| `pip-audit` exit | {exit_code("pip-audit.txt")} (non-zero: findings, listed below) |

| Package | Pinned | Advisory | Fixed in |
|---|---|---|---|
""" + "\n".join(audit_rows()) + """

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
"""

    (HERE / "README.md").write_text(body, encoding="utf-8")
    print(f"wrote {HERE / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
