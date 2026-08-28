/**
 * The four hooks in `lib/diagnostics/useDiagnostics.ts` — the seam WO-20
 * wires.
 *
 * The load-bearing test here is "subscribes once, however many times the
 * machine's context value is rebuilt". `JobRunContextValue` is a `useMemo`
 * over `state`, so it is a NEW object on every frame; an effect keyed on it
 * would tear down and re-subscribe each time, and because each subscribe
 * re-reads the baseline, the transition it re-subscribed to observe is
 * exactly the one that would be lost. The hook keys on `subscribe` and
 * `getSnapshot`, which the provider memoizes with an empty dependency
 * list.
 */

import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DiagnosticsRing } from "@/lib/diagnostics/ring";
import {
  readDebugPerf,
  useDebugPerf,
  useDiagnosticsRecorder,
  useDiagnosticsRecords,
  useWebVitals,
  type MachineSource,
} from "@/lib/diagnostics/useDiagnostics";
import type { VitalMetric, WebVitalsModule } from "@/lib/diagnostics/vitals";
import { initialJobState } from "@/lib/job/machine";
import type { JobState } from "@/lib/job/types";

import { act, render, renderHook, screen, waitFor } from "../support/render";

const AT = Date.UTC(2026, 7, 28, 9, 0, 0);

/** A hand-driven machine with the provider's own subscribe/getSnapshot. */
function fakeMachine(initial: JobState = initialJobState) {
  let snapshot = initial;
  const listeners = new Set<() => void>();
  const source: MachineSource = {
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
  };
  return {
    source,
    listeners,
    publish(next: JobState) {
      snapshot = next;
      for (const listener of listeners) listener();
    },
  };
}

describe("useDiagnosticsRecorder", () => {
  it("records what the machine moves through", () => {
    const ring = new DiagnosticsRing();
    const machine = fakeMachine();
    renderHook(() => {
      useDiagnosticsRecorder(machine.source, ring, () => AT);
    });

    act(() => {
      machine.publish({ ...initialJobState, phase: "attaching", jobId: "run-1" });
    });
    act(() => {
      machine.publish({ ...initialJobState, phase: "live", jobId: "run-1", connection: "open" });
    });

    expect(ring.records().map((entry) => `${entry.kind}:${entry.event}`)).toEqual([
      "transition:attaching",
      "connection:open",
      "transition:live",
    ]);
  });

  it("does not record the state that was already true at subscribe time", () => {
    const ring = new DiagnosticsRing();
    const machine = fakeMachine({ ...initialJobState, phase: "live", connection: "open" });
    renderHook(() => {
      useDiagnosticsRecorder(machine.source, ring, () => AT);
    });
    expect(ring.records()).toEqual([]);
  });

  it("subscribes ONCE however often the context value is rebuilt", () => {
    const ring = new DiagnosticsRing();
    const machine = fakeMachine();
    // The provider's shape: a new object every render, stable members.
    function Probe(): ReactNode {
      const [, force] = useState(0);
      useDiagnosticsRecorder(
        {
          subscribe: machine.source.subscribe,
          getSnapshot: machine.source.getSnapshot,
        },
        ring,
        () => AT,
      );
      return (
        <button
          type="button"
          onClick={() => {
            force((n) => n + 1);
          }}
        >
          rerender
        </button>
      );
    }

    render(<Probe />);
    expect(machine.listeners.size).toBe(1);
    for (let index = 0; index < 5; index += 1) {
      act(() => {
        screen.getByRole("button", { name: "rerender" }).click();
      });
    }
    expect(machine.listeners.size).toBe(1);

    // And a transition after all that re-rendering is still recorded.
    act(() => {
      machine.publish({ ...initialJobState, phase: "live" });
    });
    expect(ring.records()).toHaveLength(1);
  });

  it("unsubscribes on unmount", () => {
    const ring = new DiagnosticsRing();
    const machine = fakeMachine();
    const { unmount } = renderHook(() => {
      useDiagnosticsRecorder(machine.source, ring, () => AT);
    });
    expect(machine.listeners.size).toBe(1);
    unmount();
    expect(machine.listeners.size).toBe(0);
  });

  it("does nothing at all with no machine above it", () => {
    const ring = new DiagnosticsRing();
    expect(() =>
      renderHook(() => {
        useDiagnosticsRecorder(null, ring, () => AT);
      }),
    ).not.toThrow();
    expect(ring.records()).toEqual([]);
  });

  it("ignores a notification that did not change the snapshot", () => {
    const ring = new DiagnosticsRing();
    const machine = fakeMachine();
    renderHook(() => {
      useDiagnosticsRecorder(machine.source, ring, () => AT);
    });
    act(() => {
      for (const listener of machine.listeners) listener();
    });
    expect(ring.records()).toEqual([]);
  });

  it("defaults to the product's own ring and clock", () => {
    const machine = fakeMachine();
    renderHook(() => {
      useDiagnosticsRecorder(machine.source);
    });
    expect(machine.listeners.size).toBe(1);
  });
});

describe("useDiagnosticsRecords", () => {
  it("re-renders as the ring grows, and returns a stable value otherwise", () => {
    const ring = new DiagnosticsRing();
    let renders = 0;
    const { result } = renderHook(() => {
      renders += 1;
      return useDiagnosticsRecords(ring);
    });

    expect(result.current).toEqual([]);
    const before = renders;

    act(() => {
      ring.push({
        kind: "frame",
        event: "job_started",
        at: AT,
        jobId: null,
        phase: "live",
        from: null,
        failureKind: null,
        detail: null,
      });
    });

    expect(result.current).toHaveLength(1);
    expect(renders).toBeGreaterThan(before);
  });

  it("reads the shared buffer when none is passed", () => {
    const { result } = renderHook(() => useDiagnosticsRecords());
    expect(Array.isArray(result.current)).toBe(true);
  });
});

describe("useDebugPerf", () => {
  const original = window.location.search;

  afterEach(() => {
    window.history.replaceState(null, "", `${window.location.pathname}${original}`);
  });

  it("is false on an ordinary URL", () => {
    window.history.replaceState(null, "", "/c/abc");
    expect(renderHook(() => useDebugPerf()).result.current).toBe(false);
  });

  it("is true behind ?debug=perf", () => {
    window.history.replaceState(null, "", "/c/abc?debug=perf");
    expect(renderHook(() => useDebugPerf()).result.current).toBe(true);
  });

  it("subscribes to nothing, and unsubscribing from nothing is safe", () => {
    window.history.replaceState(null, "", "/c/abc?debug=perf");
    const { unmount } = renderHook(() => useDebugPerf());
    expect(() => {
      unmount();
    }).not.toThrow();
  });

  it("reads the same value on the server and on the first client render", () => {
    // One function serves as both snapshots, so the two cannot disagree.
    // With no `window` there is no URL, and the answer is false.
    window.history.replaceState(null, "", "/c/abc?debug=perf");
    expect(readDebugPerf()).toBe(true);
    const saved = globalThis.window;
    Reflect.deleteProperty(globalThis, "window");
    try {
      expect(readDebugPerf()).toBe(false);
    } finally {
      Object.defineProperty(globalThis, "window", {
        value: saved,
        configurable: true,
        writable: true,
      });
    }
  });
});

describe("useWebVitals", () => {
  function fakeModule(): { module: WebVitalsModule; count: () => number } {
    let subscriptions = 0;
    const subscribe = (_callback: (metric: VitalMetric) => void): void => {
      subscriptions += 1;
    };
    return {
      module: { onLCP: subscribe, onINP: subscribe, onCLS: subscribe },
      count: () => subscriptions,
    };
  }

  it("loads nothing while the flag is off", () => {
    const load = vi.fn(() => Promise.resolve(fakeModule().module));
    renderHook(() => {
      useWebVitals(false, { load, ring: new DiagnosticsRing() });
    });
    expect(load).not.toHaveBeenCalled();
  });

  it("loads once, and only once, however often it re-renders", async () => {
    const fake = fakeModule();
    const load = vi.fn(() => Promise.resolve(fake.module));
    const ring = new DiagnosticsRing();
    const { rerender } = renderHook(() => {
      useWebVitals(true, { load, ring });
    });

    await waitFor(() => {
      expect(fake.count()).toBe(3);
    });
    rerender();
    rerender();
    expect(load).toHaveBeenCalledTimes(1);
    expect(fake.count()).toBe(3);
  });
});
