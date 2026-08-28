"use client";

// The four hooks that wire the ring to React (WO-16).
//
// THIS MODULE DOES NOT IMPORT `lib/job/provider`. `useDiagnosticsRecorder`
// takes the `subscribe` / `getSnapshot` pair as an argument instead, for
// the same reason the provider exposes that pair at all: the machine must
// not know diagnostics exist, and the reverse is just as important — a
// surface that renders the disclosure without a `JobRunProvider` (the
// landing page, a story) must not drag `useJobStream`, `EventSource` and
// `lib/api` into its route chunk to do it.
//
// So WO-20's composition is one line inside a component that already calls
// `useJobRun()`:
//
//     useDiagnosticsRecorder(useJobRun());
//
// because `JobRunContextValue` already satisfies `MachineSource` — the two
// members are the ones `useSyncExternalStore` requires and the provider
// wrote them for this consumer.

import { useEffect, useRef, useSyncExternalStore } from "react";

import type { JobState } from "@/lib/job/types";

import {
  diagnosticsRing,
  recordsFromTransition,
  type DiagnosticRecord,
  type DiagnosticsRing,
} from "./ring";
import {
  isPerfDebugEnabled,
  startWebVitals,
  type StartWebVitalsOptions,
} from "./vitals";

/**
 * The machine, seen from outside React's render path.
 *
 * Structurally identical to the half of `JobRunContextValue` that
 * `lib/job/provider.tsx` documents as "the WO-11 integration seam", so no
 * adapter is needed at the call site.
 */
export interface MachineSource {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => JobState;
}

/**
 * Record every machine transition into the ring, for as long as this is
 * mounted.
 *
 * Subscribes outside the render path rather than diffing in an effect on
 * `state`, because the provider notifies its listeners AFTER writing the
 * snapshot the notification is about — so reading `getSnapshot()` from the
 * callback cannot miss an intermediate state the way a `useEffect` on a
 * re-rendered value can when two dispatches land in one batch.
 *
 * `null` is accepted and does nothing, so a surface can call this
 * unconditionally whether or not a machine is mounted above it.
 */
export function useDiagnosticsRecorder(
  source: MachineSource | null,
  ring: DiagnosticsRing = diagnosticsRing,
  now: () => number = Date.now,
): void {
  // The previous snapshot lives in a ref, not in state: recording must not
  // itself cause a render, or every frame would render the whole surface
  // twice.
  const previous = useRef<JobState | null>(null);

  // THE TWO MEMBERS, NOT THE OBJECT. `JobRunContextValue` is rebuilt on
  // every state change (its `useMemo` depends on `state`), so an effect
  // keyed on `source` would tear down and re-subscribe on every frame —
  // and each re-subscribe resets the baseline, which drops exactly the
  // transition it was re-subscribing to observe. `subscribe` and
  // `getSnapshot` are `useCallback([])` in the provider and never change,
  // so keying on them subscribes once.
  const subscribe = source?.subscribe ?? null;
  const getSnapshot = source?.getSnapshot ?? null;

  useEffect(() => {
    if (subscribe === null || getSnapshot === null) return;

    const observe = (): void => {
      const next = getSnapshot();
      if (next === previous.current) return;
      ring.pushAll(recordsFromTransition(previous.current, next, now()));
      previous.current = next;
    };

    // The state that exists at subscribe time is the baseline, not a
    // transition: replaying its phase and connection as records would
    // invent a movement the machine never made.
    previous.current = getSnapshot();
    return subscribe(observe);
  }, [getSnapshot, now, ring, subscribe]);
}

/** The ring's contents, as a React value. Re-renders when it grows. */
export function useDiagnosticsRecords(
  ring: DiagnosticsRing = diagnosticsRing,
): readonly DiagnosticRecord[] {
  return useSyncExternalStore(ring.subscribe, ring.getSnapshot, ring.getSnapshot);
}

/** The flag cannot change without a navigation, so nothing to subscribe to. */
const subscribeNever = (): (() => void) => () => {};

/**
 * The flag, read from wherever this is running.
 *
 * ONE function serves as both `getSnapshot` and `getServerSnapshot`, which
 * is what makes it hydration-safe rather than merely SSR-safe: two
 * different readers would have to agree by construction, and this one
 * cannot disagree with itself. On the server there is no `window`, so it is
 * `false`, and the first client render is the same `false` — the flag only
 * takes effect after hydration, which is exactly when the vitals it gates
 * can start being measured anyway.
 */
export function readDebugPerf(): boolean {
  if (typeof window === "undefined") return false;
  return isPerfDebugEnabled(window.location.search);
}

/**
 * Is `?debug=perf` set on the current URL?
 *
 * `useSyncExternalStore` with a no-op subscriber rather than
 * `useSearchParams`, for two reasons: it must not opt a route into
 * `next/navigation`'s client boundary, and the flag does not change without
 * a navigation, which remounts the tree anyway.
 */
export function useDebugPerf(): boolean {
  return useSyncExternalStore(subscribeNever, readDebugPerf, readDebugPerf);
}

/**
 * Load `web-vitals` and report LCP/INP/CLS into the ring, once, while
 * `enabled`.
 *
 * The guard is a ref rather than the effect's own cleanup because the
 * import is asynchronous: under StrictMode's double-invoked effects the
 * second run would otherwise start a second load and subscribe twice, and
 * the library dedupes nothing.
 */
export function useWebVitals(
  enabled: boolean,
  options: StartWebVitalsOptions = {},
): void {
  const started = useRef(false);
  const { load, now, ring } = options;

  useEffect(() => {
    if (!enabled || started.current) return;
    started.current = true;
    void startWebVitals({ load, now, ring });
  }, [enabled, load, now, ring]);
}
