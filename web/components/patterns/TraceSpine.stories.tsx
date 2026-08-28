/**
 * TraceSpine/ — 03 §5.4's twelve states, plus the two renderings that are
 * not one of them (WO-15 criterion 11).
 *
 * READ `AllStates` FIRST. It is the whole table on one page, and it is
 * where the design's claim is checkable at a glance: every row draws its
 * own blind spot, and no row draws a stage that was not observed.
 *
 * THE ONE THING TO LOOK FOR IN EVERY STORY. The dashed void in the Run
 * segment is dimensioned and STATIC — flip the Motion toolbar to "reduced"
 * and it does not change, because it never moved (03 §5.6: "the one thing
 * that must never animate is the region the UI knows nothing about,
 * because motion there would read as activity"). The pulsing `Live` mark is
 * the product's only ambient motion and appears ONLY where an EventSource
 * is open — `RunningWithCheckpoint`, `RunningNoCheckpoint`, `StatusUnknown`
 * and `AwaitingReview`. It is gone in `Reconnecting` and `StreamTimeout`
 * while the ticks stay, which is 03 §5.4's "ticks kept, then a broken
 * rule".
 *
 * WHAT IS DELIBERATELY MISSING FROM `Succeeded`. 03 §5.4 prints "Complete
 * in 74.3 s · quality 0.86 · $0.4231 · 11 calls" for a succeeded run. None
 * of those four values is among §5.2's four inputs, so the spine says
 * "Complete" and WO-19's MetricsStrip says what it cost. A spine that read
 * `cost_usd` would be a spine that reads whatever is nearby.
 *
 * NO STRING IN THIS FILE IS RENDERED AS TEXT. `copy/no-inline-text` covers
 * components/patterns/**, stories included; every label below arrives
 * through `SpineInputs` or as a `parameters` value, which the rule leaves
 * alone by design.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { Plan } from "@/lib/api";
import type { ObservedCheckpoint } from "@/lib/job/types";
import type { SpineInputs, SpineStateId } from "@/lib/spine/state";

import { TraceSpine } from "./TraceSpine";

/**
 * CRITERION 10 — THE INSERTION POINT FOR STRUCTURED EVIDENCE.
 *
 * Per-checkpoint structured evidence — the papers a `searcher` checkpoint
 * found, the claims a `verifier` checked — would attach as a disclosure
 * inside each `CheckpointLedger` entry, fed by a new field on a VERSIONED
 * backend contract. It is a documented insertion point and no code:
 * `node_completed.state_delta` is an open scalar map with no schema
 * (`runner.py:947-955`) and `JobDetail` carries no evidence field at all,
 * so rendering today's delta as "evidence" would present a debug channel
 * as a defensible artefact. 06-WORK-ORDERS.md §7 lists it as not
 * scheduled; nothing in this surface reads `state_delta`.
 */
const EVIDENCE_NOTE =
  "Insertion point (no code): per-checkpoint structured evidence would " +
  "attach as a disclosure inside each ledger entry, behind a versioned " +
  "backend contract. state_delta is an open scalar map with no schema, so " +
  "nothing here reads it.";

const meta = {
  title: "Patterns/TraceSpine",
  component: TraceSpine,
  parameters: {
    docs: { description: { component: EVIDENCE_NOTE } },
  },
  args: { legend: "disclosure" as const },
} satisfies Meta<typeof TraceSpine>;

export default meta;
type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Inputs. Four per story, and only four.
// ---------------------------------------------------------------------------

function checkpoint(node: string, observedAt: number): ObservedCheckpoint {
  return { node, observedAt, stateDelta: {} };
}

/** Opaque labels, verbatim off `web/contract/sse/live_success.jsonl`. */
const THREE: readonly ObservedCheckpoint[] = [
  checkpoint("planner", 1_000),
  checkpoint("searcher", 2_000),
  checkpoint("synthesizer", 3_000),
];

const ONE: readonly ObservedCheckpoint[] = [checkpoint("planner", 1_000)];

const PLAN: Plan = {
  sub_questions: [
    "Which faithfulness metrics are used for retrieval-augmented systems?",
    "How are they validated against human judgement?",
  ],
  search_queries: ["retrieval augmented generation faithfulness evaluation"],
};

function inputs(over: Partial<SpineInputs>): SpineInputs {
  return {
    status: null,
    observation: { checkpoints: [], connection: "closed", current: false },
    plan: null,
    secondsSinceLastFrame: null,
    ...over,
  };
}

/** One `SpineInputs` per row of 03 §5.4. Keyed, so none can go missing. */
const STATES: Record<SpineStateId, SpineInputs> = {
  submitting: inputs({ status: "submitting" }),
  awaiting_review: inputs({
    status: "pending_review",
    observation: { checkpoints: ONE, connection: "open", current: true },
    plan: PLAN,
    secondsSinceLastFrame: 4,
  }),
  running_observed: inputs({
    status: "running",
    observation: { checkpoints: THREE, connection: "open", current: true },
    secondsSinceLastFrame: 41,
  }),
  rejoined: inputs({
    status: "running",
    observation: { checkpoints: [], connection: "open", current: false },
  }),
  reconnecting: inputs({
    status: "running",
    observation: { checkpoints: THREE, connection: "reconnecting", current: false },
    secondsSinceLastFrame: 12,
  }),
  recycled: inputs({
    status: "running",
    observation: { checkpoints: ONE, connection: "recycled", current: false },
    secondsSinceLastFrame: 60,
  }),
  succeeded: inputs({
    status: "succeeded",
    observation: { checkpoints: THREE, connection: "closed", current: false },
  }),
  historic: inputs({ status: "succeeded" }),
  failed_observed: inputs({
    status: "failed",
    observation: { checkpoints: THREE, connection: "closed", current: false },
  }),
  failed_unobserved: inputs({ status: "failed" }),
  cancelled: inputs({ status: "cancelled" }),
  expired: inputs({ status: "unavailable" }),
};

/** §4's state C: attached, and the API has not reported a status. */
const STATUS_NOT_REPORTED: SpineInputs = inputs({
  observation: { checkpoints: [], connection: "open", current: false },
});

// ---------------------------------------------------------------------------
// The thirteen.
// ---------------------------------------------------------------------------

/** No run on screen at all. The shape, and no claim about anything. */
export const NoJob: Story = { args: { inputs: null } };

/** §4 state C. "Its status is not reported yet" — never "unknown". */
export const StatusUnknown: Story = { args: { inputs: STATUS_NOT_REPORTED } };

/** §2.2 row 12: rejoined after a reload. The run segment is fully dashed. */
export const RunningNoCheckpoint: Story = { args: { inputs: STATES.rejoined } };

/** §2.2 row 10. Three ticks, then the void, then the sentence about it. */
export const RunningWithCheckpoint: Story = { args: { inputs: STATES.running_observed } };

/** §2.2 row 11. Ticks kept; the rule breaks; the ambient pulse stops. */
export const Reconnecting: Story = { args: { inputs: STATES.reconnecting } };

/** §2.2 row 25. The server recycled the stream; the run did not stop. */
export const StreamTimeout: Story = { args: { inputs: STATES.recycled } };

/** §2.2 row 9. The pause, and the one sentence that describes it. */
export const AwaitingReview: Story = { args: { inputs: STATES.awaiting_review } };

/**
 * The same pause, one poll earlier.
 *
 * `plan_ready` arrives over SSE before the liveness poll has re-read the
 * status, so the job detail still says `running` while a plan is already in
 * hand. Input 3 is non-null only during the review pause
 * (`schemas.py:98-124`), which makes it as good an authority for the pause
 * as the status is — and it is the authority that arrives first.
 */
export const AwaitingReviewBeforeThePoll: Story = {
  args: {
    inputs: inputs({
      status: "running",
      observation: { checkpoints: ONE, connection: "open", current: true },
      plan: PLAN,
      secondsSinceLastFrame: 1,
    }),
  },
};

/** Watched to the end: the ledger is what this connection saw. */
export const Succeeded: Story = { args: { inputs: STATES.succeeded } };

/** D-010: `job.plan = None` is permanent, so history keeps no lineage. */
export const SucceededFromHistory: Story = { args: { inputs: STATES.historic } };

/** §2.2 row 15, with nothing observed: "Failed." and no attribution. */
export const Failed: Story = { args: { inputs: STATES.failed_unobserved } };

/** H3: "after the last observed checkpoint", never "failed in". */
export const FailedAfterCheckpoint: Story = { args: { inputs: STATES.failed_observed } };

/** §2.2 row 13. The review pause is the only cancellation point there is. */
export const Cancelled: Story = { args: { inputs: STATES.cancelled } };

/** §2.2 row 16. Retention, not deletion and not permission (H8). */
export const Unavailable: Story = { args: { inputs: STATES.expired } };

/** Submitting: `POST /research` is in flight and no run exists yet. */
export const Submitting: Story = { args: { inputs: STATES.submitting } };

// ---------------------------------------------------------------------------
// The three axes.
//
// THERE IS DELIBERATELY NO "ALL TWELVE ON ONE PAGE" STORY. A `<section>`
// named by a heading is a `region` LANDMARK, and twelve of them with the
// same accessible name is an axe `landmark-unique` violation — a real one,
// not a false positive: a screen-reader user really cannot tell twelve
// identically named regions apart. The product renders one spine, the
// twelve rows are the twelve stories above, and the theme and motion
// toolbars are an axis on every one of them (§4 row 8) rather than a
// gallery that has to be exempted from the gate.
// ---------------------------------------------------------------------------

/** The legend 03 §5.3 shows once per session, before it goes behind a toggle. */
export const LegendOpen: Story = {
  args: { inputs: STATES.running_observed, legend: "open" },
};

export const Dark: Story = {
  args: { inputs: STATES.running_observed },
  globals: { theme: "dark" },
};

/** The RC-17 claim: a word and a shape per status, with the hue removed. */
export const ForcedColours: Story = {
  args: { inputs: STATES.failed_observed, legend: "open" },
  globals: { theme: "forced-colors" },
};

/**
 * The one that has to look IDENTICAL to `RunningWithCheckpoint` in the
 * blind spot, and different only in that the `Live` mark has stopped.
 */
export const ReducedMotion: Story = {
  args: { inputs: STATES.running_observed },
  globals: { motion: "reduce" },
};

/** 320px is the narrowest RC-14 viewport; the spine wraps rather than pans. */
export const Narrow: Story = {
  args: { inputs: STATES.running_observed },
  globals: { viewport: { value: "w320" } },
};
