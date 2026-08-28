/**
 * `lib/spine/state.ts` and `lib/spine/adapter.ts` — the twelve states of
 * 03 §5.4 and the four inputs of §5.2 (WO-15 criteria 1, 3, 4).
 *
 * This is the half of the spine that has no DOM. It matters on its own
 * because §5.1's binding constraint is a statement about a DERIVATION —
 * "the trace may be driven only by job status plus the last observed
 * completed checkpoint" — and a derivation is provable in a way a rendered
 * tree is not:
 *
 *   - `spineStateId` is TOTAL. The sweep below drives every combination of
 *     status × connection × ledger × plan and asserts every one lands on
 *     one of the twelve rows, so criterion 4's "renders a defined state"
 *     cannot fail by falling through a gap.
 *   - The adapter is the ONLY reader of `JobState`, so "does the spine read
 *     something it may not?" is answered by one file. The purity property
 *     is asserted here at the input level and again at the DOM level in
 *     `TraceSpine.test.tsx`.
 */

import { describe, expect, it } from "vitest";

import type { JobDetail, JobStatus } from "@/lib/api";
import { initialJobState } from "@/lib/job/machine";
import type { JobState, ObservedCheckpoint } from "@/lib/job/types";
import { spineInputs } from "@/lib/spine/adapter";
import {
  SEGMENT_STATUSES,
  SEGMENT_WORD,
  SPINE_CONNECTIONS,
  SPINE_STATES,
  describeSpine,
  spineStateId,
  type SegmentStatus,
  type SpineConnection,
  type SpineInputs,
  type SpineStateId,
  type SpineStatus,
} from "@/lib/spine/state";

import { EVERY_STATE, ONE, PLAN, STATUS_UNKNOWN, THREE, checkpoint } from "./spineFixtures";

const STATUSES: SpineStatus[] = [
  null,
  "submitting",
  "unavailable",
  "pending",
  "running",
  "pending_review",
  "succeeded",
  "failed",
  "cancelled",
];

function inputs(over: Partial<SpineInputs> = {}): SpineInputs {
  return {
    status: "running",
    observation: { checkpoints: [], connection: "open", current: false },
    plan: null,
    secondsSinceLastFrame: null,
    ...over,
  };
}

// ---------------------------------------------------------------------------
// The twelve.
// ---------------------------------------------------------------------------

describe("03 §5.4's table is the state set, exactly", () => {
  it("has twelve rows and no more", () => {
    expect(SPINE_STATES).toHaveLength(12);
    expect(new Set(SPINE_STATES).size).toBe(12);
  });

  it("every row is reachable, and the fixture for it lands on it", () => {
    for (const id of SPINE_STATES) {
      expect(spineStateId(EVERY_STATE[id]), id).toBe(id);
    }
  });

  it("state C — attached with the status not reported — lands on the rejoined row", () => {
    // H2: after a reload the position is unknown and the UI says so. The
    // sentence claims no status, which is the whole difference.
    expect(spineStateId(STATUS_UNKNOWN)).toBe("rejoined");
    expect(describeSpine(STATUS_UNKNOWN).announcement).not.toContain("Running");
  });

  it("is total: every status × connection × ledger × plan lands on a row", () => {
    const set = new Set<string>(SPINE_STATES);
    const ledgers: Array<readonly ObservedCheckpoint[]> = [[], ONE, THREE];
    let combinations = 0;
    for (const status of STATUSES) {
      for (const connection of SPINE_CONNECTIONS) {
        for (const checkpoints of ledgers) {
          for (const plan of [null, PLAN]) {
            for (const seconds of [null, 0, 41]) {
              const id = spineStateId(
                inputs({
                  status,
                  observation: {
                    checkpoints,
                    connection,
                    current: connection === "open" && checkpoints.length > 0,
                  },
                  plan,
                  secondsSinceLastFrame: seconds,
                }),
              );
              expect(set.has(id), `${String(status)}/${connection}`).toBe(true);
              combinations += 1;
            }
          }
        }
      }
    }
    expect(combinations).toBe(STATUSES.length * 4 * 3 * 2 * 3);
  });
});

describe("the three pairs the ledger alone tells apart", () => {
  const cases: Array<[JobStatus, SpineStateId, SpineStateId]> = [
    ["succeeded", "succeeded", "historic"],
    ["failed", "failed_observed", "failed_unobserved"],
  ];

  it.each(cases)("%s: %s with a ledger, %s without", (status, withLedger, without) => {
    expect(spineStateId(inputs({ status, observation: { checkpoints: THREE, connection: "closed", current: false } }))).toBe(withLedger);
    expect(spineStateId(inputs({ status, observation: { checkpoints: [], connection: "closed", current: false } }))).toBe(without);
  });

  it("running: observed with a ledger, rejoined without", () => {
    expect(spineStateId(inputs({ observation: { checkpoints: ONE, connection: "open", current: true } }))).toBe("running_observed");
    expect(spineStateId(inputs({ observation: { checkpoints: [], connection: "open", current: false } }))).toBe("rejoined");
  });

  it("a run this session watched finish and one loaded from history differ only in the ledger", () => {
    // D-010: `job.plan = None` is permanent, and there is no replay
    // backlog — so "produced outside this session" and "finished while we
    // were not watching" are the same claim, and get the same sentence.
    const history = describeSpine(EVERY_STATE.historic);
    expect(history.ledger).toEqual([]);
    expect(history.segments.map((segment) => segment.status)).toEqual([
      "unavailable",
      "unavailable",
      "unavailable",
      "complete",
    ]);
  });
});

describe("the connection is part of input 2, and it is what §5.4's four live rows need", () => {
  it("recycled and reconnecting are different rows with the same ledger", () => {
    const ledger = { checkpoints: ONE, current: false };
    expect(spineStateId(inputs({ observation: { ...ledger, connection: "reconnecting" } }))).toBe("reconnecting");
    expect(spineStateId(inputs({ observation: { ...ledger, connection: "recycled" } }))).toBe("recycled");
  });

  it("a terminal status outranks whatever the socket is doing", () => {
    for (const connection of SPINE_CONNECTIONS) {
      expect(
        spineStateId(
          inputs({
            status: "cancelled",
            observation: { checkpoints: THREE, connection, current: false },
          }),
        ),
      ).toBe("cancelled");
    }
  });

  it("`live` is true only on an open socket — the one place ambient motion is allowed", () => {
    for (const connection of SPINE_CONNECTIONS) {
      const model = describeSpine(inputs({ observation: { checkpoints: ONE, connection, current: connection === "open" } }));
      expect(model.live, connection).toBe(connection === "open");
    }
  });
});

// ---------------------------------------------------------------------------
// Segments.
// ---------------------------------------------------------------------------

describe("segments", () => {
  it("are always the four of 03 §5.3, in order, with a word each", () => {
    for (const id of SPINE_STATES) {
      const model = describeSpine(EVERY_STATE[id]);
      expect(model.segments.map((segment) => segment.name), id).toEqual([
        "Question",
        "Plan",
        "Run",
        "Report",
      ]);
      for (const segment of model.segments) {
        expect(SEGMENT_STATUSES, id).toContain(segment.status);
        // `live` is the ambient indicator, never a segment.
        expect(segment.status, id).not.toBe("live");
        expect(segment.word, id).toBe(SEGMENT_WORD[segment.status]);
        expect(segment.word.length, id).toBeGreaterThan(0);
      }
    }
  });

  it("the Plan segment is filled only by the pause, never by the status", () => {
    // §5.2: the plan is "non-null only during pending_review" and is
    // "erased on resume". A running job that once had one no longer does,
    // so drawing `Plan ──●` from the status would be an observation we do
    // not hold — which is the invention §5.1 forbids.
    const running = describeSpine(inputs({ observation: { checkpoints: THREE, connection: "open", current: true } }));
    expect(running.segments[1]?.status).toBe("not-observed");

    const withPlan = describeSpine(
      inputs({
        status: "running",
        plan: PLAN,
        observation: { checkpoints: THREE, connection: "open", current: true },
      }),
    );
    // A plan in hand is the review pause, whatever the last poll said.
    expect(withPlan.id).toBe("awaiting_review");
    expect(withPlan.segments[1]?.status).toBe("awaiting-review");
  });

  it("the Run segment always agrees with the ledger beside it", () => {
    for (const id of SPINE_STATES) {
      const model = describeSpine(EVERY_STATE[id]);
      const run = model.segments[2] as { status: SegmentStatus };
      if (run.status === "observed") {
        expect(model.ledger.length, id).toBeGreaterThan(0);
      }
      if (run.status === "not-observed") {
        expect(model.ledger, id).toEqual([]);
      }
    }
  });

  it("cancelled marks the Plan segment, because the review is the only place to cancel", () => {
    expect(describeSpine(EVERY_STATE.cancelled).segments.map((s) => s.status)).toEqual([
      "observed",
      "cancelled",
      "not-observed",
      "not-observed",
    ]);
  });

  it("expired dashes every segment (03 §5.4's last row)", () => {
    expect(describeSpine(EVERY_STATE.expired).segments.map((s) => s.status)).toEqual([
      "unavailable",
      "unavailable",
      "unavailable",
      "unavailable",
    ]);
  });
});

// ---------------------------------------------------------------------------
// Sentences.
// ---------------------------------------------------------------------------

describe("the announcement is material, and the detail is not announced", () => {
  it("running announces one word that a checkpoint arriving cannot change", () => {
    const before = describeSpine(inputs({ observation: { checkpoints: ONE, connection: "open", current: true }, secondsSinceLastFrame: 3 }));
    const after = describeSpine(inputs({ observation: { checkpoints: THREE, connection: "open", current: true }, secondsSinceLastFrame: 0 }));
    expect(before.announcement).toBe(after.announcement);
    expect(before.detail).not.toBe(after.detail);
  });

  it("names the last observed checkpoint only where H3 allows it", () => {
    const failed = describeSpine(EVERY_STATE.failed_observed);
    expect(failed.announcement).toBe(
      "Failed after the last observed checkpoint (synthesizer).",
    );
    expect(describeSpine(EVERY_STATE.failed_unobserved).announcement).toBe(
      "Failed. No checkpoints were observed on this connection.",
    );
  });

  it("says only 'Complete' for a succeeded run — the metrics are WO-19's", () => {
    // Duration, quality, cost and calls are not among §5.2's four inputs.
    const model = describeSpine(EVERY_STATE.succeeded);
    expect(model.announcement).toBe(SEGMENT_WORD.complete);
    expect(model.announcement).not.toMatch(/\$|quality|calls/);
  });

  it("carries a detail line wherever there is something true to count", () => {
    expect(describeSpine(EVERY_STATE.running_observed).detail).toBe(
      "3 checkpoints observed on this connection · updated 41s ago",
    );
    expect(describeSpine(EVERY_STATE.rejoined).detail).toBe(
      "No checkpoints observed on this connection",
    );
    // Settled: the count is still true, the age would be a clock reading.
    expect(describeSpine(EVERY_STATE.succeeded).detail).toBe(
      "3 checkpoints observed on this connection",
    );
    expect(describeSpine(EVERY_STATE.historic).detail).toBeNull();
    expect(describeSpine(EVERY_STATE.submitting).detail).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The adapter.
// ---------------------------------------------------------------------------

function detail(status: JobStatus): JobDetail {
  return { job_id: "baseline-running", status } as JobDetail;
}

function jobState(over: Partial<JobState> = {}): JobState {
  return { ...initialJobState, jobId: "baseline-running", phase: "live", ...over };
}

describe("the adapter reads JobState, and the spine reads the adapter", () => {
  it("returns null when there is no run on screen at all", () => {
    expect(spineInputs(initialJobState)).toBeNull();
    expect(spineInputs({ ...initialJobState, phase: "submit_failed" })).toBeNull();
  });

  it("a submission in flight is a status, and it is the only one with no job id", () => {
    const state = { ...initialJobState, phase: "submitting" as const };
    expect(spineInputs(state)?.status).toBe("submitting");
    expect(state.jobId).toBeNull();
  });

  it("a 404 is 'unavailable', never a guess about why (H8)", () => {
    expect(spineInputs(jobState({ phase: "unavailable" }))?.status).toBe("unavailable");
  });

  it("the status is null until GET /research/{id} has said otherwise (H9)", () => {
    expect(spineInputs(jobState())?.status).toBeNull();
    expect(spineInputs(jobState({ detail: detail("running") }))?.status).toBe("running");
  });

  it("`current` is checkpointIsCurrent, and it agrees with the connection", () => {
    const states: JobState[] = [
      jobState({ connection: "open" }),
      jobState({ connection: "open", checkpoint: checkpoint("planner"), observed: [checkpoint("planner")] }),
      jobState({ connection: "reconnecting", checkpoint: checkpoint("planner"), observed: [checkpoint("planner")] }),
      jobState({ connection: "closed" }),
      jobState({ connection: "opening" }),
    ];
    for (const state of states) {
      const got = spineInputs(state);
      expect(got).not.toBeNull();
      const observation = (got as SpineInputs).observation;
      expect(observation.current).toBe(
        observation.connection === "open" && observation.checkpoints.length > 0,
      );
    }
  });

  it("tells a recycled stream from a dropped one by the frame the server sent", () => {
    const dropped = jobState({ connection: "reconnecting" });
    expect(spineInputs(dropped)?.observation.connection).toBe("reconnecting");

    const recycled = jobState({
      connection: "reconnecting",
      frames: [{ name: "stream_timeout", data: { reconnect: true }, receivedAt: 5 }],
    });
    expect(spineInputs(recycled)?.observation.connection).toBe("recycled");

    // A stream_timeout that is no longer the newest frame is history.
    const past = jobState({
      connection: "reconnecting",
      frames: [
        { name: "stream_timeout", data: null, receivedAt: 5 },
        { name: "node_completed", data: { node: "planner" }, receivedAt: 6 },
      ],
    });
    expect(spineInputs(past)?.observation.connection).toBe("reconnecting");
  });

  it("`opening` is not a connection the spine may call open", () => {
    expect(spineInputs(jobState({ connection: "opening" }))?.observation.connection).toBe(
      "closed",
    );
  });

  it("ages the last frame off a clock the caller supplies, never one it reads", () => {
    const state = jobState({ lastFrameAt: 1_000 });
    expect(spineInputs(state)?.secondsSinceLastFrame).toBeNull();
    expect(spineInputs(state, 42_400)?.secondsSinceLastFrame).toBe(41);
    // A clock that has gone backwards is a clock, not a negative age.
    expect(spineInputs(state, 0)?.secondsSinceLastFrame).toBe(0);
    expect(spineInputs(jobState(), 42_400)?.secondsSinceLastFrame).toBeNull();
  });
});

describe("criterion 1 — the four inputs, and nothing else", () => {
  /** Everything a `JobState` carries that is NOT one of the four inputs. */
  const NOISE: Partial<JobState> = {
    frames: [{ name: "job_started", data: { query: "a question" }, receivedAt: 1 }],
    terminal: { name: "job_completed", shape: "live", receivedAt: 9 },
    failure: { kind: "timeout", message: "", raw: null },
    failureMessage: "a thrown message",
    failureStatus: 504,
    failureSource: "poll",
    unavailableReason: null,
    submission: null,
    review: { action: "approve", inFlight: true },
    unchangedPolls: 7,
    detailSignature: "whatever",
    connectionOpenedAt: 3,
    suspended: true,
  };

  it("two states that differ in every other field produce the same four inputs", () => {
    const base = jobState({
      detail: detail("running"),
      connection: "open",
      checkpoint: checkpoint("planner"),
      observed: [checkpoint("planner")],
      lastFrameAt: 1_000,
    });
    const noisy: JobState = { ...base, ...NOISE, jobId: "a-different-id" };

    // `jobId` is not an input either: it names the run, it does not
    // describe it.
    expect(spineInputs(noisy, 2_000)).toEqual(spineInputs(base, 2_000));
    expect(describeSpine(spineInputs(noisy, 2_000) as SpineInputs)).toEqual(
      describeSpine(spineInputs(base, 2_000) as SpineInputs),
    );
  });

  it("the SpineInputs shape has exactly four members", () => {
    const got = spineInputs(jobState({ detail: detail("running") }));
    expect(Object.keys(got as SpineInputs).sort()).toEqual([
      "observation",
      "plan",
      "secondsSinceLastFrame",
      "status",
    ]);
  });
});

describe("SEGMENT_WORD is total over 03 §3.4's eight statuses", () => {
  it("has eight distinct words for eight distinct statuses", () => {
    expect(SEGMENT_STATUSES).toHaveLength(8);
    const words = SEGMENT_STATUSES.map((status) => SEGMENT_WORD[status]);
    expect(new Set(words).size).toBe(8);
  });

  it("names a connection phase for every value the adapter can produce", () => {
    expect([...SPINE_CONNECTIONS].sort()).toEqual(
      (["closed", "open", "reconnecting", "recycled"] satisfies SpineConnection[]).sort(),
    );
  });
});
