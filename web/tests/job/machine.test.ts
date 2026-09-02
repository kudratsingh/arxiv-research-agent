// The reducer as a transition table (WO-10 acceptance criterion 1).
//
// Zero mocking, by construction: `jobReducer` takes a state and an
// event and returns a state. There is no clock to freeze, no fetch to
// intercept and no `EventSource` to stub, because none of them is
// reachable from `machine.ts`.
//
// `EXPECTED` below is written out by hand — all 11 phases × 26 events —
// rather than derived from `TRANSITIONS`, which would only prove the
// table equals itself. It is a second, independent statement of what
// the machine does, and the compiler forces it to stay total: adding a
// phase or an event breaks this file until the new row or column is
// decided here too.

import { describe, expect, it } from "vitest";

import {
  IGNORE,
  TRANSITIONS,
  detailSignature,
  initialJobState,
  isIgnored,
  isReplayShape,
  jobReducer,
  readNode,
  readPlan,
  readStateDelta,
  transitionMatrix,
} from "@/lib/job/machine";
import {
  JOB_EVENT_TYPES,
  JOB_PHASES,
  type JobEvent,
  type JobEventType,
  type JobPhase,
  type JobState,
} from "@/lib/job/types";
import { sessionAsJobDetail } from "@/lib/job/session";
import type { JobDetail, SessionDetail } from "@/lib/api";

import { loadFixture } from "../support/handlers";

// ---------------------------------------------------------------------------
// Sample inputs.
//
// Bodies come from the recorded fixtures, never from a literal written
// here: an authored `JobDetail` would let this file pass against a
// shape the API does not produce.
// ---------------------------------------------------------------------------

const RUNNING = loadFixture("job.running").body as JobDetail;
const PENDING_REVIEW = loadFixture("job.pending_review").body as JobDetail;
const SUCCEEDED = loadFixture("job.succeeded").body as JobDetail;

const TOKEN = "submission-under-test";

function frame(name: string, data: Record<string, unknown> | null) {
  return { name, data, receivedAt: 1_000 };
}

/**
 * One sample of every event type.
 *
 * `detail_resolved` deliberately carries the **running** fixture
 * throughout the table, so every cell that handles it is expected to
 * land on `live`. The other two routings — `pending_review` and a
 * terminal status — get their own tests below, where the input is the
 * thing under test rather than a constant.
 */
function sampleEvent(type: JobEventType): JobEvent {
  switch (type) {
    case "submit_requested":
      return {
        type,
        token: TOKEN,
        query: "q",
        conversationId: "conv-1",
        at: 1,
      };
    case "submit_accepted":
      return { type, token: TOKEN, jobId: "job-1", at: 1 };
    case "submit_rejected":
      return { type, token: TOKEN, failure: null, message: "nope", status: 500, at: 1 };
    case "attach_requested":
      return { type, jobId: "job-1", prefetch: true, at: 1 };
    case "detail_resolved":
      return { type, detail: RUNNING, source: "attach", at: 1 };
    case "detail_not_found":
      return {
        type,
        jobId: "job-1",
        failure: null,
        message: "job_not_found",
        status: 404,
        source: "attach",
        at: 1,
      };
    case "detail_unreachable":
      return {
        type,
        jobId: "job-1",
        failure: null,
        message: "network",
        status: null,
        source: "attach",
        at: 1,
      };
    case "stream_opened":
    case "stream_interrupted":
    case "stream_failed":
      return { type, jobId: "job-1", at: 1 };
    case "job_started":
      return { type, frame: frame("job_started", { job_id: "job-1", query: "q" }) };
    case "node_completed":
      return {
        type,
        frame: frame("node_completed", { node: "planner", state_delta: {} }),
      };
    case "plan_ready":
      return {
        type,
        frame: frame("plan_ready", {
          job_id: "job-1",
          plan: { sub_questions: ["a"], search_queries: ["b"] },
        }),
      };
    case "turn_ready":
      return {
        type,
        frame: frame("turn_ready", {
          job_id: "job-1",
          turn: { turn_number: 1, kind: "reflection" },
        }),
      };
    case "job_completed":
    case "job_failed":
    case "job_cancelled":
      return { type, frame: frame(type, { job_id: "job-1" }) };
    case "stream_timeout":
      return {
        type,
        frame: frame("stream_timeout", { job_id: "job-1", reconnect: true }),
      };
    case "unknown_frame":
      return { type, frame: frame("message", { anything: true }) };
    case "review_requested":
    case "review_accepted":
      return { type, action: "approve", at: 1 };
    case "review_conflict":
    case "review_rejected":
      return { type, failure: null, message: "conflict", status: 409, at: 1 };
    case "page_hidden":
    case "page_restored":
    case "reset":
      return { type, at: 1 };
  }
}

/** A state parked in `phase`, with whatever that phase's cells read. */
function seedFor(phase: JobPhase): JobState {
  return {
    ...initialJobState,
    phase,
    jobId: "job-1",
    submission:
      phase === "submitting"
        ? { token: TOKEN, query: "q", conversationId: "conv-1", startedAt: 0 }
        : null,
  };
}

// ---------------------------------------------------------------------------
// The table.
// ---------------------------------------------------------------------------

/** This pair is a deliberate no-op: the state comes back identical. */
const X = "ignored" as const;
type Expected = JobPhase | typeof X;

const EXPECTED: Record<JobPhase, Record<JobEventType, Expected>> = {
  idle: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: X,
    detail_not_found: X,
    detail_unreachable: X,
    stream_opened: X,
    stream_interrupted: X,
    stream_failed: X,
    job_started: X,
    node_completed: X,
    plan_ready: X,
    turn_ready: X,
    job_completed: X,
    job_failed: X,
    job_cancelled: X,
    stream_timeout: X,
    unknown_frame: X,
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: X,
    page_restored: X,
    reset: "idle",
  },
  submitting: {
    // R-01: a second submission while one is in flight is not a state
    // this machine has.
    submit_requested: X,
    submit_accepted: "attaching",
    submit_rejected: "submit_failed",
    attach_requested: "attaching",
    detail_resolved: X,
    detail_not_found: X,
    detail_unreachable: X,
    stream_opened: X,
    stream_interrupted: X,
    stream_failed: X,
    job_started: X,
    node_completed: X,
    plan_ready: X,
    turn_ready: X,
    job_completed: X,
    job_failed: X,
    job_cancelled: X,
    stream_timeout: X,
    unknown_frame: X,
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: X,
    page_restored: X,
    reset: "idle",
  },
  submit_failed: {
    // A retry is a NEW run, explicitly asked for (H6).
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: X,
    detail_not_found: X,
    detail_unreachable: X,
    stream_opened: X,
    stream_interrupted: X,
    stream_failed: X,
    job_started: X,
    node_completed: X,
    plan_ready: X,
    turn_ready: X,
    job_completed: X,
    job_failed: X,
    job_cancelled: X,
    stream_timeout: X,
    unknown_frame: X,
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: X,
    page_restored: X,
    reset: "idle",
  },
  attaching: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: "live",
    detail_not_found: "unavailable",
    // Not proof the run is gone — only a 404 is (H8).
    detail_unreachable: "live",
    stream_opened: "live",
    stream_interrupted: "attaching",
    stream_failed: "unavailable",
    job_started: "attaching",
    node_completed: "attaching",
    plan_ready: "awaiting_review",
    turn_ready: "awaiting_learner",
    job_completed: "reconciling",
    job_failed: "reconciling",
    job_cancelled: "reconciling",
    stream_timeout: "attaching",
    unknown_frame: "attaching",
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: "attaching",
    page_restored: "attaching",
    reset: "idle",
  },
  unavailable: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: "live",
    detail_not_found: X,
    detail_unreachable: X,
    stream_opened: X,
    stream_interrupted: X,
    stream_failed: X,
    job_started: X,
    node_completed: X,
    plan_ready: X,
    turn_ready: X,
    job_completed: X,
    job_failed: X,
    job_cancelled: X,
    stream_timeout: X,
    unknown_frame: X,
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: X,
    page_restored: X,
    reset: "idle",
  },
  live: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: "live",
    detail_not_found: "unavailable",
    detail_unreachable: "live",
    stream_opened: "live",
    stream_interrupted: "live",
    stream_failed: "unavailable",
    job_started: "live",
    node_completed: "live",
    plan_ready: "awaiting_review",
    turn_ready: "awaiting_learner",
    job_completed: "reconciling",
    job_failed: "reconciling",
    job_cancelled: "reconciling",
    stream_timeout: "live",
    unknown_frame: "live",
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: "live",
    page_restored: "live",
    reset: "idle",
  },
  awaiting_learner: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: "live",
    detail_not_found: "unavailable",
    detail_unreachable: "awaiting_learner",
    stream_opened: "awaiting_learner",
    stream_interrupted: "awaiting_learner",
    stream_failed: "unavailable",
    job_started: "awaiting_learner",
    node_completed: "awaiting_learner",
    plan_ready: "awaiting_review",
    turn_ready: "awaiting_learner",
    job_completed: "reconciling",
    job_failed: "reconciling",
    job_cancelled: "reconciling",
    stream_timeout: "awaiting_learner",
    unknown_frame: "awaiting_learner",
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: "awaiting_learner",
    page_restored: "awaiting_learner",
    reset: "idle",
  },
  awaiting_review: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: "live",
    detail_not_found: "unavailable",
    detail_unreachable: "awaiting_review",
    stream_opened: "awaiting_review",
    stream_interrupted: "awaiting_review",
    stream_failed: "unavailable",
    job_started: "awaiting_review",
    node_completed: "awaiting_review",
    plan_ready: "awaiting_review",
    turn_ready: "awaiting_learner",
    job_completed: "reconciling",
    job_failed: "reconciling",
    job_cancelled: "reconciling",
    stream_timeout: "awaiting_review",
    unknown_frame: "awaiting_review",
    review_requested: "awaiting_review",
    // The 200 does not mean resumed (`schemas.py:141-160`).
    review_accepted: "resolving",
    // 409 means the truth moved: refetch it (`routes.py:261-264`).
    review_conflict: "attaching",
    review_rejected: "awaiting_review",
    page_hidden: "awaiting_review",
    page_restored: "awaiting_review",
    reset: "idle",
  },
  resolving: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: "live",
    detail_not_found: "unavailable",
    detail_unreachable: "resolving",
    stream_opened: "resolving",
    stream_interrupted: "resolving",
    stream_failed: "unavailable",
    // The frame is the proof the run resumed, not the review's 200.
    job_started: "live",
    node_completed: "live",
    plan_ready: "awaiting_review",
    turn_ready: "awaiting_learner",
    job_completed: "reconciling",
    job_failed: "reconciling",
    job_cancelled: "reconciling",
    stream_timeout: "resolving",
    unknown_frame: "resolving",
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: "resolving",
    page_restored: "resolving",
    reset: "idle",
  },
  reconciling: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: "live",
    detail_not_found: "unavailable",
    // The run is over; its values could not be read. Settle honestly.
    detail_unreachable: "settled",
    stream_opened: X,
    stream_interrupted: X,
    stream_failed: X,
    job_started: X,
    node_completed: X,
    plan_ready: X,
    turn_ready: X,
    job_completed: X,
    job_failed: X,
    job_cancelled: X,
    stream_timeout: X,
    unknown_frame: X,
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: "reconciling",
    page_restored: "reconciling",
    reset: "idle",
  },
  settled: {
    submit_requested: "submitting",
    submit_accepted: X,
    submit_rejected: X,
    attach_requested: "attaching",
    detail_resolved: "live",
    detail_not_found: X,
    detail_unreachable: X,
    // The terminal handler closed this stream itself. Its close is not
    // a failure, and must not overwrite a finished run.
    stream_opened: X,
    stream_interrupted: X,
    stream_failed: X,
    job_started: X,
    node_completed: X,
    plan_ready: X,
    turn_ready: X,
    job_completed: X,
    job_failed: X,
    job_cancelled: X,
    stream_timeout: X,
    unknown_frame: X,
    review_requested: X,
    review_accepted: X,
    review_conflict: X,
    review_rejected: X,
    page_hidden: X,
    page_restored: X,
    reset: "idle",
  },
};

// ---------------------------------------------------------------------------

describe("the transition table is total", () => {
  it("has a decided cell for every phase and every event", () => {
    expect(Object.keys(TRANSITIONS).sort()).toEqual([...JOB_PHASES].sort());
    for (const phase of JOB_PHASES) {
      expect(Object.keys(TRANSITIONS[phase]).sort()).toEqual(
        [...JOB_EVENT_TYPES].sort()
      );
    }
    expect(transitionMatrix()).toHaveLength(
      JOB_PHASES.length * JOB_EVENT_TYPES.length
    );
    expect(JOB_PHASES).toHaveLength(11);
    expect(JOB_EVENT_TYPES).toHaveLength(26);
  });

  it("declares the same ignored set the expectation table does", () => {
    for (const { phase, type, handled } of transitionMatrix()) {
      expect({ phase, type, handled }).toEqual({
        phase,
        type,
        handled: EXPECTED[phase][type] !== X,
      });
    }
  });

  it("uses a deliberate no-op, never a fall-through", () => {
    // `IGNORE` is `null`, and the reducer returns the state object
    // itself for it. A fall-through would return a fresh object with
    // the same contents and this would not notice; identity does.
    expect(IGNORE).toBeNull();
    for (const phase of JOB_PHASES) {
      for (const type of JOB_EVENT_TYPES) {
        if (EXPECTED[phase][type] !== X) continue;
        expect(TRANSITIONS[phase][type]).toBe(IGNORE);
        expect(isIgnored(phase, type)).toBe(true);
      }
    }
  });
});

describe("every phase × event pair lands where the table says", () => {
  for (const phase of JOB_PHASES) {
    for (const type of JOB_EVENT_TYPES) {
      const expected = EXPECTED[phase][type];
      const label =
        expected === X
          ? `${phase} + ${type} is inert`
          : `${phase} + ${type} → ${expected}`;
      it(label, () => {
        const seed = seedFor(phase);
        const next = jobReducer(seed, sampleEvent(type));
        if (expected === X) {
          expect(next).toBe(seed);
          return;
        }
        expect(next.phase).toBe(expected);
        expect(next).not.toBe(seed);
      });
    }
  }
});

describe("the reducer is pure", () => {
  it("never mutates the state it was given", () => {
    for (const phase of JOB_PHASES) {
      for (const type of JOB_EVENT_TYPES) {
        const seed = seedFor(phase);
        const snapshot = structuredClone(seed);
        jobReducer(seed, sampleEvent(type));
        expect(seed).toEqual(snapshot);
      }
    }
  });

  it("returns the same result for the same inputs", () => {
    for (const phase of JOB_PHASES) {
      for (const type of JOB_EVENT_TYPES) {
        const event = sampleEvent(type);
        expect(jobReducer(seedFor(phase), event)).toEqual(
          jobReducer(seedFor(phase), event)
        );
      }
    }
  });

  it("reads no clock: every timestamp arrives on the event", () => {
    const at = 987_654;
    const next = jobReducer(seedFor("live"), {
      type: "stream_opened",
      jobId: "job-1",
      at,
    });
    expect(next.connectionOpenedAt).toBe(at);
  });
});

describe("attaching routes on the job's status, not on a frame", () => {
  const attaching = seedFor("attaching");

  it("pending_review lands on the review with the plan from JobDetail", () => {
    const next = jobReducer(attaching, {
      type: "detail_resolved",
      detail: PENDING_REVIEW,
      source: "attach",
      at: 1,
    });
    expect(next.phase).toBe("awaiting_review");
    expect(next.plan).toEqual(PENDING_REVIEW.plan);
  });

  it("a terminal status settles without opening a stream", () => {
    const next = jobReducer(attaching, {
      type: "detail_resolved",
      detail: SUCCEEDED,
      source: "attach",
      at: 1,
    });
    expect(next.phase).toBe("settled");
    expect(next.connection).toBe("closed");
  });

  it("running lands on live with no checkpoint claimed", () => {
    const next = jobReducer(attaching, {
      type: "detail_resolved",
      detail: RUNNING,
      source: "attach",
      at: 1,
    });
    expect(next.phase).toBe("live");
    expect(next.checkpoint).toBeNull();
  });
});

describe("the submission token", () => {
  const submitting = seedFor("submitting");

  it("adopts a job only for the submission in flight", () => {
    const next = jobReducer(submitting, {
      type: "submit_accepted",
      token: TOKEN,
      jobId: "job-9",
      at: 1,
    });
    expect(next.jobId).toBe("job-9");
    expect(next.submission).toBeNull();
  });

  it("drops a response carrying somebody else's token", () => {
    const next = jobReducer(submitting, {
      type: "submit_accepted",
      token: "a-stale-token",
      jobId: "job-9",
      at: 1,
    });
    // Not merely "did not transition": the state is untouched, so a
    // late duplicate cannot put a job on screen the user did not ask
    // for twice.
    expect(next).toBe(submitting);
  });

  it("drops a rejection carrying somebody else's token", () => {
    const next = jobReducer(submitting, {
      type: "submit_rejected",
      token: "a-stale-token",
      failure: null,
      message: "boom",
      status: 500,
      at: 1,
    });
    expect(next).toBe(submitting);
  });
});

describe("the liveness backoff counter", () => {
  function poll(state: JobState, detail: JobDetail): JobState {
    return jobReducer(state, {
      type: "detail_resolved",
      detail,
      source: "poll",
      at: 1,
    });
  }

  it("counts consecutive polls that changed nothing", () => {
    let state = jobReducer(seedFor("attaching"), {
      type: "detail_resolved",
      detail: RUNNING,
      source: "attach",
      at: 1,
    });
    expect(state.unchangedPolls).toBe(0);
    // The attach above is the baseline, so the very first poll already
    // counts as unchanged.
    for (let i = 1; i <= 5; i += 1) {
      state = poll(state, RUNNING);
      expect(state.unchangedPolls).toBe(i);
    }
  });

  it("resets the moment something changes", () => {
    let state = poll(seedFor("live"), RUNNING);
    state = poll(state, RUNNING);
    expect(state.unchangedPolls).toBe(1);
    state = poll(state, SUCCEEDED);
    expect(state.unchangedPolls).toBe(0);
  });

  it("ignores elapsed_sec, which changes on every poll by construction", () => {
    // `jobs.py:102-107` computes it as now() - started_at for a job
    // with no completed_at, so a naive comparison never backs off.
    const later: JobDetail = {
      ...RUNNING,
      elapsed_sec: (RUNNING.elapsed_sec ?? 0) + 20,
    };
    expect(detailSignature(later)).toBe(detailSignature(RUNNING));
    // The first poll only establishes the baseline; the second is the
    // first one that can be unchanged, and a moved `elapsed_sec` does
    // not stop it being so.
    const state = poll(poll(seedFor("live"), RUNNING), later);
    expect(state.unchangedPolls).toBe(1);
  });

  it("only the poll moves it — an attach or a reconcile does not", () => {
    let state = poll(poll(seedFor("live"), RUNNING), RUNNING);
    expect(state.unchangedPolls).toBe(1);
    state = jobReducer(state, {
      type: "detail_resolved",
      detail: RUNNING,
      source: "reconcile",
      at: 1,
    });
    expect(state.unchangedPolls).toBe(1);
  });
});

describe("payload readers tolerate what the contract allows", () => {
  it("treats a missing or empty node as no observation (H11)", () => {
    expect(readNode(null)).toBeNull();
    expect(readNode({})).toBeNull();
    expect(readNode({ node: "" })).toBeNull();
    expect(readNode({ node: 42 })).toBeNull();
    expect(readNode({ node: "claim_decomposer" })).toBe("claim_decomposer");
  });

  it("passes unknown state_delta keys straight through", () => {
    expect(
      readStateDelta({
        node: "planner",
        state_delta: { unreleased_feature_flag: true, planner_confidence: 0.62 },
      })
    ).toEqual({ unreleased_feature_flag: true, planner_confidence: 0.62 });
    expect(readStateDelta({ node: "searcher" })).toEqual({});
    expect(readStateDelta({ state_delta: "not an object" })).toEqual({});
  });

  it("ignores a plan_ready frame with no usable plan", () => {
    expect(readPlan(null)).toBeNull();
    expect(readPlan({ job_id: "job-1" })).toBeNull();
    const next = jobReducer(seedFor("live"), {
      type: "plan_ready",
      frame: frame("plan_ready", { job_id: "job-1" }),
    });
    expect(next.phase).toBe("live");
    expect(next.plan).toBeNull();
    // The frame still happened, and the log records what happened.
    expect(next.frames).toHaveLength(1);
  });

  it("survives a frame whose body did not parse", () => {
    const next = jobReducer(seedFor("live"), {
      type: "node_completed",
      frame: frame("node_completed", null),
    });
    expect(next.checkpoint).toBeNull();
    expect(next.frames).toHaveLength(1);
  });

  it("tells the replay terminal shape from the live one", () => {
    // `status` present is the attach-time replay (`routes.py:857-867`);
    // absent is a live outcome (`runner.py:1278-1288`).
    expect(isReplayShape(frame("job_completed", { status: "succeeded" }))).toBe(
      true
    );
    expect(isReplayShape(frame("job_completed", { llm_calls: 11 }))).toBe(false);
    expect(isReplayShape(frame("job_completed", null))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// WO-W13 criterion 1, second half.
//
// The table above already decides every session cell, but "an unknown event
// in a session run is tolerated exactly as the research machine tolerates it"
// is a claim about *equality between two runs*, and a table of expected
// phases cannot state it: both runs could be individually wrong in the same
// way and the table would still be green. So it is asserted directly, by
// running the identical event against both and comparing the whole state
// delta rather than the phase.
// ---------------------------------------------------------------------------

describe("a session run tolerates what a research run tolerates", () => {
  // From the recorded session fixture, through the same adapter the surface
  // uses. Not an authored literal, for the reason at the top of this file.
  const SESSION_DETAIL = sessionAsJobDetail(
    loadFixture("learn.session.awaiting").body as SessionDetail
  );

  /** Everything the reducer may legitimately differ on between two runs. */
  function shape(state: JobState) {
    return {
      frameCount: state.frames.length,
      lastFrameName: state.frames.at(-1)?.name ?? null,
      checkpoint: state.checkpoint,
      observed: state.observed,
      terminal: state.terminal,
      failure: state.failure,
      unavailableReason: state.unavailableReason,
      plan: state.plan,
      review: state.review,
      connection: state.connection,
    };
  }

  it("adopts awaiting_learner from the job's own status, not from a frame", () => {
    const next = jobReducer(seedFor("attaching"), {
      type: "detail_resolved",
      detail: SESSION_DETAIL,
      source: "attach",
      at: 1,
    });
    expect(next.phase).toBe("awaiting_learner");
    // The never-invent-a-stage rule: a parked session has published no
    // checkpoint, so none is claimed.
    expect(next.checkpoint).toBeNull();
    expect(next.plan).toBeNull();
  });

  it("logs an unknown frame and changes nothing else, in either run", () => {
    const event = sampleEvent("unknown_frame");
    const research = jobReducer(seedFor("live"), event);
    const session = jobReducer(seedFor("awaiting_learner"), event);

    expect(shape(session)).toEqual(shape(research));
    // Each run stays in the phase it was in: tolerating an unknown frame is
    // never a reason to move.
    expect(research.phase).toBe("live");
    expect(session.phase).toBe("awaiting_learner");
    expect(session.frames.at(-1)?.name).toBe("message");
  });

  it("treats a malformed turn_ready the way it treats a malformed plan_ready", () => {
    const research = jobReducer(seedFor("live"), {
      type: "plan_ready",
      frame: frame("plan_ready", null),
    });
    const session = jobReducer(seedFor("awaiting_learner"), {
      type: "turn_ready",
      frame: frame("turn_ready", null),
    });
    // Both log the frame; neither invents the payload it did not receive.
    expect(session.frames).toHaveLength(research.frames.length);
    expect(session.plan).toBeNull();
    expect(research.plan).toBeNull();
  });

  it("parks on turn_ready without claiming a checkpoint or a plan", () => {
    const seed = { ...seedFor("live"), plan: { sub_questions: ["a"], search_queries: ["b"] } };
    const next = jobReducer(seed, sampleEvent("turn_ready"));
    expect(next.phase).toBe("awaiting_learner");
    expect(next.plan).toBeNull();
    expect(next.checkpoint).toBeNull();
    expect(next.frames.at(-1)?.name).toBe("turn_ready");
  });
});
