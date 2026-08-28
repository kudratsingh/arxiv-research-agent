// The stream, against the recorded frame scripts (WO-10 acceptance
// criteria 5, 7 and 8; 05-MIGRATION.md §2.1 step 4).
//
// Every scenario here replays a `web/contract/sse/*.jsonl` recording
// through the one `FakeEventSource` stub. Nothing invents a frame: the
// two places that do author a payload (`plan_ready` sent twice, and
// the unnamed `message` frame) say so and say why.

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import type { JobDetail } from "@/lib/api";
import { checkpointLabel, jobReducer } from "@/lib/job/machine";
import { useJobStream } from "@/lib/job/useJobStream";
import type { JobClient, JobState } from "@/lib/job/types";

import {
  FakeEventSource,
  allSources,
  installFakeEventSource,
  loadSseScript,
  onlySource,
  openSources,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture } from "../support/handlers";
import { act, renderHook } from "../support/render";

const RUNNING = loadFixture("job.running").body as JobDetail;
const SUCCEEDED = loadFixture("job.succeeded").body as JobDetail;
const PENDING_REVIEW = loadFixture("job.pending_review").body as JobDetail;

/**
 * Reads in the order the machine makes them; never a POST.
 *
 * Always built OUTSIDE the render function. The client is a memoized
 * seam keyed on the object identity, so a fresh literal per render
 * would hand every read a fresh queue and quietly answer the reconcile
 * with the attach's response.
 */
function clientReturning(...details: JobDetail[]): Partial<JobClient> {
  const queue = [...details];
  return {
    getJob: () => Promise.resolve(queue.length > 1 ? queue.shift()! : queue[0]!),
    streamUrl: (jobId) => `/api/research/${jobId}/stream`,
  };
}

afterEach(() => {
  uninstallFakeEventSource();
});

// ---------------------------------------------------------------------------
// Criterion 5 — stream_timeout.
// ---------------------------------------------------------------------------

describe("stream_timeout reopens the stream immediately", () => {
  beforeEach(() => {
    installFakeEventSource({ script: "stream_timeout" });
  });

  it("registers the seventh name the current client drops", () => {
    // `useResearchStream.ts:59-66` registers six names. The frame in
    // this recording is real server output from the deadline path
    // (`streaming.py:300-308`), and today it is dropped silently.
    const script = loadSseScript("stream_timeout");
    const names = script.records
      .filter((r) => r.type === "event")
      .map((r) => r.event);
    expect(names).toContain("stream_timeout");
  });

  it("opens a new connection in the same tick, with no timer to wait out", async () => {
    const client = clientReturning(RUNNING, SUCCEEDED);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    const first = onlySource();

    await act(async () => {
      first.play();
    });

    // "Immediately" is provable here because this suite installs no
    // fake timers and advances nothing: the second connection exists
    // as a direct consequence of the frame.
    expect(allSources()).toHaveLength(2);
    expect(first.closed).toBe(true);
    expect(openSources()).toHaveLength(1);
    expect(first.heartbeats).toBe(5);

    // The stream ended; the JOB did not. Nothing about the run's phase
    // may change on this frame.
    expect(result.current.state.phase).toBe("live");
    expect(result.current.state.frames.map((f) => f.name)).toEqual([
      "stream_timeout",
    ]);
  });

  it("treats the reopened connection as a new one for the checkpoint", async () => {
    const client = clientReturning(RUNNING, SUCCEEDED);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    await act(async () => {
      onlySource().play();
    });

    const second = onlySource();
    await act(async () => {
      second.play();
    });

    // The recording's second connection carries `synthesizer` and the
    // terminal frame. Everything before the timeout is gone, as it
    // must be: there is no backlog.
    expect(result.current.state.observed.map((o) => o.node)).toEqual([
      "synthesizer",
    ]);
    expect(result.current.state.phase).toBe("settled");
    expect(result.current.state.detail).toEqual(SUCCEEDED);
  });

  it("is not a terminal event: TERMINAL_EVENTS excludes it", () => {
    // `streaming.py:89-103` pins the three outcomes; the stream ending
    // is not one of them.
    const state = jobReducer(
      {
        phase: "live",
        jobId: "baseline-running",
        detail: RUNNING,
        plan: null,
        checkpoint: null,
        observed: [],
        connection: "open",
        frames: [],
        terminal: null,
        failure: null,
        failureMessage: null,
        failureStatus: null,
        failureSource: null,
        unavailableReason: null,
        submission: null,
        review: null,
        unchangedPolls: 0,
        detailSignature: null,
        lastFrameAt: null,
        connectionOpenedAt: 1,
        suspended: false,
      } satisfies JobState,
      {
        type: "stream_timeout",
        frame: {
          name: "stream_timeout",
          data: { reconnect: true, max_duration_sec: 60 },
          receivedAt: 5,
        },
      }
    );
    expect(state.phase).toBe("live");
    expect(state.terminal).toBeNull();
    expect(state.connection).toBe("reconnecting");
  });
});

// ---------------------------------------------------------------------------
// Criterion 8 — plan_ready is idempotent.
// ---------------------------------------------------------------------------

describe("plan_ready is idempotent", () => {
  beforeEach(() => {
    installFakeEventSource({ script: "plan_review" });
  });

  /** Everything except the frame log, which records what arrived. */
  function withoutLog(state: JobState) {
    return { ...state, frames: [], lastFrameAt: null };
  }

  it("a second frame changes nothing but the log", async () => {
    // `routes.py:456-462`: the frame can legitimately arrive twice on
    // the in-memory path. The duplicate below is the recorded frame,
    // re-sent — the recording carries it once because one connection
    // saw it once.
    const client = clientReturning(PENDING_REVIEW, SUCCEEDED);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-plan-review");
    });
    const source = onlySource();

    await act(async () => {
      source.playNext();
    });
    const afterFirst = withoutLog(result.current.state);
    expect(result.current.state.phase).toBe("awaiting_review");

    const replayed = loadSseScript("plan_review").records.find(
      (r) => r.type === "event" && r.event === "plan_ready"
    );
    await act(async () => {
      source.emit(
        "plan_ready",
        (replayed as { data: Record<string, unknown> }).data
      );
    });

    expect(withoutLog(result.current.state)).toEqual(afterFirst);
    // Both arrivals are in the log; neither produced a warning, a
    // second plan, or a phase change.
    expect(
      result.current.state.frames.filter((f) => f.name === "plan_ready")
    ).toHaveLength(2);
  });

  it("is idempotent in the reducer too, with no hook in the way", () => {
    const frame = {
      name: "plan_ready",
      data: {
        job_id: "baseline-plan-review",
        plan: { sub_questions: ["a"], search_queries: ["b"] },
      },
      receivedAt: 1,
    };
    const seed: JobState = {
      ...jobReducer(
        { ...emptyState(), phase: "live", connection: "open" },
        { type: "plan_ready", frame }
      ),
    };
    const again = jobReducer(seed, { type: "plan_ready", frame });
    expect(withoutLog(again)).toEqual(withoutLog(seed));
  });

  it("survives the plan arriving from JobDetail and then again as a frame", async () => {
    // The attach read already produced the plan (`schemas.py:115-120`),
    // so the replayed frame is the second arrival of the same thing.
    const client = clientReturning(PENDING_REVIEW, SUCCEEDED);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-plan-review");
    });
    expect(result.current.state.plan).toEqual(PENDING_REVIEW.plan);
    const fromDetail = withoutLog(result.current.state);

    await act(async () => {
      onlySource().playNext();
    });
    expect(withoutLog(result.current.state)).toEqual({
      ...fromDetail,
      connection: "open",
      connectionOpenedAt: result.current.state.connectionOpenedAt,
    });
  });
});

// ---------------------------------------------------------------------------
// Review resolution.
// ---------------------------------------------------------------------------

describe("resolving the review pause", () => {
  beforeEach(() => {
    installFakeEventSource({ script: "plan_review" });
  });

  it("a 200 means 'wait', not 'resumed'", async () => {
    // `ReviewResponse.status` is always `pending_review`
    // (`schemas.py:141-160`).
    const client: Partial<JobClient> = {
      ...clientReturning(PENDING_REVIEW, SUCCEEDED),
      reviewPlan: () => Promise.resolve({ status: "pending_review" }),
    };
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-plan-review");
    });
    // The recording opens with the attach-time replay of plan_ready.
    await act(async () => {
      onlySource().playNext();
    });
    expect(result.current.state.phase).toBe("awaiting_review");

    await act(async () => {
      await result.current.review("approve");
    });
    expect(result.current.state.phase).toBe("resolving");
    expect(result.current.state.plan).toBeNull();

    // The next frame is what proves the run resumed — not the 200.
    await act(async () => {
      onlySource().playNext();
    });
    expect(result.current.state.phase).toBe("live");
    expect(checkpointLabel(result.current.state)).toBe("searcher");
  });

  it("a 409 refetches the truth instead of shouting", async () => {
    // `job_not_awaiting_review` (`routes.py:261-264`): another tab
    // resolved it, or `api_hitl_timeout_sec` fired.
    const reads: string[] = [];
    const client: Partial<JobClient> = {
      getJob: (jobId) => {
        reads.push(jobId);
        return Promise.resolve(reads.length === 1 ? PENDING_REVIEW : SUCCEEDED);
      },
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
      reviewPlan: () =>
        Promise.reject(
          new ApiError(409, "job_not_awaiting_review (status=running)")
        ),
    };
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-plan-review");
    });
    await act(async () => {
      await result.current.review("approve");
    });

    expect(reads).toEqual(["baseline-plan-review", "baseline-plan-review"]);
    expect(result.current.state.phase).toBe("settled");
    expect(result.current.state.detail).toEqual(SUCCEEDED);
  });
});

// ---------------------------------------------------------------------------
// Tolerance.
// ---------------------------------------------------------------------------

describe("unknown names and unknown keys are tolerated", () => {
  it("ignores event names the backend does not emit today", async () => {
    // `node_started` does not exist at all (`streaming.py:13-35`) and
    // `paper_indexed` is invented. A browser only delivers events a
    // listener was registered for, so the tolerance is structural —
    // and this proves the machine registers nothing wider.
    installFakeEventSource({ script: "unknown_event_name" });
    const client = clientReturning(RUNNING, SUCCEEDED);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    await act(async () => {
      onlySource().play();
    });

    expect(result.current.state.frames.map((f) => f.name)).toEqual([
      "job_started",
      "node_completed",
      "job_completed",
    ]);
    expect(checkpointLabel(result.current.state)).toBe("searcher");
    expect(result.current.state.phase).toBe("settled");
  });

  it("passes unknown state_delta keys through and accepts unknown nodes", async () => {
    installFakeEventSource({ script: "unknown_state_delta_keys" });
    const client = clientReturning(RUNNING, SUCCEEDED);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    await act(async () => {
      onlySource().play();
    });

    expect(result.current.state.observed.map((o) => o.node)).toEqual([
      "planner",
      "claim_decomposer",
      "searcher",
    ]);
    expect(result.current.state.observed[0]?.stateDelta).toEqual({
      iteration: 0,
      planner_confidence: 0.62,
      sub_questions_count: 3,
      unreleased_feature_flag: true,
    });
    // An empty delta is still an observation: the node completed.
    expect(result.current.state.observed[2]?.stateDelta).toEqual({});
  });

  it("logs an unnamed frame without letting it change anything", async () => {
    // No recording carries one — the server names every event it
    // emits — so this is the seam a future event would arrive through,
    // exercised by hand.
    installFakeEventSource();
    const client = clientReturning(RUNNING);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    await act(async () => {
      onlySource().emit("message", { something: "new" });
    });
    expect(result.current.state.frames.map((f) => f.name)).toEqual(["message"]);
    expect(result.current.state.phase).toBe("live");
    expect(result.current.state.checkpoint).toBeNull();
  });

  it("survives a frame whose body is not JSON", async () => {
    installFakeEventSource();
    const client = clientReturning(RUNNING);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    await act(async () => {
      onlySource().emitRaw("node_completed", "{not json");
    });
    expect(result.current.state.frames).toHaveLength(1);
    expect(result.current.state.frames[0]?.data).toBeNull();
    expect(result.current.state.checkpoint).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The whole live path.
// ---------------------------------------------------------------------------

describe("live_success end to end", () => {
  it("settles from the read, closes the stream, and opens no second one", async () => {
    installFakeEventSource({ script: "live_success" });
    const client = clientReturning(RUNNING, SUCCEEDED);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    const source = onlySource();
    await act(async () => {
      source.play();
    });

    expect(result.current.state.phase).toBe("settled");
    expect(result.current.state.detail).toEqual(SUCCEEDED);
    expect(result.current.state.observed.map((o) => o.node)).toEqual([
      "planner",
      "searcher",
      "synthesizer",
    ]);
    expect(source.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("narrates a transient drop and never unlocks mid-run", async () => {
    installFakeEventSource();
    const client = clientReturning(RUNNING);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    await act(async () => {
      onlySource().transientDrop();
    });
    expect(result.current.state.phase).toBe("live");
    expect(result.current.state.connection).toBe("reconnecting");
    expect(result.current.state.frames.map((f) => f.name)).toEqual([
      "stream_note",
    ]);
  });

  it("a permanently failed connection is the unavailable dead end", async () => {
    installFakeEventSource();
    const client = clientReturning(RUNNING);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    await act(async () => {
      onlySource().fatal();
    });
    expect(result.current.state.phase).toBe("unavailable");
    expect(result.current.state.unavailableReason).toBe("stream_failed");
  });

  it("does not report a settled stream's own close as a failure", async () => {
    installFakeEventSource({ script: "live_success" });
    const client = clientReturning(RUNNING, SUCCEEDED);
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    const source = onlySource();
    await act(async () => {
      source.play();
    });
    expect(result.current.state.phase).toBe("settled");

    await act(async () => {
      source.fatal();
    });
    // Overwriting a finished run with "no longer available" would
    // throw the report away.
    expect(result.current.state.phase).toBe("settled");
    expect(result.current.state.detail).toEqual(SUCCEEDED);
  });
});

// ---------------------------------------------------------------------------

function emptyState(): JobState {
  return {
    phase: "idle",
    jobId: null,
    detail: null,
    plan: null,
    checkpoint: null,
    observed: [],
    connection: "closed",
    frames: [],
    terminal: null,
    failure: null,
    failureMessage: null,
    failureStatus: null,
    failureSource: null,
    unavailableReason: null,
    submission: null,
    review: null,
    unchangedPolls: 0,
    detailSignature: null,
    lastFrameAt: null,
    connectionOpenedAt: null,
    suspended: false,
  };
}
