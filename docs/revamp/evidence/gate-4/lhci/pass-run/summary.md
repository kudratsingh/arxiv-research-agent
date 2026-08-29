# Lighthouse CI — §8.2 assertion run

Produced by `node scripts/lhci-run.mjs` (WO-29). Every number below is a **local lab measurement** against the seeded Compose stack — a Lighthouse simulated-throttling run on one machine, not field p75. See `docs/revamp/evidence/gate-4/lhci/README.md` §1.

- Generated: `2026-08-29T15:55:54.458Z`
- Base URL: `http://127.0.0.1:13295`
- Assertions evaluated: **70**

## mobile-412 — Mobile, 412 x 823

Result: **PASS** (`lhci autorun` exit 0)

| State | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `/` | 100 | 100 | 100 | 1.26 s | 14 ms | 0.00000 | pass |
| `/c/baseline-empty` | 98 | 100 | 100 | 1.82 s | 29 ms | 0.00000 | pass |
| `/c/baseline-populated` | 100 | 100 | 100 | 1.37 s | 14 ms | 0.00000 | pass |
| `/c/baseline-populated?job=baseline-plan-review` | 100 | 100 | 100 | 1.32 s | 67 ms | 0.00000 | pass |

Per-run spread (median is what the assertions were evaluated against):

| State | LCP runs (ms) | TBT runs (ms) | CLS runs | bf-cache reasons |
|---|---|---|---|---|
| `/` | 1244, 1262, 1389 | 40, 14, 10 | 0.00000, 0.00000, 0.00000 | — |
| `/c/baseline-empty` | 1388, 1823, 2722 | 173, 12, 29 | 0.00000, 0.00000, 0.00000 | — |
| `/c/baseline-populated` | 1406, 1366, 1271 | 14, 13, 14 | 0.00000, 0.00000, 0.00061 | — |
| `/c/baseline-populated?job=baseline-plan-review` | 1404, 1310, 1317 | 66, 76, 67 | 0.00000, 0.00000, 0.00000 | — |

## desktop-1350 — Desktop, 1350 x 940

Result: **PASS** (`lhci autorun` exit 0)

| State | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `/` | 100 | 100 | 100 | 0.36 s | 0 ms | 0.00000 | **fail** |
| `/c/baseline-empty` | 100 | 100 | 100 | 0.34 s | 0 ms | 0.00000 | **fail** |
| `/c/baseline-populated` | 99 | 100 | 100 | 0.82 s | 0 ms | 0.00000 | **fail** |
| `/c/baseline-populated?job=baseline-plan-review` | 100 | 100 | 100 | 0.34 s | 0 ms | 0.00013 | **fail** |

Per-run spread (median is what the assertions were evaluated against):

| State | LCP runs (ms) | TBT runs (ms) | CLS runs | bf-cache reasons |
|---|---|---|---|---|
| `/` | 356, 565, 332 | 0, 0, 0 | 0.00000, 0.00000, 0.00000 | MainResourceHasCacheControlNoStore (Not actionable); JsNetworkRequestReceivedCacheControlNoStoreResource (Not actionable) |
| `/c/baseline-empty` | 337, 332, 336 | 0, 0, 0 | 0.00000, 0.00000, 0.00000 | MainResourceHasCacheControlNoStore (Not actionable); JsNetworkRequestReceivedCacheControlNoStoreResource (Not actionable) |
| `/c/baseline-populated` | 823, 821, 823 | 0, 0, 0 | 0.00000, 0.00000, 0.00000 | MainResourceHasCacheControlNoStore (Not actionable); JsNetworkRequestReceivedCacheControlNoStoreResource (Not actionable) |
| `/c/baseline-populated?job=baseline-plan-review` | 569, 333, 344 | 0, 0, 0 | 0.00013, 0.00013, 0.00013 | MainResourceHasCacheControlNoStore (Not actionable); JsNetworkRequestReceivedCacheControlNoStoreResource (Not actionable) |

## mobile-320 — Mobile, 320 x 568 (04 §8.3 narrow strip)

Result: **PASS** (`lhci autorun` exit 0)

| State | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `/` | 100 | 100 | 100 | 1.36 s | 7 ms | 0.00000 | pass |
| `/c/baseline-populated` | 100 | 100 | 100 | 1.81 s | 7 ms | 0.00000 | pass |

Per-run spread (median is what the assertions were evaluated against):

| State | LCP runs (ms) | TBT runs (ms) | CLS runs | bf-cache reasons |
|---|---|---|---|---|
| `/` | 1213, 2342, 1362 | 7, 24, 4 | 0.00000, 0.00000, 0.00000 | — |
| `/c/baseline-populated` | 1215, 2484, 1813 | 7, 8, 6 | 0.00000, 0.00000, 0.00000 | — |

