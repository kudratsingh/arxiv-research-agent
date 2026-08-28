// Terminal copy and terminal frames (WO-10 acceptance criteria 4 and 7;
// H3, H9; 04-ARCHITECTURE.md §11.3; 03-DESIGN-BRIEF.md §5.1, §5.5).
//
// Two properties, one file, because they are the same property seen
// from two sides:
//
//   - **A terminal frame is a signal.** One event name has three
//     shapes — live `job_completed` carries `llm_calls` and no
//     `status` (`runner.py:1278-1288`), the attach-time replay carries
//     `status` and no `llm_calls` (`routes.py:857-867`), and live
//     `job_cancelled` carries `reason` at `runner.py:1128-1135` but
//     not at `runner.py:1196-1199`. Reading values off any of them
//     would make the UI's correctness depend on which one arrived.
//   - **The copy therefore cannot name a stage.** No terminal payload
//     carries a node, so "failed in <node>" would have to be invented.
//     The only true sentences are "failed after <checkpoint>", when
//     one was observed on the connection that ended, and plain
//     "failed".

import { describe, expect, it } from "vitest";

import {
  initialJobState,
  jobReducer,
  terminalPhrase,
} from "@/lib/job/machine";
import type { JobState } from "@/lib/job/types";
import type { JobDetail } from "@/lib/api";

import { loadSseScript } from "../support/FakeEventSource";
import { loadFixture } from "../support/handlers";

const SUCCEEDED = loadFixture("job.succeeded").body as JobDetail;
const FAILED_PARTIAL = loadFixture("job.failed_partial").body as JobDetail;
const CANCELLED = loadFixture("job.cancelled").body as JobDetail;

/** The recorded terminal payloads, straight off the wire. */
function recordedPayload(
  script: "replay_terminal" | "terminal_replay_no_node" | "live_success" | "live_failure"
): { event: string; data: Record<string, unknown> | null } {
  const record = loadSseScript(script)
    .records.filter((r) => r.type === "event")
    .at(-1);
  if (record === undefined || record.type !== "event") {
    throw new Error(`${script} has no event records`);
  }
  return { event: record.event, data: record.data };
}

/**
 * Live `job_cancelled`, both shapes.
 *
 * There is no recording for either: cancelling for real resumes and
 * then stops a workflow against a model, which the cost boundary
 * forbids. The two payloads are transcribed from the runner's emit
 * sites, and the point of the test is that the difference between them
 * cannot reach the screen.
 */
const CANCELLED_WITH_REASON = {
  job_id: "baseline-cancelled",
  elapsed_sec: 16.0,
  reason: "hitl_cancelled",
};
const CANCELLED_WITHOUT_REASON = {
  job_id: "baseline-cancelled",
  elapsed_sec: 16.0,
};

// ---------------------------------------------------------------------------
// A run, driven purely through the reducer.
// ---------------------------------------------------------------------------

interface RunOptions {
  /** Checkpoints observed on the connection that ends, in order. */
  checkpoints?: string[];
  /** A drop and reopen before the terminal frame (the gap case). */
  reopenAfter?: number;
  terminal: { event: string; data: Record<string, unknown> | null };
  /** What `GET /research/{id}` answers, or `null` for a failed read. */
  reconcile: JobDetail | null;
}

function run({
  checkpoints = [],
  reopenAfter,
  terminal,
  reconcile,
}: RunOptions): JobState {
  let state = jobReducer(initialJobState, {
    type: "attach_requested",
    jobId: "job-1",
    prefetch: true,
    at: 0,
  });
  state = jobReducer(state, {
    type: "stream_opened",
    jobId: "job-1",
    at: 1,
  });
  checkpoints.forEach((node, index) => {
    if (reopenAfter === index) {
      state = jobReducer(state, {
        type: "stream_interrupted",
        jobId: "job-1",
        at: 100 + index,
      });
      state = jobReducer(state, {
        type: "stream_opened",
        jobId: "job-1",
        at: 150 + index,
      });
    }
    state = jobReducer(state, {
      type: "node_completed",
      frame: {
        name: "node_completed",
        data: { node, state_delta: {} },
        receivedAt: 200 + index,
      },
    });
  });
  state = jobReducer(state, {
    type: terminal.event as "job_completed" | "job_failed" | "job_cancelled",
    frame: { name: terminal.event, data: terminal.data, receivedAt: 900 },
  });
  state =
    reconcile === null
      ? jobReducer(state, {
          type: "detail_unreachable",
          jobId: "job-1",
          failure: null,
          message: "network down",
          status: null,
          source: "reconcile",
          at: 950,
        })
      : jobReducer(state, {
          type: "detail_resolved",
          detail: reconcile,
          source: "reconcile",
          at: 950,
        });
  return state;
}

// ---------------------------------------------------------------------------
// Criterion 4 — the copy.
// ---------------------------------------------------------------------------

/**
 * 03-DESIGN-BRIEF.md §5.5's forbidden strings, as patterns.
 *
 * "failed in" is the one the acceptance criterion names; the rest are
 * here because a phrase that sneaks past one of them has usually
 * sneaked past all of them.
 */
const FORBIDDEN = [
  /failed in\b/i,
  /failed during\b/i,
  /\bin progress\b/i,
  /currently running/i,
  /\bstage\b/i,
  /step \d+ of \d+/i,
  /almost done/i,
  /%/,
];

/** Every terminal path a run can reach, with the phrase it must produce. */
const TERMINAL_PATHS: Array<{
  name: string;
  state: () => JobState;
  phrase: string;
}> = [
  {
    name: "live failure, checkpoints observed",
    state: () =>
      run({
        checkpoints: ["planner", "searcher"],
        terminal: recordedPayload("live_failure"),
        reconcile: FAILED_PARTIAL,
      }),
    phrase: "failed after searcher",
  },
  {
    name: "live failure, nothing observed on this connection",
    state: () =>
      run({ terminal: recordedPayload("live_failure"), reconcile: FAILED_PARTIAL }),
    phrase: "failed",
  },
  {
    name: "replay failure on attach, which carries no node at all",
    state: () =>
      run({
        terminal: recordedPayload("terminal_replay_no_node"),
        reconcile: FAILED_PARTIAL,
      }),
    phrase: "failed",
  },
  {
    name: "failure after a reconnect: only the new connection counts",
    state: () =>
      run({
        checkpoints: ["planner", "synthesizer"],
        reopenAfter: 1,
        terminal: recordedPayload("live_failure"),
        reconcile: FAILED_PARTIAL,
      }),
    phrase: "failed after synthesizer",
  },
  {
    name: "failure whose settling read never came back",
    state: () =>
      run({
        checkpoints: ["planner"],
        terminal: recordedPayload("live_failure"),
        reconcile: null,
      }),
    phrase: "failed after planner",
  },
  {
    name: "live success",
    state: () =>
      run({
        checkpoints: ["planner", "searcher", "synthesizer"],
        terminal: recordedPayload("live_success"),
        reconcile: SUCCEEDED,
      }),
    phrase: "complete",
  },
  {
    name: "replay success on attach",
    state: () =>
      run({ terminal: recordedPayload("replay_terminal"), reconcile: SUCCEEDED }),
    phrase: "complete",
  },
  {
    name: "cancelled, live frame carrying a reason",
    state: () =>
      run({
        checkpoints: ["planner"],
        terminal: { event: "job_cancelled", data: CANCELLED_WITH_REASON },
        reconcile: CANCELLED,
      }),
    phrase: "cancelled",
  },
  {
    name: "cancelled, live frame carrying no reason",
    state: () =>
      run({
        terminal: { event: "job_cancelled", data: CANCELLED_WITHOUT_REASON },
        reconcile: CANCELLED,
      }),
    phrase: "cancelled",
  },
  {
    name: "cancelled, settling read never came back",
    state: () =>
      run({
        terminal: { event: "job_cancelled", data: CANCELLED_WITHOUT_REASON },
        reconcile: null,
      }),
    phrase: "cancelled",
  },
  {
    name: "success signalled, settling read never came back",
    state: () =>
      run({ terminal: recordedPayload("live_success"), reconcile: null }),
    // H9: the live `job_completed` frame does not even carry `status`.
    // With no read to confirm it, "complete" would be a claim nothing
    // supports.
    phrase: "finished",
  },
  {
    name: "the run is no longer available",
    state: () =>
      jobReducer(
        { ...initialJobState, phase: "attaching", jobId: "job-1" },
        {
          type: "detail_not_found",
          jobId: "job-1",
          failure: null,
          message: "job_not_found",
          status: 404,
          source: "attach",
          at: 1,
        }
      ),
    phrase: "no longer available",
  },
  {
    name: "the submission itself failed",
    state: () =>
      jobReducer(
        {
          ...initialJobState,
          phase: "submitting",
          submission: {
            token: "t",
            query: "q",
            conversationId: null,
            startedAt: 0,
          },
        },
        {
          type: "submit_rejected",
          token: "t",
          failure: null,
          message: "rate limited",
          status: 429,
          at: 1,
        }
      ),
    phrase: "not started",
  },
];

describe("terminal copy is 'failed after <checkpoint>' or plain 'failed'", () => {
  for (const path of TERMINAL_PATHS) {
    it(`${path.name} → "${path.phrase}"`, () => {
      expect(terminalPhrase(path.state())).toBe(path.phrase);
    });
  }

  it("no terminal path anywhere produces a forbidden form", () => {
    for (const path of TERMINAL_PATHS) {
      const phrase = terminalPhrase(path.state());
      expect(phrase).not.toBeNull();
      for (const pattern of FORBIDDEN) {
        expect({ path: path.name, phrase, matches: pattern.test(phrase!) }).toEqual(
          { path: path.name, phrase, matches: false }
        );
      }
    }
  });

  it("the only shape a failure phrase can take is 'failed' or 'failed after X'", () => {
    // Stronger than the forbidden list: an allow-list. A phrase this
    // does not match cannot have come from `terminalPhrase`, whatever
    // preposition someone reaches for later.
    for (const path of TERMINAL_PATHS) {
      const phrase = terminalPhrase(path.state())!;
      if (!phrase.startsWith("failed")) continue;
      expect(phrase).toMatch(/^failed( after [^\s]+)?$/);
    }
  });

  it("says nothing at all while the run is unfinished", () => {
    for (const phase of ["idle", "submitting", "attaching", "live", "awaiting_review", "resolving", "reconciling"] as const) {
      expect(terminalPhrase({ ...initialJobState, phase })).toBeNull();
    }
  });

  it("names the checkpoint verbatim, not from a vocabulary", () => {
    const state = run({
      checkpoints: ["a_node_nobody_has_heard_of"],
      terminal: recordedPayload("live_failure"),
      reconcile: FAILED_PARTIAL,
    });
    expect(terminalPhrase(state)).toBe("failed after a_node_nobody_has_heard_of");
  });
});

// ---------------------------------------------------------------------------
// Criterion 7 — terminal frames are signals only.
// ---------------------------------------------------------------------------

describe("terminal frames are signals; values come from GET /research/{id}", () => {
  const SHAPES: Array<{ name: string; data: Record<string, unknown> | null }> = [
    {
      name: "live job_completed (llm_calls, no status)",
      data: recordedPayload("live_success").data,
    },
    { name: "replay job_completed (status, no llm_calls)", data: recordedPayload("replay_terminal").data },
    { name: "live job_cancelled with a reason", data: CANCELLED_WITH_REASON },
    { name: "live job_cancelled with no reason", data: CANCELLED_WITHOUT_REASON },
    { name: "replay job_failed (status, no llm_calls)", data: recordedPayload("terminal_replay_no_node").data },
    { name: "live job_failed (no status)", data: recordedPayload("live_failure").data },
  ];

  it("records only the name, the shape and the arrival time", () => {
    for (const shape of SHAPES) {
      const state = run({
        terminal: { event: "job_completed", data: shape.data },
        reconcile: SUCCEEDED,
      });
      expect(Object.keys(state.terminal ?? {}).sort()).toEqual([
        "name",
        "receivedAt",
        "shape",
      ]);
      expect(state.terminal?.name).toBe("job_completed");
      // The discriminator is recorded for the diagnostics disclosure —
      // and it is the ONLY thing the payload decides.
      expect(state.terminal?.shape).toBe(
        shape.data !== null && "status" in shape.data ? "replay" : "live"
      );
    }
  });

  it("displays the settled JobDetail, whichever shape signalled it", () => {
    const details: JobState["detail"][] = SHAPES.map(
      (shape) =>
        run({
          terminal: { event: "job_completed", data: shape.data },
          reconcile: SUCCEEDED,
        }).detail
    );
    // One name, six payloads, one rendered answer.
    for (const detail of details) expect(detail).toEqual(SUCCEEDED);
  });

  it("does not believe a replay frame's status over the read", () => {
    // The replay shape is the only terminal payload that carries a
    // `status` at all, and trusting it is the exact mistake H9 exists
    // to prevent: here the frame says succeeded and the job failed.
    const state = run({
      terminal: {
        event: "job_completed",
        data: { job_id: "baseline-failed-partial", status: "succeeded" },
      },
      reconcile: FAILED_PARTIAL,
    });
    expect(state.detail?.status).toBe("failed");
    expect(terminalPhrase(state)).toBe("failed");
  });

  it("keeps no value from the frame, not even the ones JobDetail lacks", () => {
    // Live `job_completed` carries `llm_calls`; the replay does not.
    // Neither number is anywhere in the state — the only copy of it is
    // the frame log, which is a record of what arrived rather than a
    // source of rendered values.
    // Sentinel values that cannot collide with anything in the
    // recorded fixture, so the search below means what it says.
    const state = run({
      terminal: {
        event: "job_completed",
        data: {
          job_id: "job-1",
          llm_calls: 987654321,
          cost_usd: 123456.789,
          iterations: 555555,
        },
      },
      reconcile: SUCCEEDED,
    });
    // Everything except the frame log, which is a record of what
    // arrived rather than a source of rendered values.
    const rendered = JSON.stringify({ ...state, frames: [] });
    for (const sentinel of ["987654321", "123456.789", "555555"]) {
      expect({ sentinel, present: rendered.includes(sentinel) }).toEqual({
        sentinel,
        present: false,
      });
    }
    expect(state.detail?.llm_calls).toBe(SUCCEEDED.llm_calls);
    expect(state.detail?.cost_usd).toBe(SUCCEEDED.cost_usd);
  });

  it("the checkpoint survives the settle, because the failure is 'after' it", () => {
    const state = run({
      checkpoints: ["planner", "searcher"],
      terminal: recordedPayload("live_failure"),
      reconcile: FAILED_PARTIAL,
    });
    expect(state.checkpoint?.node).toBe("searcher");
    expect(state.connection).toBe("closed");
  });
});
