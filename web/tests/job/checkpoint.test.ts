// The four checkpoint rules (WO-10 acceptance criterion 3,
// 04-ARCHITECTURE.md §4.4, REVIEW.md's binding constraint).
//
// Each rule gets its own describe block, and the last one drives
// `reconnect_gap.jsonl` — the recording that exists specifically to
// catch a client inventing the checkpoint it never saw. Between the
// two connections in that script a `node_completed` for `searcher` was
// published with nobody subscribed. It is not in the file, it can
// never be delivered, and the property under test is that the string
// "searcher" never appears in any state the machine passes through.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  checkpointIsCurrent,
  checkpointLabel,
  initialJobState,
  jobReducer,
} from "@/lib/job/machine";
import { useJobStream } from "@/lib/job/useJobStream";
import {
  JOB_EVENT_TYPES,
  JOB_PHASES,
  type JobClient,
  type JobEventType,
  type JobPhase,
  type JobState,
  type ObservedCheckpoint,
} from "@/lib/job/types";
import type { JobDetail } from "@/lib/api";

import {
  FakeEventSource,
  installFakeEventSource,
  loadSseScript,
  onlySource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture } from "../support/handlers";
import { act, renderHook } from "../support/render";

const RUNNING = loadFixture("job.running").body as JobDetail;
const SUCCEEDED = loadFixture("job.succeeded").body as JobDetail;

const PLANNER: ObservedCheckpoint = {
  node: "planner",
  observedAt: 10,
  stateDelta: { iteration: 0 },
};

function frame(name: string, data: Record<string, unknown> | null) {
  return { name, data, receivedAt: 100 };
}

/** A state on an open connection that has already seen `planner`. */
function observing(phase: JobPhase = "live"): JobState {
  return {
    ...initialJobState,
    phase,
    jobId: "baseline-running",
    connection: "open",
    checkpoint: PLANNER,
    observed: [PLANNER],
  };
}

// ---------------------------------------------------------------------------
// Rule 1 — set only by node_completed on the currently-open source.
// ---------------------------------------------------------------------------

describe("rule 1: only node_completed sets a checkpoint", () => {
  it("no other event in the whole table produces one", () => {
    // Exhaustive: from a state with no checkpoint, every phase × every
    // event, and the only pair that may end with one is
    // `node_completed`.
    const events: Record<JobEventType, unknown> = {} as never;
    void events;
    for (const phase of JOB_PHASES) {
      for (const type of JOB_EVENT_TYPES) {
        if (type === "node_completed") continue;
        const seed: JobState = {
          ...initialJobState,
          phase,
          jobId: "job-1",
          connection: "open",
        };
        const next = jobReducer(seed, eventFor(type));
        expect({ phase, type, checkpoint: next.checkpoint }).toEqual({
          phase,
          type,
          checkpoint: null,
        });
      }
    }
  });

  it("takes the node label verbatim, with no vocabulary check (H11)", () => {
    // `claim_decomposer` is not a node in today's graph. It is still a
    // checkpoint, because node names are opaque strings.
    const next = jobReducer(observing(), {
      type: "node_completed",
      frame: frame("node_completed", {
        node: "claim_decomposer",
        state_delta: { decomposition_strategy: "per-sentence" },
      }),
    });
    expect(checkpointLabel(next)).toBe("claim_decomposer");
    expect(next.checkpoint?.stateDelta).toEqual({
      decomposition_strategy: "per-sentence",
    });
  });

  it("observes nothing from a frame that carries no node", () => {
    const before = observing();
    const next = jobReducer(before, {
      type: "node_completed",
      frame: frame("node_completed", { state_delta: { iteration: 1 } }),
    });
    expect(next.checkpoint).toBe(PLANNER);
    expect(next.observed).toEqual([PLANNER]);
  });

  it("appends to the ledger in receive order", () => {
    let state = observing();
    for (const node of ["searcher", "synthesizer"]) {
      state = jobReducer(state, {
        type: "node_completed",
        frame: frame("node_completed", { node, state_delta: {} }),
      });
    }
    expect(state.observed.map((o) => o.node)).toEqual([
      "planner",
      "searcher",
      "synthesizer",
    ]);
    expect(checkpointLabel(state)).toBe("synthesizer");
  });
});

// ---------------------------------------------------------------------------
// Rule 2 — reset to unknown on every open.
// ---------------------------------------------------------------------------

describe("rule 2: every open resets the checkpoint to unknown", () => {
  it("clears it on stream_opened, in every phase that accepts one", () => {
    for (const phase of ["attaching", "live", "awaiting_review", "resolving"] as const) {
      const next = jobReducer(observing(phase), {
        type: "stream_opened",
        jobId: "baseline-running",
        at: 500,
      });
      expect({ phase, checkpoint: next.checkpoint, observed: next.observed }).toEqual(
        { phase, checkpoint: null, observed: [] }
      );
    }
  });

  it("clears it when the page is hidden and the stream closed (RC-18)", () => {
    const next = jobReducer(observing(), { type: "page_hidden", at: 1 });
    expect(next.checkpoint).toBeNull();
    expect(next.observed).toEqual([]);
  });

  it("clears it for a frame that arrives with no open we ever saw", () => {
    // The belt to `stream_opened`'s braces. If a frame lands while the
    // connection is `reconnecting`, it belongs to a connection whose
    // beginning we missed — so the previous connection's ledger goes
    // before the frame is applied, and the new checkpoint is the only
    // one left.
    const reconnecting: JobState = { ...observing(), connection: "reconnecting" };
    const next = jobReducer(reconnecting, {
      type: "node_completed",
      frame: frame("node_completed", { node: "synthesizer", state_delta: {} }),
    });
    expect(next.observed.map((o) => o.node)).toEqual(["synthesizer"]);
    expect(checkpointLabel(next)).toBe("synthesizer");
  });

  it("does not present a checkpoint as current once the connection ends", () => {
    const dropped = jobReducer(observing(), {
      type: "stream_interrupted",
      jobId: "baseline-running",
      at: 1,
    });
    // §5.4 keeps the ticks through a reconnect — they are a true
    // statement about a connection that ended — but they stop being a
    // statement about now, and this is the flag that says so.
    expect(dropped.checkpoint).toBe(PLANNER);
    expect(dropped.connection).toBe("reconnecting");
    expect(checkpointIsCurrent(dropped)).toBe(false);
    expect(checkpointIsCurrent(observing())).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Rules 3 — never persisted, never derived from JobDetail.
// ---------------------------------------------------------------------------

describe("rule 3: never persisted, never derived from JobDetail", () => {
  const MODULES = ["machine.ts", "types.ts", "useJobStream.ts", "provider.tsx"];

  it("no module in lib/job/ touches browser storage at all", () => {
    // Comments are stripped first: `machine.ts` names both APIs in the
    // note explaining that it never calls them, and a scan that could
    // not tell the two apart would have to be deleted the moment the
    // rule was documented.
    for (const name of MODULES) {
      const source = readFileSync(join(process.cwd(), "lib", "job", name), "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/\/\/.*$/gm, "");
      expect({
        name,
        storage: /\b(localStorage|sessionStorage)\b/.test(source),
      }).toEqual({ name, storage: false });
    }
  });

  it("writes nothing to storage while driving a whole run", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    let state = initialJobState;
    state = jobReducer(state, {
      type: "attach_requested",
      jobId: "baseline-running",
      prefetch: true,
      at: 1,
    });
    state = jobReducer(state, {
      type: "detail_resolved",
      detail: RUNNING,
      source: "attach",
      at: 2,
    });
    state = jobReducer(state, {
      type: "stream_opened",
      jobId: "baseline-running",
      at: 3,
    });
    state = jobReducer(state, {
      type: "node_completed",
      frame: frame("node_completed", { node: "planner", state_delta: {} }),
    });
    state = jobReducer(state, {
      type: "job_completed",
      frame: frame("job_completed", { job_id: "baseline-running" }),
    });
    state = jobReducer(state, {
      type: "detail_resolved",
      detail: SUCCEEDED,
      source: "reconcile",
      at: 9,
    });
    expect(state.phase).toBe("settled");
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("a JobDetail read never invents, changes or clears a checkpoint", () => {
    // `JobDetail` has no node field (`schemas.py:98-124`), so there is
    // nothing to derive one from — and a status of `running` must not
    // be turned into "it must have finished the planner by now".
    for (const detail of [RUNNING, SUCCEEDED]) {
      for (const source of ["attach", "poll", "reconcile", "refresh"] as const) {
        const fromNothing = jobReducer(
          { ...initialJobState, phase: "live", connection: "open" },
          { type: "detail_resolved", detail, source, at: 1 }
        );
        expect(fromNothing.checkpoint).toBeNull();
        expect(fromNothing.observed).toEqual([]);

        const fromSomething = jobReducer(observing(), {
          type: "detail_resolved",
          detail,
          source,
          at: 1,
        });
        expect(fromSomething.checkpoint).toBe(PLANNER);
        expect(fromSomething.observed).toEqual([PLANNER]);
      }
    }
  });

  it("a fresh attach starts from unknown — a reload observes nothing", () => {
    // H2: after any reload the position is unknown until a new frame
    // arrives. A reload is a fresh mount, so this is the mount state.
    const next = jobReducer(observing(), {
      type: "attach_requested",
      jobId: "baseline-running",
      prefetch: true,
      at: 1,
    });
    expect(next.checkpoint).toBeNull();
    expect(next.observed).toEqual([]);
    expect(checkpointLabel(next)).toBe("unknown");
  });
});

// ---------------------------------------------------------------------------
// The gap, end to end.
// ---------------------------------------------------------------------------

describe("reconnect_gap.jsonl: no invented checkpoint after a gap", () => {
  const details: JobDetail[] = [];
  let client: Partial<JobClient>;

  beforeEach(() => {
    details.length = 0;
    client = {
      // Two reads, in order: the pre-flight attach (still running) and
      // the reconcile after the terminal frame.
      getJob: () => Promise.resolve(details.shift() ?? SUCCEEDED),
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
      // `submitResearch` is left at its default and never called; no
      // test in this file may reach the one billable endpoint.
    };
    details.push({ ...RUNNING, job_id: "baseline-running" });
    installFakeEventSource({ script: "reconnect_gap" });
  });

  afterEach(() => {
    uninstallFakeEventSource();
  });

  it("the recording itself never carries the frame published in the gap", () => {
    const script = loadSseScript("reconnect_gap");
    const nodes = script.records
      .filter((record) => record.type === "event")
      .map((record) => (record.data as { node?: string } | null)?.node)
      .filter((node): node is string => typeof node === "string");
    expect(nodes).toEqual(["planner", "synthesizer"]);
    expect(script.connections).toHaveLength(2);
  });

  it("never shows searcher, and forgets planner at the reopen", async () => {
    const history: JobState[] = [];
    const { result } = renderHook(() => {
      const controls = useJobStream({ client });
      history.push(controls.state);
      return controls;
    });

    await act(async () => {
      result.current.attach("baseline-running");
    });
    const source = onlySource();

    // -- Connection 0: heartbeat, job_started, node_completed(planner).
    await act(async () => {
      source.play();
    });
    expect(checkpointLabel(result.current.state)).toBe("planner");
    expect(result.current.state.observed.map((o) => o.node)).toEqual(["planner"]);
    expect(source.heartbeats).toBe(1);

    // -- The drop. The browser owns the retry; the client only narrates.
    await act(async () => {
      source.endConnection();
    });
    expect(result.current.state.connection).toBe("reconnecting");
    expect(checkpointIsCurrent(result.current.state)).toBe(false);

    // -- The browser's own retry: same object, `open` again.
    await act(async () => {
      source.reopen();
    });
    expect(result.current.state.checkpoint).toBeNull();
    expect(checkpointLabel(result.current.state)).toBe("unknown");
    expect(result.current.state.observed).toEqual([]);
    // No second EventSource: this is a reconnect, not a re-attach.
    expect(FakeEventSource.instances).toHaveLength(1);

    // -- Connection 1: heartbeat, node_completed(synthesizer).
    await act(async () => {
      source.playNext();
    });
    expect(checkpointLabel(result.current.state)).toBe("synthesizer");
    expect(result.current.state.observed.map((o) => o.node)).toEqual([
      "synthesizer",
    ]);

    // -- Connection 1: job_completed → reconcile → settled.
    await act(async () => {
      source.playNext();
    });
    expect(result.current.state.phase).toBe("settled");

    // THE property. Every state the machine passed through, not just
    // the ones the assertions above happened to sample.
    expect(history.length).toBeGreaterThan(5);
    for (const state of history) {
      expect(state.checkpoint?.node).not.toBe("searcher");
      expect(state.observed.map((o) => o.node)).not.toContain("searcher");
    }
    // And the whole frame log, which is what a diagnostics disclosure
    // would render.
    expect(
      result.current.state.frames.some(
        (f) => (f.data as { node?: string } | null)?.node === "searcher"
      )
    ).toBe(false);
  });

  it("keeps the ledger empty when the reopen delivers nothing", async () => {
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    const source = onlySource();
    await act(async () => {
      source.play();
    });
    await act(async () => {
      source.endConnection();
      source.reopen();
    });
    // Nothing played on the new connection: the honest answer is
    // "unknown", not "planner" and not "searcher".
    expect(checkpointLabel(result.current.state)).toBe("unknown");
    expect(result.current.state.observed).toEqual([]);
    expect(result.current.state.connection).toBe("open");
  });
});

// ---------------------------------------------------------------------------

/** One sample event per type, for the exhaustive rule-1 sweep. */
function eventFor(type: JobEventType) {
  switch (type) {
    case "submit_requested":
      return { type, token: "t", query: "q", conversationId: null, at: 1 } as const;
    case "submit_accepted":
      return { type, token: "t", jobId: "job-1", at: 1 } as const;
    case "submit_rejected":
      return {
        type,
        token: "t",
        failure: null,
        message: "m",
        status: 500,
        at: 1,
      } as const;
    case "attach_requested":
      return { type, jobId: "job-1", prefetch: true, at: 1 } as const;
    case "detail_resolved":
      return { type, detail: RUNNING, source: "poll", at: 1 } as const;
    case "detail_not_found":
    case "detail_unreachable":
      return {
        type,
        jobId: "job-1",
        failure: null,
        message: "m",
        status: 404,
        source: "attach",
        at: 1,
      } as const;
    case "stream_opened":
    case "stream_interrupted":
    case "stream_failed":
      return { type, jobId: "job-1", at: 1 } as const;
    case "job_started":
    case "plan_ready":
    case "turn_ready":
    case "job_completed":
    case "job_failed":
    case "job_cancelled":
    case "stream_timeout":
    case "unknown_frame":
      // Every one of these carries a `node` key it must not read.
      return {
        type,
        frame: frame(type, { node: "searcher", plan: null }),
      } as const;
    case "node_completed":
      return {
        type,
        frame: frame(type, { node: "searcher", state_delta: {} }),
      } as const;
    case "review_requested":
    case "review_accepted":
      return { type, action: "approve", at: 1 } as const;
    case "review_conflict":
    case "review_rejected":
      return { type, failure: null, message: "m", status: 409, at: 1 } as const;
    case "page_hidden":
    case "page_restored":
    case "reset":
      return { type, at: 1 } as const;
  }
}
