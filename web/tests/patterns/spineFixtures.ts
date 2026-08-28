/**
 * One `SpineInputs` per row of 03 §5.4, and nothing else in this file.
 *
 * WHY THE FIXTURES ARE SHARED. WO-15 criterion 3 is "no forbidden string
 * from §5.5 is producible by ANY spine state — driven over all twelve
 * states", and criterion 5 is "a test with colour and images disabled still
 * distinguishes all eight statuses". Both are sweeps over the same twelve
 * inputs, and a sweep that quietly covers eleven of them is exactly the
 * failure the criteria are written against. `EVERY_STATE` is keyed by
 * `SpineStateId`, so TypeScript refuses a missing row and the tests assert
 * that each fixture really lands on the state it is filed under.
 *
 * Not a `.test.ts`, so the `unit` project does not collect it as a suite.
 */

import type { Plan } from "@/lib/api";
import type { ObservedCheckpoint } from "@/lib/job/types";
import type { SpineInputs, SpineStateId } from "@/lib/spine/state";

/** Opaque labels, verbatim off `web/contract/sse/live_success.jsonl`. */
export function checkpoint(node: string, observedAt = 1_000): ObservedCheckpoint {
  return { node, observedAt, stateDelta: {} };
}

export const THREE: readonly ObservedCheckpoint[] = [
  checkpoint("planner", 1_000),
  checkpoint("searcher", 2_000),
  checkpoint("synthesizer", 3_000),
];

export const ONE: readonly ObservedCheckpoint[] = [checkpoint("planner")];

export const PLAN: Plan = {
  sub_questions: ["How is faithfulness measured?", "Which benchmarks are used?"],
  search_queries: ["retrieval augmented generation faithfulness"],
};

/** A closed connection that observed nothing. The commonest shape. */
function inert(status: SpineInputs["status"]): SpineInputs {
  return {
    status,
    observation: { checkpoints: [], connection: "closed", current: false },
    plan: null,
    secondsSinceLastFrame: null,
  };
}

/** 03 §5.4's twelve rows, in the order the table prints them. */
export const EVERY_STATE: Record<SpineStateId, SpineInputs> = {
  submitting: inert("submitting"),

  awaiting_review: {
    status: "pending_review",
    observation: { checkpoints: ONE, connection: "open", current: true },
    plan: PLAN,
    secondsSinceLastFrame: 4,
  },

  running_observed: {
    status: "running",
    observation: { checkpoints: THREE, connection: "open", current: true },
    plan: null,
    secondsSinceLastFrame: 41,
  },

  // "Running, rejoined after reload": the run segment is fully dashed and
  // the ledger is empty, because this connection has seen nothing yet.
  rejoined: {
    status: "running",
    observation: { checkpoints: [], connection: "open", current: false },
    plan: null,
    secondsSinceLastFrame: null,
  },

  // "Reconnecting": the ticks are KEPT and `current` is false — WO-10's
  // `checkpointIsCurrent` goes false the moment a connection ends.
  reconnecting: {
    status: "running",
    observation: { checkpoints: THREE, connection: "reconnecting", current: false },
    plan: null,
    secondsSinceLastFrame: 12,
  },

  recycled: {
    status: "running",
    observation: { checkpoints: ONE, connection: "recycled", current: false },
    plan: null,
    secondsSinceLastFrame: 60,
  },

  succeeded: {
    status: "succeeded",
    observation: { checkpoints: THREE, connection: "closed", current: false },
    plan: null,
    secondsSinceLastFrame: null,
  },

  // Loaded from thread history, or reattached after the run had already
  // finished — the same situation to a client with no replay backlog.
  historic: inert("succeeded"),

  failed_observed: {
    status: "failed",
    observation: { checkpoints: THREE, connection: "closed", current: false },
    plan: null,
    secondsSinceLastFrame: null,
  },

  failed_unobserved: inert("failed"),

  cancelled: inert("cancelled"),

  expired: inert("unavailable"),
};

/**
 * §4's state C — attached, and the API has not said what the run is doing.
 *
 * It lands on the `rejoined` row (H2: after a reload the position is
 * unknown and the UI says so) with a sentence that claims no status at all.
 */
export const STATUS_UNKNOWN: SpineInputs = {
  status: null,
  observation: { checkpoints: [], connection: "open", current: false },
  plan: null,
  secondsSinceLastFrame: null,
};

/** A checkpoint whose payload carried no usable label. Renders "not reported". */
export const UNLABELLED: readonly ObservedCheckpoint[] = [checkpoint("")];
