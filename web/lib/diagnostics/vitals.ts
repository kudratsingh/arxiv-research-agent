// Web vitals, measured and not sent (04 §9.2 item 2, WO-16 c7).
//
// "`web-vitals` reports LCP/INP/CLS to the ring buffer and renders them
// only behind `?debug=perf`. Field p75 remains unavailable, and this
// document does not pretend otherwise."
//
// THE DYNAMIC IMPORT IS THE WHOLE POINT, and it is one line — the `import()`
// inside `loadWebVitals` below. Two things follow from it, and both are
// asserted rather than assumed:
//
//   - `web-vitals` is in NEITHER route's first-load JS.
//     `web/tests/diagnostics/bundle.test.ts` proves it twice: statically, by
//     walking the import graph from both route entries, and — when a
//     production build exists — against the real chunk union that
//     `scripts/route-budgets.mjs` derives from the Next manifests.
//   - The package is only fetched at all when the page was opened with
//     `?debug=perf`. Loading it unconditionally would keep the bundle
//     assertion technically true and make it worthless: every reader would
//     still download the library, just in a second request.
//
// IT IS A RUNTIME DEPENDENCY, exact-pinned, because it ships. A dynamically
// imported package is still shipped code; putting it in `devDependencies`
// would break `npm ci --omit=dev` in the Docker build for a reader who
// passes the flag.
//
// NOTHING HERE TRANSMITS. There is no `sendBeacon`, no `fetch`, no
// reporting endpoint and no third-party SDK — the metrics land in the same
// in-memory ring the frames do, and `web/tests/diagnostics/egress.test.ts`
// asserts that over the whole client module graph.

import { diagnosticsRing, type DiagnosticInput, type DiagnosticsRing } from "./ring";

/** `?debug=perf` — the query parameter and the value that arms it. */
export const PERF_DEBUG_PARAM = "debug";
export const PERF_DEBUG_VALUE = "perf";

/** The three metrics 04 §9.2 names. FCP and TTFB are not collected. */
export const TRACKED_VITALS = ["LCP", "INP", "CLS"] as const;
export type TrackedVital = (typeof TRACKED_VITALS)[number];

/**
 * Is the performance debug flag set?
 *
 * Takes the search string rather than reading `window` so it is a pure
 * function with a test that needs no DOM, and so a server render — where
 * there is no `window` — calls it with `""` and gets `false`.
 */
export function isPerfDebugEnabled(search: string | null | undefined): boolean {
  if (typeof search !== "string" || search === "") return false;
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return params.get(PERF_DEBUG_PARAM) === PERF_DEBUG_VALUE;
}

/**
 * The subset of a `web-vitals` metric this product reads.
 *
 * Declared structurally rather than imported as a type, so `import type
 * { Metric } from "web-vitals"` does not appear anywhere — a type-only
 * import is erased at build time and would be harmless, but it would also
 * make `bundle.test.ts`'s "no static reference to web-vitals outside the
 * dynamic import" assertion softer than it should be.
 */
export interface VitalMetric {
  name: string;
  value: number;
  rating: string;
  id: string;
  navigationType?: string;
}

/** The three subscription functions this module calls, and nothing else. */
export interface WebVitalsModule {
  onLCP: (callback: (metric: VitalMetric) => void) => void;
  onINP: (callback: (metric: VitalMetric) => void) => void;
  onCLS: (callback: (metric: VitalMetric) => void) => void;
}

/**
 * THE dynamic import. The only reference to the package in the product.
 *
 * Written as a function so the call site is a real code-split point and so
 * tests can substitute a loader without mocking the module registry.
 */
export function loadWebVitals(): Promise<WebVitalsModule> {
  return import("web-vitals") as Promise<WebVitalsModule>;
}

/**
 * One metric, as a ring record.
 *
 * `value` is rounded to the precision the metric is read at — CLS is
 * unitless and small, LCP and INP are milliseconds — and the rating is the
 * library's own word, not a re-judgement.
 */
export function vitalRecord(metric: VitalMetric, at: number): DiagnosticInput {
  const unitless = metric.name === "CLS";
  return {
    kind: "vital",
    event: metric.name,
    at,
    jobId: null,
    phase: "idle",
    from: null,
    failureKind: null,
    detail: {
      value: unitless
        ? Math.round(metric.value * 1000) / 1000
        : Math.round(metric.value),
      rating: metric.rating,
      unit: unitless ? "" : "ms",
      navigationType: metric.navigationType ?? null,
    },
  };
}

export interface StartWebVitalsOptions {
  /** Where the metrics land. Defaults to the product's one ring. */
  ring?: DiagnosticsRing;
  /** Clock seam. */
  now?: () => number;
  /** Loader seam. Defaults to `loadWebVitals`, i.e. the dynamic import. */
  load?: () => Promise<WebVitalsModule>;
}

/**
 * Subscribe LCP, INP and CLS into the ring. Resolves once subscribed.
 *
 * Idempotence is the CALLER's problem and `useWebVitals` handles it: the
 * library dedupes nothing, so subscribing twice reports twice.
 */
export async function startWebVitals(
  options: StartWebVitalsOptions = {},
): Promise<void> {
  const ring = options.ring ?? diagnosticsRing;
  const now = options.now ?? (() => Date.now());
  const load = options.load ?? loadWebVitals;

  const web = await load();
  const report = (metric: VitalMetric): void => {
    ring.push(vitalRecord(metric, now()));
  };
  web.onLCP(report);
  web.onINP(report);
  web.onCLS(report);
}
