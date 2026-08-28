// Drift check 4 of 4 (04-ARCHITECTURE.md §3.5), consumer half.
//
// The producer half is `tests/test_contract_sse_events.py`, which derives the
// same set from `src/api/streaming.py` and then reads the literal out of
// `lib/api/events.ts`. Adding a backend event breaks both: the Python test
// because its derived set stops matching the pin, this one because
// `SERVER_EVENT_NAMES` stops matching the list written out below.
//
// Both halves have to be edited to add an event, which is the point — an
// event that exists on the wire and not in the client is a silent hole, and
// the whole SSE surface is hand-written (§3.2).

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import {
  CLIENT_EVENT_NAMES,
  SERVER_EVENT_NAMES,
  STREAM_TIMEOUT_EVENT,
  TERMINAL_EVENTS,
  type ServerSseEventName,
  type SseEventName,
} from "@/lib/api";

/**
 * `TERMINAL_EVENT_NAMES ∪ {job_started, node_completed, plan_ready} ∪
 * {STREAM_TIMEOUT_EVENT}` — written out by hand rather than composed from the
 * constants under test, because a pin that derives itself from its subject
 * pins nothing.
 *
 * `src/api/streaming.py:75` (`STREAM_TIMEOUT_EVENT`), `:89-103`
 * (`TERMINAL_EVENT_STATUS`, from which `TERMINAL_EVENT_NAMES` is derived) and
 * the module docstring at `:13-35` for the three non-terminal runner frames.
 */
const PINNED_SERVER_EVENTS = [
  "job_cancelled",
  "job_completed",
  "job_failed",
  "job_started",
  "node_completed",
  "plan_ready",
  "stream_timeout",
];

type Exact<A, B> = [A] extends [B] ? ([B] extends [A] ? true : never) : never;
function proves<T extends true>(_: T): void {
  /* the type parameter is the assertion */
}

describe("contract/events — the frozen SSE name set", () => {
  it("events.ts declares exactly the pinned set", () => {
    expect([...SERVER_EVENT_NAMES].sort()).toEqual(PINNED_SERVER_EVENTS);
    expect(new Set(SERVER_EVENT_NAMES).size).toBe(SERVER_EVENT_NAMES.length);
  });

  it("pins the same set at the type level", () => {
    // The runtime array and the exported union cannot drift apart.
    proves<Exact<ServerSseEventName, (typeof SERVER_EVENT_NAMES)[number]>>(true);
    proves<
      Exact<
        ServerSseEventName,
        | "job_started"
        | "node_completed"
        | "plan_ready"
        | "job_completed"
        | "job_failed"
        | "job_cancelled"
        | "stream_timeout"
      >
    >(true);
  });

  it("has no node_started, because the runner emits only after a node returns", () => {
    // Named explicitly in `src/api/streaming.py:13-35`. It is the event
    // people most often assume exists.
    expect(SERVER_EVENT_NAMES).not.toContain("node_started");
  });

  it("treats stream_timeout as a member of the wire set but not an outcome", () => {
    // `streaming.py:108-114`: the stream ended, the job did not. A client
    // that put it in the terminal set would report a running job as finished.
    expect(SERVER_EVENT_NAMES).toContain(STREAM_TIMEOUT_EVENT);
    expect(TERMINAL_EVENTS.has(STREAM_TIMEOUT_EVENT as SseEventName)).toBe(
      false
    );
    expect([...TERMINAL_EVENTS].sort()).toEqual([
      "job_cancelled",
      "job_completed",
      "job_failed",
    ]);
  });

  it("keeps client-synthesized names off the wire set", () => {
    // `stream_note` and `error` are the stream hook's own transport notes;
    // no server ever sends them.
    for (const name of CLIENT_EVENT_NAMES) {
      expect(SERVER_EVENT_NAMES).not.toContain(name);
    }
    expect([...CLIENT_EVENT_NAMES].sort()).toEqual(["error", "stream_note"]);
  });

  it("keeps the legacy union exactly the server set minus stream_timeout, plus the client notes", () => {
    // `SseEventName` is frozen for M0 compatibility —
    // `components/EventLog.tsx:10` keys an exhaustive
    // `Record<SseEventName, string>` off it — so its relationship to the real
    // wire set has to be stated somewhere or the two quietly diverge. Adding
    // a listener for `stream_timeout` (M2) means widening the union, and this
    // proof is what makes that a deliberate edit.
    proves<
      Exact<
        SseEventName,
        | Exclude<ServerSseEventName, typeof STREAM_TIMEOUT_EVENT>
        | (typeof CLIENT_EVENT_NAMES)[number]
      >
    >(true);
  });
});

describe("contract/events — both halves of check 4 pin the same list", () => {
  it("the Python half reads the literal this file asserts", () => {
    // Belt and braces: the Python test parses `SERVER_EVENT_NAMES` out of
    // this source file. If the constant is ever renamed or restructured, the
    // parse would silently find nothing — so assert the shape it depends on
    // from this side too.
    const source = readFileSync(
      join(process.cwd(), "lib", "api", "events.ts"),
      "utf8"
    );
    const block = /export const SERVER_EVENT_NAMES = \[([^\]]*)\] as const;/.exec(
      source
    );
    expect(block).not.toBeNull();
    const names = [...(block?.[1] ?? "").matchAll(/"([a-z_]+)"/g)].map(
      (match) => match[1]
    );
    expect(names.sort()).toEqual(PINNED_SERVER_EVENTS);
  });
});
