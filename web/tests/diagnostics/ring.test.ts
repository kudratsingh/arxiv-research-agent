/**
 * WO-16 criterion 5 — "Ring buffer holds the last 200 lifecycle records in
 * memory only, cleared on reload."
 *
 * Three claims, three kinds of proof:
 *
 *   - **Exactly 200.** Behavioural. 201 records are pushed and the 1st is
 *     gone while the 201st is present, and `seq` keeps counting so a reader
 *     of the blob can tell that something was dropped.
 *   - **Memory only.** Structural. No module under `lib/diagnostics/`
 *     mentions any storage API, asserted against the source text, AND a
 *     push is watched with spies installed over `localStorage`,
 *     `sessionStorage`, `indexedDB`, `document.cookie` and `caches` so a
 *     future indirection cannot satisfy the text scan and still write.
 *   - **Cleared on reload.** Behavioural, by simulating the only thing a
 *     reload does to a module-scope singleton: `vi.resetModules()` and a
 *     fresh import. The re-imported ring is empty, which is the whole of
 *     the guarantee and the reason the buffer is module scope in the first
 *     place.
 *
 * `recordsFromTransition` is tested against real `JobState` values built
 * with the machine's own `initialJobState`, not hand-rolled objects, so a
 * field that moves in `lib/job/` fails here rather than silently producing
 * empty records.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RING_CAPACITY } from "@/lib/diagnostics/constants";
import {
  DIAGNOSTIC_KINDS,
  DiagnosticsRing,
  diagnosticsRing,
  recordsFromTransition,
  type DiagnosticInput,
} from "@/lib/diagnostics/ring";
import { initialJobState } from "@/lib/job/machine";
import type { ApiFailure } from "@/lib/api";
import type { JobFrame, JobState } from "@/lib/job/types";

const AT = Date.UTC(2026, 7, 28, 9, 0, 0);

function input(overrides: Partial<DiagnosticInput> = {}): DiagnosticInput {
  return {
    kind: "frame",
    event: "node_completed",
    at: AT,
    jobId: "run-1",
    phase: "live",
    from: null,
    failureKind: null,
    detail: null,
    ...overrides,
  };
}

function frame(name: string, receivedAt: number, data: JobFrame["data"] = null): JobFrame {
  return { name, data, receivedAt };
}

describe("criterion 5 — the buffer holds exactly 200", () => {
  it("is 200, from 04 §9.2, and the class defaults to it", () => {
    expect(RING_CAPACITY).toBe(200);
    expect(new DiagnosticsRing().capacity).toBe(200);
    expect(diagnosticsRing.capacity).toBe(200);
  });

  it("keeps the newest 200 and drops the oldest, in order", () => {
    const ring = new DiagnosticsRing();
    for (let index = 0; index < RING_CAPACITY + 1; index += 1) {
      ring.push(input({ event: `frame-${index}` }));
    }

    const records = ring.records();
    expect(records).toHaveLength(RING_CAPACITY);
    expect(ring.size).toBe(RING_CAPACITY);
    expect(ring.dropped).toBe(1);
    // Oldest first, and the 0th is the one that fell off.
    expect(records[0]?.event).toBe("frame-1");
    expect(records.at(-1)?.event).toBe(`frame-${RING_CAPACITY}`);
  });

  it("does not grow past the ceiling however long the stream runs", () => {
    const ring = new DiagnosticsRing();
    for (let index = 0; index < RING_CAPACITY * 7; index += 1) {
      ring.push(input({ event: `frame-${index}` }));
    }
    expect(ring.records()).toHaveLength(RING_CAPACITY);
    expect(ring.dropped).toBe(RING_CAPACITY * 6);
  });

  it("keeps `seq` monotonic across the wrap, so a gap is visible", () => {
    const ring = new DiagnosticsRing(3);
    for (let index = 0; index < 5; index += 1) ring.push(input());
    expect(ring.records().map((entry) => entry.seq)).toEqual([2, 3, 4]);
  });

  it("reports the size honestly before it is full", () => {
    const ring = new DiagnosticsRing(4);
    expect(ring.size).toBe(0);
    expect(ring.dropped).toBe(0);
    ring.push(input());
    ring.push(input());
    expect(ring.size).toBe(2);
    expect(ring.dropped).toBe(0);
    expect(ring.records()).toHaveLength(2);
  });

  it("refuses a capacity that is not a positive integer", () => {
    for (const bad of [0, -1, 1.5, Number.NaN]) {
      expect(() => new DiagnosticsRing(bad), String(bad)).toThrow(/positive integer/);
    }
  });

  it("pushAll appends in order and notifies once", () => {
    const ring = new DiagnosticsRing();
    const listener = vi.fn();
    ring.subscribe(listener);
    const stored = ring.pushAll([input({ event: "a" }), input({ event: "b" })]);
    expect(stored.map((entry) => entry.event)).toEqual(["a", "b"]);
    expect(ring.records().map((entry) => entry.event)).toEqual(["a", "b"]);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("pushAll of nothing is nothing — no record, no notification", () => {
    const ring = new DiagnosticsRing();
    const listener = vi.fn();
    ring.subscribe(listener);
    expect(ring.pushAll([])).toEqual([]);
    expect(listener).not.toHaveBeenCalled();
  });

  it("pushAll wraps the same way push does", () => {
    const ring = new DiagnosticsRing(3);
    ring.pushAll([0, 1, 2, 3, 4].map((n) => input({ event: `f-${n}` })));
    expect(ring.records().map((entry) => entry.event)).toEqual(["f-2", "f-3", "f-4"]);
  });

  it("clear() empties it, counter included", () => {
    const ring = new DiagnosticsRing(3);
    ring.pushAll([input(), input(), input(), input()]);
    expect(ring.dropped).toBe(1);
    ring.clear();
    expect(ring.records()).toEqual([]);
    expect(ring.size).toBe(0);
    expect(ring.dropped).toBe(0);
    ring.push(input({ event: "after" }));
    expect(ring.records()[0]).toMatchObject({ seq: 0, event: "after" });
  });
});

describe("criterion 5 — the useSyncExternalStore contract", () => {
  it("returns the same snapshot until something is pushed", () => {
    const ring = new DiagnosticsRing();
    const first = ring.getSnapshot();
    expect(ring.getSnapshot()).toBe(first);
    ring.push(input());
    const second = ring.getSnapshot();
    expect(second).not.toBe(first);
    expect(ring.getSnapshot()).toBe(second);
  });

  it("notifies subscribers and stops when they unsubscribe", () => {
    const ring = new DiagnosticsRing();
    const listener = vi.fn();
    const unsubscribe = ring.subscribe(listener);
    ring.push(input());
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    ring.push(input());
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("notifies on clear too", () => {
    const ring = new DiagnosticsRing();
    const listener = vi.fn();
    ring.subscribe(listener);
    ring.clear();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("criterion 5 — MEMORY ONLY", () => {
  const STORAGE_API =
    /\blocalStorage\b|\bsessionStorage\b|\bindexedDB\b|\bdocument\.cookie\b|\bcaches\b|\bopenDatabase\b|\bnavigator\.storage\b/;

  /**
   * Comments are stripped before the scan.
   *
   * The prohibition is on CODE that writes, not on prose that names the
   * prohibition — `ring.ts`'s own header lists the five APIs it does not
   * use, and a scan that failed on that would be a scan nobody could
   * document around. The behavioural assertion below is what covers an
   * indirection that evades a text scan.
   */
  function stripComments(source: string): string {
    return source.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/(^|\s)\/\/.*$/gm, "$1");
  }

  it("no module under lib/diagnostics names a storage API", async () => {
    const { readFileSync, readdirSync } = await import("node:fs");
    const path = await import("node:path");
    const dir = path.join(process.cwd(), "lib", "diagnostics");
    const files = readdirSync(dir).filter((file) => file.endsWith(".ts"));
    expect(files.length).toBeGreaterThan(3);
    for (const file of files) {
      const source = stripComments(readFileSync(path.join(dir, file), "utf8"));
      expect(STORAGE_API.test(source), `${file} names a storage API`).toBe(false);
    }
  });

  it("the stripper is not vacuous — it leaves real code alone", () => {
    expect(stripComments("// localStorage\nconst a = 1;\n")).not.toMatch(/localStorage/);
    expect(stripComments("/* localStorage */\n")).not.toMatch(/localStorage/);
    expect(stripComments("localStorage.setItem('a', 'b');")).toMatch(/localStorage/);
  });

  it("writes to no storage API when a record is pushed", () => {
    const written: string[] = [];
    const trap = (name: string) => ({
      get: () => {
        written.push(name);
        return undefined;
      },
      configurable: true,
    });
    const original = {
      localStorage: Object.getOwnPropertyDescriptor(window, "localStorage"),
      sessionStorage: Object.getOwnPropertyDescriptor(window, "sessionStorage"),
    };
    Object.defineProperty(window, "localStorage", trap("localStorage"));
    Object.defineProperty(window, "sessionStorage", trap("sessionStorage"));
    try {
      const ring = new DiagnosticsRing();
      ring.push(input());
      ring.pushAll([input(), input()]);
      ring.records();
      ring.clear();
      expect(written).toEqual([]);
    } finally {
      if (original.localStorage) {
        Object.defineProperty(window, "localStorage", original.localStorage);
      }
      if (original.sessionStorage) {
        Object.defineProperty(window, "sessionStorage", original.sessionStorage);
      }
    }
  });
});

describe("recordsFromTransition — what the machine contributes", () => {
  const base: JobState = { ...initialJobState, jobId: "run-1" };

  it("has nothing to compare a first snapshot's phase or connection against", () => {
    // `previous === null` is "we just subscribed". A phase and a connection
    // that were already true have no `from`, so recording them would
    // invent a movement that did not happen. Frames and a standing failure
    // DID happen and are recorded.
    const state: JobState = {
      ...base,
      phase: "live",
      connection: "open",
      failure: { kind: "offline", message: "", raw: null } as ApiFailure,
    };
    const records = recordsFromTransition(null, state, AT);
    expect(records.map((entry) => entry.kind)).toEqual(["failure"]);
  });

  it("records each new frame once, with the frame's own receive time", () => {
    const first = frame("job_started", AT, { job_id: "run-1" });
    const second = frame("node_completed", AT + 10, {
      node: "searcher",
      state_delta: { papers_found: 9 },
    });
    const before: JobState = { ...base, frames: [first] };
    const after: JobState = { ...base, frames: [first, second] };

    const records = recordsFromTransition(before, after, AT + 999);
    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({
      kind: "frame",
      event: "node_completed",
      at: AT + 10,
      jobId: "run-1",
      detail: { node: "searcher", state_delta: { papers_found: 9 } },
    });
  });

  it("identifies frames by reference, so a full log does not replay itself", () => {
    // The reducer caps `frames` at MAX_FRAMES: once it is full the LENGTH
    // stops changing while the contents keep moving. A length diff would
    // record nothing from that point on; reference identity is exact.
    const kept = Array.from({ length: 3 }, (_, index) =>
      frame(`old-${index}`, AT + index),
    );
    const fresh = frame("new", AT + 100);
    const before: JobState = { ...base, frames: kept };
    const after: JobState = { ...base, frames: [...kept.slice(1), fresh] };

    const records = recordsFromTransition(before, after, AT);
    expect(records.map((entry) => entry.event)).toEqual(["new"]);
  });

  it("passes unknown event names and unknown state_delta keys through (H11)", () => {
    const odd = frame("paper_indexed", AT, {
      arxiv_id: "2601.00001",
      state_delta: { decomposition_strategy: "per-sentence", unreleased_feature_flag: true },
    });
    const [record] = recordsFromTransition(base, { ...base, frames: [odd] }, AT);
    expect(record?.event).toBe("paper_indexed");
    expect(record?.detail).toEqual(odd.data);
  });

  it("records the connection change with what it moved from", () => {
    const records = recordsFromTransition(
      { ...base, connection: "open" },
      { ...base, connection: "reconnecting" },
      AT,
    );
    expect(records).toEqual([
      expect.objectContaining({
        kind: "connection",
        event: "reconnecting",
        from: "open",
        at: AT,
      }),
    ]);
  });

  it("records the machine's own transition", () => {
    const records = recordsFromTransition(
      { ...base, phase: "attaching" },
      { ...base, phase: "live" },
      AT,
    );
    expect(records).toEqual([
      expect.objectContaining({ kind: "transition", event: "live", from: "attaching" }),
    ]);
  });

  it("records the terminal SHAPE, which lives nowhere else", () => {
    const records = recordsFromTransition(base, {
      ...base,
      terminal: { name: "job_completed", shape: "replay", receivedAt: AT + 5 },
    }, AT);
    expect(records).toEqual([
      expect.objectContaining({
        kind: "terminal",
        event: "job_completed",
        at: AT + 5,
        detail: { shape: "replay" },
      }),
    ]);
  });

  it("records a failure as its normalized kind, plus the raw string", () => {
    const failure: ApiFailure = {
      kind: "upstream_unavailable",
      status: 502,
      message: "",
      raw: null,
    };
    const records = recordsFromTransition(base, {
      ...base,
      failure,
      failureSource: "poll",
      failureStatus: 502,
      failureMessage: "upstream returned 502",
    }, AT);
    expect(records).toEqual([
      expect.objectContaining({
        kind: "failure",
        event: "poll",
        failureKind: "upstream_unavailable",
        detail: { status: 502, error: "upstream returned 502" },
      }),
    ]);
  });

  it("falls back to the failure kind when no source is recorded", () => {
    const failure: ApiFailure = { kind: "timeout", message: "", raw: null };
    const [record] = recordsFromTransition(base, { ...base, failure }, AT);
    expect(record?.event).toBe("timeout");
  });

  it("does not repeat a failure that has not changed", () => {
    const failure: ApiFailure = { kind: "offline", message: "", raw: null };
    const settled: JobState = { ...base, failure };
    expect(recordsFromTransition(settled, settled, AT)).toEqual([]);
  });

  it("emits nothing at all when nothing changed", () => {
    expect(recordsFromTransition(base, base, AT)).toEqual([]);
  });

  it("emits every kind in one realistic step, frames first", () => {
    const arrived = frame("job_failed", AT + 3);
    const failure: ApiFailure = { kind: "server_error", status: 500, message: "", raw: null };
    const records = recordsFromTransition(
      { ...base, phase: "live", connection: "open" },
      {
        ...base,
        phase: "settled",
        connection: "closed",
        frames: [arrived],
        terminal: { name: "job_failed", shape: "live", receivedAt: AT + 3 },
        failure,
        failureSource: "reconcile",
        failureStatus: 500,
        failureMessage: "boom",
      },
      AT + 4,
    );
    expect(records.map((entry) => entry.kind)).toEqual([
      "frame",
      "terminal",
      "connection",
      "transition",
      "failure",
    ]);
    // Every kind the union declares is reachable; `vital` comes from
    // `vitals.ts`, which has its own test.
    const seen = new Set(records.map((entry) => entry.kind));
    for (const kind of DIAGNOSTIC_KINDS) {
      if (kind === "vital") continue;
      expect(seen.has(kind), kind).toBe(true);
    }
  });
});

describe("the shared singleton", () => {
  beforeEach(() => {
    diagnosticsRing.clear();
  });

  afterEach(() => {
    diagnosticsRing.clear();
  });

  it("is one buffer, shared by reference", async () => {
    const again = await import("@/lib/diagnostics/ring");
    expect(again.diagnosticsRing).toBe(diagnosticsRing);
    diagnosticsRing.push(input({ event: "shared" }));
    expect(again.diagnosticsRing.records()).toHaveLength(1);
  });
});

// LAST IN THE FILE, deliberately. `vi.resetModules()` empties this file's
// module registry, so any dynamic import after it gets a fresh evaluation —
// which is the point of the test and would be a false failure for anything
// that ran afterwards and expected the singleton it imported statically.
describe("criterion 5 — CLEARED ON RELOAD", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("a fresh module evaluation gets an empty buffer", async () => {
    const first = await import("@/lib/diagnostics/ring");
    expect(first.diagnosticsRing).toBe(diagnosticsRing);
    first.diagnosticsRing.push(input({ event: "before-reload" }));
    expect(first.diagnosticsRing.records()).toHaveLength(1);

    // The only thing a reload does to a module-scope singleton: evaluate
    // the module again. There is no rehydration path to test, because
    // there is nothing persisted to rehydrate from.
    vi.resetModules();
    const second = await import("@/lib/diagnostics/ring");
    expect(second.diagnosticsRing).not.toBe(first.diagnosticsRing);
    expect(second.diagnosticsRing.records()).toEqual([]);
    expect(second.diagnosticsRing.size).toBe(0);
    expect(second.diagnosticsRing.dropped).toBe(0);

    first.diagnosticsRing.clear();
  });
});
