/**
 * WO-16 criterion 7 (behaviour) — "Web vitals are measured into the ring
 * buffer and rendered only behind `?debug=perf`."
 *
 * The bundle half of that criterion is `bundle.test.ts`. This file covers
 * the runtime half: the flag, the metric-to-record mapping, and the fact
 * that the three subscriptions land in the ring and nowhere else.
 *
 * `loadWebVitals()` is exercised against the REAL package once, so the
 * dynamic import is proved to resolve and to export the three functions
 * this module calls. Everything else uses the `load` seam, because a jsdom
 * environment has no `PerformanceObserver` and the library would correctly
 * report nothing.
 */

import { describe, expect, it, vi } from "vitest";

import { DiagnosticsRing } from "@/lib/diagnostics/ring";
import {
  PERF_DEBUG_PARAM,
  PERF_DEBUG_VALUE,
  TRACKED_VITALS,
  isPerfDebugEnabled,
  loadWebVitals,
  startWebVitals,
  vitalRecord,
  type VitalMetric,
  type WebVitalsModule,
} from "@/lib/diagnostics/vitals";

const AT = Date.UTC(2026, 7, 28, 9, 0, 0);

function metric(overrides: Partial<VitalMetric> = {}): VitalMetric {
  return {
    name: "LCP",
    value: 1839.7,
    rating: "good",
    id: "v5-1756370043120-1234567890123",
    navigationType: "navigate",
    ...overrides,
  };
}

describe("the ?debug=perf flag", () => {
  it("is the parameter and the value 04 §9.2 names", () => {
    expect(PERF_DEBUG_PARAM).toBe("debug");
    expect(PERF_DEBUG_VALUE).toBe("perf");
  });

  it.each([
    ["?debug=perf", true],
    ["debug=perf", true],
    ["?job=abc&debug=perf", true],
    ["?debug=perf&job=abc", true],
    ["?debug=PERF", false],
    ["?debug=1", false],
    ["?debugging=perf", false],
    ["?job=abc", false],
    ["", false],
  ])("%s -> %s", (search, expected) => {
    expect(isPerfDebugEnabled(search)).toBe(expected);
  });

  it("is false where there is no URL at all — a server render", () => {
    expect(isPerfDebugEnabled(null)).toBe(false);
    expect(isPerfDebugEnabled(undefined)).toBe(false);
  });
});

describe("one metric, as a ring record", () => {
  it("tracks the three 04 §9.2 names and no others", () => {
    expect([...TRACKED_VITALS]).toEqual(["LCP", "INP", "CLS"]);
  });

  it("rounds a millisecond metric to whole milliseconds", () => {
    const entry = vitalRecord(metric(), AT);
    expect(entry).toMatchObject({
      kind: "vital",
      event: "LCP",
      at: AT,
      jobId: null,
      failureKind: null,
      detail: { value: 1840, rating: "good", unit: "ms", navigationType: "navigate" },
    });
  });

  it("keeps CLS unitless and to three decimals, because it is not a duration", () => {
    const entry = vitalRecord(metric({ name: "CLS", value: 0.0213456, rating: "poor" }), AT);
    expect(entry.detail).toMatchObject({ value: 0.021, unit: "", rating: "poor" });
  });

  it("reports a missing navigation type as null rather than inventing one", () => {
    const entry = vitalRecord(metric({ navigationType: undefined }), AT);
    expect(entry.detail?.["navigationType"]).toBeNull();
  });

  it("does not carry a run id — a page metric is not about a run", () => {
    expect(vitalRecord(metric(), AT).jobId).toBeNull();
  });
});

describe("startWebVitals", () => {
  function fakeModule(): { module: WebVitalsModule; fire: (m: VitalMetric) => void } {
    const callbacks: ((m: VitalMetric) => void)[] = [];
    const subscribe = (callback: (m: VitalMetric) => void): void => {
      callbacks.push(callback);
    };
    return {
      module: { onLCP: subscribe, onINP: subscribe, onCLS: subscribe },
      fire: (m) => {
        for (const callback of callbacks) callback(m);
      },
    };
  }

  it("subscribes exactly the three metrics", async () => {
    const onLCP = vi.fn();
    const onINP = vi.fn();
    const onCLS = vi.fn();
    await startWebVitals({
      ring: new DiagnosticsRing(),
      load: () => Promise.resolve({ onLCP, onINP, onCLS }),
    });
    expect(onLCP).toHaveBeenCalledTimes(1);
    expect(onINP).toHaveBeenCalledTimes(1);
    expect(onCLS).toHaveBeenCalledTimes(1);
  });

  it("reports into the ring, and into nothing else", async () => {
    const ring = new DiagnosticsRing();
    const { module, fire } = fakeModule();
    await startWebVitals({ ring, load: () => Promise.resolve(module), now: () => AT });

    fire(metric({ name: "INP", value: 42.6, rating: "needs-improvement" }));
    // Three subscriptions share one callback in the fake, so one metric
    // arrives three times; what matters is that every arrival is a record.
    expect(ring.records()).toHaveLength(3);
    expect(ring.records()[0]).toMatchObject({
      kind: "vital",
      event: "INP",
      at: AT,
      detail: { value: 43, rating: "needs-improvement", unit: "ms" },
    });
  });

  it("defaults to the product's own ring and clock", async () => {
    const { module, fire } = fakeModule();
    const { diagnosticsRing } = await import("@/lib/diagnostics/ring");
    diagnosticsRing.clear();
    try {
      await startWebVitals({ load: () => Promise.resolve(module) });
      fire(metric({ name: "CLS", value: 0.01 }));
      expect(diagnosticsRing.records().length).toBeGreaterThan(0);
      expect(diagnosticsRing.records()[0]?.at).toBeGreaterThan(0);
    } finally {
      diagnosticsRing.clear();
    }
  });
});

describe("the dynamic import itself", () => {
  it("resolves the real package and exports the three subscribers", async () => {
    // THE assertion that the code-split point is real: `loadWebVitals` is
    // an `import()` and nothing else, and it returns a module with the
    // three functions this product calls. `bundle.test.ts` proves the
    // other half — that no route's first-load JS contains it.
    const web = await loadWebVitals();
    expect(typeof web.onLCP).toBe("function");
    expect(typeof web.onINP).toBe("function");
    expect(typeof web.onCLS).toBe("function");
  });
});
