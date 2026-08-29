# Lighthouse CI — §8.2 assertion run

Produced by `node scripts/lhci-run.mjs` (WO-29). Every number below is a **local lab measurement** against the seeded Compose stack — a Lighthouse simulated-throttling run on one machine, not field p75. See `docs/revamp/evidence/gate-4/lhci/README.md` §1.

- Generated: `2026-08-29T17:02:48.503Z`
- Base URL: `http://127.0.0.1:13295`
- Assertions evaluated: **80**

## mobile-412 — Mobile, 412 x 823

Result: **PASS** (`lhci autorun` exit 0)

| State | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `/` | 100 | 100 | 100 | 1.36 s | 6 ms | 0.00000 | pass |
| `/c/baseline-empty` | 100 | 100 | 100 | 1.37 s | 6 ms | 0.00000 | pass |
| `/c/baseline-populated` | 100 | 100 | 100 | 1.37 s | 8 ms | 0.00061 | pass |
| `/c/baseline-populated?job=baseline-plan-review` | 100 | 100 | 100 | 1.39 s | 10 ms | 0.00000 | pass |

⚠️ on TBT means the measured median is past 04 §8.2's ratified ceiling of 150 ms without breaching the runner ceiling the run is gated on. It is a warning, not a failure — see `web/lighthouserc.json`'s "TOTAL BLOCKING TIME" comment.

Per-run spread (median is what the assertions were evaluated against):

| State | LCP runs (ms) | TBT runs (ms) | CLS runs | bf-cache reasons |
|---|---|---|---|---|
| `/` | 1224, 1372, 1363 | 15, 5, 6 | 0.00000, 0.00000, 0.00000 | — |
| `/c/baseline-empty` | 1363, 1384, 1366 | 6, 7, 5 | 0.00000, 0.00000, 0.00000 | — |
| `/c/baseline-populated` | 1360, 1408, 1366 | 6, 9, 8 | 0.00061, 0.00000, 0.00061 | — |
| `/c/baseline-populated?job=baseline-plan-review` | 1391, 1362, 1970 | 20, 6, 10 | 0.00000, 0.00000, 0.00000 | — |

## desktop-1350 — Desktop, 1350 x 940

Result: **PASS** (`lhci autorun` exit 0)

| State | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `/` | 100 | 100 | 100 | 0.35 s | 0 ms | 0.00000 | **fail** |
| `/c/baseline-empty` | 100 | 100 | 100 | 0.45 s | 0 ms | 0.00000 | **fail** |
| `/c/baseline-populated` | 100 | 100 | 100 | 0.82 s | 0 ms | 0.00000 | **fail** |
| `/c/baseline-populated?job=baseline-plan-review` | 100 | 100 | 100 | 0.34 s | 0 ms | 0.00013 | **fail** |

⚠️ on TBT means the measured median is past 04 §8.2's ratified ceiling of 50 ms without breaching the runner ceiling the run is gated on. It is a warning, not a failure — see `web/lighthouserc.json`'s "TOTAL BLOCKING TIME" comment.

Per-run spread (median is what the assertions were evaluated against):

| State | LCP runs (ms) | TBT runs (ms) | CLS runs | bf-cache reasons |
|---|---|---|---|---|
| `/` | 343, 553, 352 | 0, 0, 0 | 0.00000, 0.00000, 0.00000 | MainResourceHasCacheControlNoStore (Not actionable); JsNetworkRequestReceivedCacheControlNoStoreResource (Not actionable) |
| `/c/baseline-empty` | 740, 338, 454 | 0, 0, 0 | 0.00000, 0.00000, 0.00000 | MainResourceHasCacheControlNoStore (Not actionable); JsNetworkRequestReceivedCacheControlNoStoreResource (Not actionable) |
| `/c/baseline-populated` | 783, 820, 819 | 0, 0, 0 | 0.00000, 0.00000, 0.00000 | MainResourceHasCacheControlNoStore (Not actionable); JsNetworkRequestReceivedCacheControlNoStoreResource (Not actionable) |
| `/c/baseline-populated?job=baseline-plan-review` | 337, 460, 335 | 0, 0, 0 | 0.00013, 0.00013, 0.00013 | MainResourceHasCacheControlNoStore (Not actionable); JsNetworkRequestReceivedCacheControlNoStoreResource (Not actionable) |

## mobile-320 — Mobile, 320 x 568 (04 §8.3 narrow strip)

Result: **PASS** (`lhci autorun` exit 0)

| State | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `/` | 100 | 100 | 100 | 1.36 s | 8 ms | 0.00000 | pass |
| `/c/baseline-populated` | 100 | 100 | 100 | 1.42 s | 33 ms | 0.00000 | pass |

⚠️ on TBT means the measured median is past 04 §8.2's ratified ceiling of 150 ms without breaching the runner ceiling the run is gated on. It is a warning, not a failure — see `web/lighthouserc.json`'s "TOTAL BLOCKING TIME" comment.

Per-run spread (median is what the assertions were evaluated against):

| State | LCP runs (ms) | TBT runs (ms) | CLS runs | bf-cache reasons |
|---|---|---|---|---|
| `/` | 1227, 1365, 1367 | 10, 8, 7 | 0.00000, 0.00000, 0.00000 | — |
| `/c/baseline-populated` | 1415, 1820, 1379 | 52, 25, 33 | 0.00000, 0.00000, 0.00000 | — |

