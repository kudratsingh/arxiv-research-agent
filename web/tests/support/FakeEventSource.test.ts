// WO-05 acceptance criteria 1 and 2.
//
// The harness is only worth having if it replays what was recorded and
// nothing else, so this file checks the two ways it could quietly lie:
// delivering frames across a connection gap that the recording proves were
// lost, and choking on a name or a key the client has never heard of.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { SERVER_EVENT_NAMES, STREAM_TIMEOUT_EVENT } from "@/lib/api";

import {
  FakeEventSource,
  SSE_SCRIPT_NAMES,
  allSources,
  installFakeEventSource,
  isFakeEventSourceInstalled,
  isLiveShape,
  isReplayShape,
  isTerminalFrame,
  listSseScripts,
  loadSseScript,
  onlySource,
  openSources,
  uninstallFakeEventSource,
  type EventRecord,
} from "./FakeEventSource";

/** Names and payloads a listener saw, in receive order. */
interface Seen {
  name: string;
  data: unknown;
}

/**
 * Listen the way the app does: one handler per known name.
 *
 * `useResearchStream.ts:152-154` registers a fixed list, which is exactly why
 * an unknown name must be a no-op rather than an error.
 */
function listenForKnownNames(source: FakeEventSource): Seen[] {
  const seen: Seen[] = [];
  for (const name of [...SERVER_EVENT_NAMES]) {
    source.addEventListener(name, ((event: MessageEvent) => {
      seen.push({ name, data: JSON.parse(event.data as string) });
    }) as EventListener);
  }
  return seen;
}

afterEach(() => {
  uninstallFakeEventSource();
});

// ---------------------------------------------------------------------------
// Criterion 1 — it is the only stub, and it replays the scripts.
// ---------------------------------------------------------------------------

describe("FakeEventSource — the suite's only EventSource stub", () => {
  const TESTS_DIR = join(process.cwd(), "tests");
  const SUPPORT_DIR = join(TESTS_DIR, "support");

  function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((entry) => {
      const full = join(dir, entry);
      return statSync(full).isDirectory() ? walk(full) : [full];
    });
  }

  it("no other file under web/tests defines or installs one", () => {
    // 04-ARCHITECTURE.md §7.2 formalises the ad-hoc stubbing the suite grew
    // organically. A second stub is a second definition of "what a browser
    // does on a dropped connection", and the two drift.
    const offenders: string[] = [];
    for (const file of walk(TESTS_DIR)) {
      if (file.startsWith(SUPPORT_DIR)) continue;
      if (!/\.(ts|tsx)$/.test(file)) continue;
      const source = readFileSync(file, "utf8");
      const where = relative(process.cwd(), file);
      if (/\bclass\s+\w*EventSource\b/.test(source)) {
        offenders.push(`${where} declares its own EventSource class`);
      }
      if (/\bglobalThis\.EventSource\s*=/.test(source)) {
        offenders.push(`${where} assigns globalThis.EventSource directly`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("installs and restores the global, leaving nothing behind", () => {
    const before = globalThis.EventSource;
    installFakeEventSource();
    expect(isFakeEventSourceInstalled()).toBe(true);
    expect(globalThis.EventSource).toBe(
      FakeEventSource as unknown as typeof EventSource
    );

    uninstallFakeEventSource();

    expect(isFakeEventSourceInstalled()).toBe(false);
    expect(globalThis.EventSource).toBe(before);
    expect(allSources()).toEqual([]);
  });
});

describe("FakeEventSource — script loading", () => {
  it("its script union is exactly what is on disk", () => {
    expect(listSseScripts()).toEqual([...SSE_SCRIPT_NAMES].sort());
    expect(SSE_SCRIPT_NAMES).toHaveLength(9);
  });

  it.each(SSE_SCRIPT_NAMES)("%s loads, segments, and keeps its header", (name) => {
    const script = loadSseScript(name);
    expect(script.header.type).toBe("header");
    expect(script.header.case).toBe(name);
    expect(script.connections.length).toBeGreaterThan(0);

    // Segmentation is lossless for everything that is not a directive.
    const kept = script.connections.flatMap((connection) => connection.records);
    const nonDirectives = script.records.filter((r) => r.type !== "directive");
    expect(kept).toEqual(nonDirectives);
  });

  it("splits the two multi-connection scripts and nothing else", () => {
    // The scripts whose recordings contain a gap; every other file is one
    // uninterrupted connection.
    const shape = Object.fromEntries(
      SSE_SCRIPT_NAMES.map((name) => [
        name,
        loadSseScript(name).connections.map((c) => c.endedBy),
      ])
    );
    expect(shape.reconnect_gap).toEqual(["disconnect", "end-of-script"]);
    expect(shape.stream_timeout).toEqual(["server-close", "end-of-script"]);
    for (const [name, ends] of Object.entries(shape)) {
      if (name === "reconnect_gap" || name === "stream_timeout") continue;
      expect(ends).toEqual(["end-of-script"]);
    }
  });
});

describe("FakeEventSource — frame-by-frame replay", () => {
  beforeEach(() => {
    installFakeEventSource({ script: "live_success" });
  });

  it("delivers one frame per playNext, in receive order", () => {
    const source = new EventSource("/api/research/baseline-running/stream");
    const seen = listenForKnownNames(source as unknown as FakeEventSource);
    const fake = onlySource();

    expect(seen).toEqual([]);
    const first = fake.playNext();
    expect(first?.event).toBe("job_started");
    expect(seen).toHaveLength(1);

    fake.play();
    expect(seen.map((entry) => entry.name)).toEqual(
      loadSseScript("live_success").records
        .filter((r): r is EventRecord => r.type === "event")
        .map((r) => r.event)
    );
    expect(fake.playNext()).toBeNull();
  });

  it("drops heartbeat comments the way a real EventSource does", () => {
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    const anything: string[] = [];
    for (const name of ["comment", "heartbeat", "message", "ping"]) {
      source.addEventListener(name, () => anything.push(name));
    }
    const seen = listenForKnownNames(source);

    source.play();

    // The recording has a heartbeat; it was consumed, counted, and never
    // surfaced under any name.
    expect(source.heartbeats).toBeGreaterThan(0);
    expect(anything).toEqual([]);
    expect(seen.length).toBe(source.delivered.length);
  });

  it("controls readyState, open, error and server-close", () => {
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    const events: string[] = [];
    source.addEventListener("open", () => events.push("open"));
    source.addEventListener("error", () => events.push("error"));

    source.open();
    expect(source.readyState).toBe(FakeEventSource.OPEN);

    // A blip and a server close both leave the browser retrying.
    source.transientDrop();
    expect(source.readyState).toBe(FakeEventSource.CONNECTING);
    source.serverClose();
    expect(source.readyState).toBe(FakeEventSource.CONNECTING);

    // A non-200 is permanent: CLOSED, and the browser will not retry.
    source.fatal();
    expect(source.readyState).toBe(FakeEventSource.CLOSED);

    source.close();
    expect(source.closed).toBe(true);
    expect(source.readyState).toBe(FakeEventSource.CLOSED);
    expect(openSources()).toEqual([]);

    expect(events).toEqual(["open", "error", "error", "error"]);
  });

  it("fires the on* properties as well as addEventListener", () => {
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    const onopen = vi.fn();
    const onerror = vi.fn();
    source.onopen = onopen;
    source.onerror = onerror;

    source.open();
    source.fatal();

    expect(onopen).toHaveBeenCalledTimes(1);
    expect(onerror).toHaveBeenCalledTimes(1);
  });
});

describe("FakeEventSource — connection boundaries are honoured", () => {
  it("reconnect_gap never delivers the frame published during the gap", () => {
    // The whole point of the recording: a `node_completed` for `searcher` was
    // published with nobody subscribed, and Redis pub/sub dropped it
    // (`routes.py:444-454`). A stub that replayed the file start-to-finish
    // would hand the client a checkpoint that never arrived — which is the
    // bug this script exists to catch.
    installFakeEventSource({ script: "reconnect_gap" });
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    const seen = listenForKnownNames(source);

    const frames = source.playScript();

    const nodes = frames
      .filter((frame) => frame.event === "node_completed")
      .map((frame) => (frame.data as { node: string }).node);
    expect(nodes).toEqual(["planner", "synthesizer"]);
    expect(nodes).not.toContain("searcher");
    expect(seen.map((entry) => entry.name)).toEqual([
      "job_started",
      "node_completed",
      "node_completed",
      "job_completed",
    ]);
  });

  it("reconnect_gap stops at the boundary and needs an explicit reopen", () => {
    installFakeEventSource({ script: "reconnect_gap" });
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    const errors: string[] = [];
    source.addEventListener("error", () => errors.push("error"));

    const first = source.play();
    expect(first.map((f) => f.event)).toEqual([
      "job_started",
      "node_completed",
    ]);
    // Exhausted, and it does NOT reach into the next connection's records.
    expect(source.playNext()).toBeNull();
    expect(source.endedBy).toBe("disconnect");

    source.endConnection();
    expect(source.readyState).toBe(FakeEventSource.CONNECTING);
    expect(errors).toEqual(["error"]);

    source.reopen();
    expect(source.readyState).toBe(FakeEventSource.OPEN);
    expect(source.play().map((f) => f.event)).toEqual([
      "node_completed",
      "job_completed",
    ]);
    expect(source.endedBy).toBe("end-of-script");
  });

  it("stream_timeout ends its first connection with the transport frame", () => {
    installFakeEventSource({ script: "stream_timeout" });
    const source = new EventSource("/stream") as unknown as FakeEventSource;

    const first = source.play();

    expect(first.map((f) => f.event)).toEqual([STREAM_TIMEOUT_EVENT]);
    // The server closed the response itself; the job kept running, so this is
    // not a terminal outcome.
    expect(source.endedBy).toBe("server-close");
    expect(isTerminalFrame(first[0]!)).toBe(false);
    expect(source.heartbeats).toBe(5);

    const second = source.reopen().play();
    expect(second.map((f) => f.event)).toEqual([
      "node_completed",
      "job_completed",
    ]);
  });

  it("a second EventSource adopts the next recorded connection", () => {
    // The reconnect the app performs by closing and re-opening, rather than
    // by letting the browser retry the same object.
    installFakeEventSource({ script: "reconnect_gap" });
    const first = new EventSource("/stream") as unknown as FakeEventSource;
    first.play();
    first.close();

    const second = new EventSource("/stream") as unknown as FakeEventSource;

    expect(second.connection?.index).toBe(1);
    expect(second.play().map((f) => f.event)).toEqual([
      "node_completed",
      "job_completed",
    ]);
  });

  it("refuses to invent a connection the recording does not have", () => {
    installFakeEventSource({ script: "live_success" });
    new EventSource("/stream");

    expect(() => new EventSource("/stream")).toThrow(/records 1 connection/);
  });

  it("says so plainly when no script is installed", () => {
    installFakeEventSource();
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    expect(source.connection).toBeNull();
    expect(() => source.play()).toThrow(/manual mode/);
    // Manual driving still works, which is what the component tests use.
    const seen: string[] = [];
    source.addEventListener("job_started", () => seen.push("job_started"));
    source.emit("job_started", { job_id: "x", query: "q" });
    expect(seen).toEqual(["job_started"]);
  });
});

describe("FakeEventSource — terminal payload shapes", () => {
  it("replay_terminal is one attach-time frame with status and no llm_calls", () => {
    installFakeEventSource({ script: "replay_terminal" });
    const source = new EventSource("/stream") as unknown as FakeEventSource;

    const frames = source.play();

    expect(frames).toHaveLength(1);
    const only = frames[0]!;
    expect(isTerminalFrame(only)).toBe(true);
    expect(isReplayShape(only)).toBe(true);
    expect(isLiveShape(only)).toBe(false);
    expect(Object.keys(only.data ?? {})).not.toContain("llm_calls");
    // The terminal branch returns before the loop that emits a heartbeat.
    expect(source.heartbeats).toBe(0);
  });

  it("live_success ends on a live frame with llm_calls and no status", () => {
    installFakeEventSource({ script: "live_success" });
    const source = new EventSource("/stream") as unknown as FakeEventSource;

    const frames = source.play();

    const last = frames[frames.length - 1]!;
    expect(last.event).toBe("job_completed");
    expect(isLiveShape(last)).toBe(true);
    expect(isReplayShape(last)).toBe(false);
    expect(Object.keys(last.data ?? {})).toContain("llm_calls");
  });
});

// ---------------------------------------------------------------------------
// Criterion 2 — unknown names and unknown state_delta keys.
// ---------------------------------------------------------------------------

describe("FakeEventSource — tolerates what the client has never heard of", () => {
  it("replays event names outside SERVER_EVENT_NAMES without throwing", () => {
    installFakeEventSource({ script: "unknown_event_name" });
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    const seen = listenForKnownNames(source);

    // No validation anywhere in the path: the stub must not check names
    // against the union, or this script could not be replayed at all.
    const frames = source.playScript();

    const names = frames.map((frame) => frame.event);
    expect(names).toContain("node_started");
    expect(names).toContain("paper_indexed");

    // A client listening only for the names it knows sees a coherent stream
    // with the unknown frames simply absent — not an error, not a gap.
    expect(seen.map((entry) => entry.name)).toEqual([
      "job_started",
      "node_completed",
      "job_completed",
    ]);

    // And the manual path is just as unvalidated: any name at all goes out.
    for (const name of [...names, "a_name_nobody_will_ever_emit"]) {
      expect(() => source.emit(name, { anything: true })).not.toThrow();
    }
  });

  it("passes unknown state_delta keys through untouched", () => {
    installFakeEventSource({ script: "unknown_state_delta_keys" });
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    const seen = listenForKnownNames(source);

    expect(() => source.playScript()).not.toThrow();

    const deltas = seen
      .filter((entry) => entry.name === "node_completed")
      .map((entry) => (entry.data as { state_delta: Record<string, unknown> })
        .state_delta);
    const keys = deltas.flatMap((delta) => Object.keys(delta));
    expect(keys).toContain("planner_confidence");
    expect(keys).toContain("decomposition_strategy");
    expect(keys).toContain("unreleased_feature_flag");
    // An empty delta survives as an empty delta and is not turned into a
    // missing frame.
    expect(deltas.some((delta) => Object.keys(delta).length === 0)).toBe(true);
    // An opaque node name outside today's graph.
    const nodes = seen
      .filter((entry) => entry.name === "node_completed")
      .map((entry) => (entry.data as { node: string }).node);
    expect(nodes).toContain("claim_decomposer");
  });

  it("survives a payload that is not JSON at all", () => {
    installFakeEventSource();
    const source = new EventSource("/stream") as unknown as FakeEventSource;
    let raw: string | null = null;
    source.addEventListener("node_completed", ((event: MessageEvent) => {
      raw = event.data as string;
    }) as EventListener);

    expect(() => source.emitRaw("node_completed", "{not json")).not.toThrow();
    expect(raw).toBe("{not json");
  });
});
