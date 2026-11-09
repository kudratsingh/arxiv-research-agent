# Offline task-bound repair verification

Application commit: `03c0140bd133eb1208050b7004b499788b8a6f18`. Offline revision: `86721e0cade1c13c4a135530f0f11fc93ce265fa862d64cfdb2c01b75180fc34`.
This is software verification, not new provider evidence, human qualification or paid authorization.

Frontend/browser checks used the locked build at application `a7104be7`; the
final `03c0140b` follow-up changes only backend schema canonicalization and its
regressions. Frontend source is byte-identical (`git diff a7104be7 03c0140b -- web`
is empty). Final full Python coverage runs on `03c0140b`.

| Check | Actual result |
|---|---|
| Full Python `make test-cov-diff` | 6912 passed; 54 inherited skips; 53 separate E2E deselections; total 94.59%; patch 97% |
| Focused harness/policy/production/read-model/canonical round trips | 140 passed |
| Harness and policy after tier fix | 64 passed |
| Both frontend result components | 53 passed |
| Full frontend, locked dependencies | 4285 passed |
| Lint / mypy / typecheck / OpenAPI generated types | Passed; mypy198 source files |
| Production build / route budgets | Passed, no ceilings changed |
| Chromium | 24 render/reload controls, dark/light × desktop/390px × three dispositions × two viewers; zero serious/critical axe findings and console exceptions |
| Real PostgreSQL | Disposable schemas; HTTP preview/submission/check/reload, ownership, sealed-context drift and quarantined read model verified |
| Scripted workflow E2E | 53 passed |
| Research simulation | 20/20, USD0 |
| Registry parity | 260 objects, zero mismatches |
| Documentation/hygiene | 95 passed |

## Package floors and module coverage

```json
{
  "api": {
    "floor": 86,
    "actual_rounded": "88"
  },
  "agents": {
    "floor": 92,
    "actual_rounded": "96"
  },
  "security": {
    "floor": 97,
    "actual_rounded": "100"
  },
  "eval": {
    "floor": 91,
    "actual_rounded": "95"
  }
}
```

```text
Name                                 Stmts   Miss Branch BrPart  Cover   Missing
--------------------------------------------------------------------------------
src/workspace/assistance_policy.py      88      2     30      0    98%   158-159
src/workspace/d5_results.py             57      3     14      1    94%   42, 78-79
--------------------------------------------------------------------------------
TOTAL                                  145      5     44      1    97%
```

## Dependency and diagnostic record

The inherited copied install had Next16.3.3, differing from lockfile16.4.4.
An isolated `npm ci` corrected that without lockfile/dependency changes. Final
frontend/build/browser results above use16.4.4. Earlier captures and logs remain
under `outputs/d5/full-abstention-v7/diagnostic-*`.

Four early Python coverage attempts were interrupted for implementation changes.
A complete prepublication run then passed6907 tests but failed two mandatory
harness checks because the new pure module lacked its unit-tier declaration.
The declaration was added; harness/policy64 passed; the final full gate above
passed without skipped assertions, changed floors or omitted inputs. The initial
frontend attempt also encountered sandbox-denied loopback health servers and a
concurrent build; the final suite ran after build with loopback access/two workers.

## Controls and preservation

Captured safety output and comparison/null reason variants are rejected before
checker dispatch. Clean full abstention has zero claims; archived retrieval notes
and the normal-answer projection pass local/wire validation and existing evidence
checks. These projections/verdicts are synthetic controls, not new provider results.
The full-only wire schema has no claims or claim-reference properties. Mandatory
checking, the single repair/recheck, unselected-evidence rejection and residual
unsupported/prose rejection remain enforced. Both read models and result viewers
preserve the disposition. First required-context profile: vehicle/controller safety;
other assessment domains require declared profiles. Task intent is explicit, not
claimed automatic classification of arbitrary questions.

Browser API responses were intercepted; database durability is established by the
separate PG tests. Representative [mobile full abstention](screenshots/assistance-safety-light-390.png)
and [quarantined comparison notes](screenshots/qualification-retrieval-dark-1440.png).

[PRESERVATION.json](PRESERVATION.json) binds identical before/after read-only census
and hashes:30 jobs,61 Messages,81 counts,USD1.779493 estimated,pending/unknown0.
No Stage D grant, new authorization/provider/count contact/spend, human label,
owner3137/review3178 change, merge or deployment. Original packet/results/scorer
and Codex-attributed synthetic exports remain untouched. The old eight-case
machine review remains FAIL; the structural repair does not retrospectively accept it.

The [separate proposal](../../FULL-ABSTENTION-VALIDATION-PROPOSAL.md) is unexecuted;
it needs a new frozen input/analysis binding before requesting paid approval.
Remote CI is reported separately against the exact published head.
