# v8r4b final offline verification

Application/source **68c23441cdc351cfb4938f2a01b58597423aca7c**. Packet
**1429b39296792b8bc3d5530d28bcc56600048b149310fc10df30c2ee6048a7a7**.
Zero real Messages/count contacts, new spend, live cap activation or stage grants.

| Check actually run on corrected source | Actual result |
|---|---|
| Focused amendment/predecessor/real-case fixture suite | **142 passed**, 92.18 s |
| `make test-cov-diff` | **6871 passed, 54 inherited skips, 53 separate-tier deselected**, exit 0; 1244.15 s |
| Total / patch coverage | **94.59% / 97%**; 89% total and 90% patch floors preserved |
| New capacity module line coverage | **96.46%** |
| Existing package floors | API88≥86 / agents96≥92 / security100≥97 / eval95≥91 |
| Global `ruff check .` | Passed |
| Strict mypy | **197 source files**, no issues |
| Workflow e2e tier | **53 passed**, 6925 deselected, 17.00 s |
| Scripted research simulation | **20/20 succeeded, USD 0.0000** |
| Registry parity | **260 objects / 0 mismatches**; no object changed |
| Packet and producer verification | Passed against corrected source and dependency bindings |
| Initial requests / scopes / capacity proposal / frozen field and preservation audit | Passed; [binding audit](BINDING-AUDIT.json) |
| Corrected complete A–D mock replay | **14 new synthetic funded jobs / 44 mocked Messages / 45 mocked counts**; cumulative **34 / 79 / 99** |
| Stage separation | Capacity alone: A owner approval required; B/C/D refused until each separate fixture grant |
| New cap boundaries | Job34/count99 admitted in replay; job35/count100 refused by production guard |
| Old cap boundaries | Job24/count80 admitted and job25/count81 refused in focused production admission tests |
| Insufficient-evidence workflow | Zero final claims, `application_context_required`; draft/check/repair/check complete |
| Historical financial preservation | Complete original subset census unchanged; source actual ledger remains **20/35/54/USD0.904053**, pending/unknown0 |
| Human quality / provider compatibility | **HOLD / UNMEASURED**, no labels or qualification credit from fixtures |

[Replay receipt](REPLAY-RECEIPT.json), [synthetic case census](CASE-CENSUS.json),
[log SHA-256 bindings](LOCAL-LOG-BINDINGS.json), [source ledger audit](LEDGER-AUDIT.json).
The permanently disabled replay database is `workspace_d5_capacity_replay_20261108_b1`.
The identical initial count body has no matching receipt among54 completed
historical counts; a fresh A remains necessary. Fake count100 values are not
model token measurements. Wire-valid fixtures do not establish remote schema
acceptance, whole-claim support or checker reliability.

## Preserved preparation failure

The earlier unapproved v8r4 candidate remains byte-identical with its original
mock report. Its insufficient-case matcher omitted the v8 prefix, so it emitted
claims and no abstention. The frozen-case regression reproduced **1 failed /
1 passed** before correction; the initial sandbox process-cleanup warning is also
retained. The corrected **142-test** suite ran cleanly with process permission.
The new replay explicitly asserts raw zero claims, the bounded abstention code
and a rendered abstention; the failure cannot be hidden by a ready state.
[Original diagnostic](../qualification-v8r4/INSUFFICIENT-FIXTURE-DIAGNOSTIC.json).
No real held-out output, source selection, schema or quality threshold changed.
Original v7r2 stays3/8; the completed four-probe diagnostic is separate. No real
review or historical paid job is attached to this new packet.

## Publication and remote CI

These are local results for the verified application source. The review branch
publication adds documentation/artifacts without changing source, helper or tests.
Exact published-head CI is checked separately and identified in the final handoff
and local `outputs/d5/capacity-extension/PUBLICATION.json`. The predecessor7518b760
CI9/9 is preserved historical evidence, not asserted as this branch's CI.
No PR, merge, deployment, recurrence, notification or everyday generation enabled.
