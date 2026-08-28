/**
 * CheckpointLedger/ — RC-10's fourth uncovered component (WO-15 c11).
 *
 * The ledger gets its own group because it has states the `TraceSpine/`
 * group never puts it in: empty on its own (the spine hides it and lets the
 * status line carry the count), forty entries that have to PAN rather than
 * reflow the page, and an entry whose payload named nothing.
 *
 * `UnknownNodeLabel` IS THE ONE TO OPEN. Its name is the bug it exists
 * against: `lib/job/machine.ts`'s `checkpointLabel()` still returns the
 * literal "unknown" for an absent label, that word is banned product-wide
 * (03 §5.5 — "not reported", because silence is the API's behaviour and not
 * a gap in our knowledge of it), and the story shows what the surface
 * actually renders instead. Nothing on this page is a guess: every label is
 * a string that arrived in a `node_completed` payload, or the dictionary's
 * word for one that did not.
 *
 * NO STRING IN THIS FILE IS RENDERED AS TEXT. Node labels are DATA — the
 * API's words, passed through verbatim (H11) — and they reach the DOM as a
 * prop, which is the only way they ever should.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { ObservedCheckpoint } from "@/lib/job/types";

import { CheckpointLedger } from "./CheckpointLedger";

const meta = {
  title: "Patterns/CheckpointLedger",
  component: CheckpointLedger,
  args: { checkpoints: [], current: true },
} satisfies Meta<typeof CheckpointLedger>;

export default meta;
type Story = StoryObj<typeof meta>;

function checkpoint(node: string, observedAt: number): ObservedCheckpoint {
  return { node, observedAt, stateDelta: {} };
}

/** Verbatim off `web/contract/sse/live_success.jsonl`. */
const THREE: ObservedCheckpoint[] = [
  checkpoint("planner", 1_000),
  checkpoint("searcher", 2_000),
  checkpoint("synthesizer", 3_000),
];

/**
 * Nothing observed yet.
 *
 * The spine passes `empty="hidden"` here and lets its own status line say
 * "No checkpoints observed on this connection"; on its own the ledger says
 * it, with the qualifier that makes it true.
 */
export const Empty: Story = { args: { checkpoints: [] } };

export const SingleCheckpoint: Story = {
  args: { checkpoints: [checkpoint("planner", 1_000)] },
};

export const ThreeCheckpoints: Story = { args: { checkpoints: THREE } };

/**
 * Long enough to pan.
 *
 * 04 §8.3 item 4: the LIST scrolls and the PAGE does not. Set the viewport
 * to 320 and drag — the reading column stays put, which is the same
 * property the CLS budget protects when a tick arrives.
 */
export const Many: Story = {
  args: {
    checkpoints: Array.from({ length: 24 }, (_, index) =>
      checkpoint(`checkpoint_${index}`, index * 1_000),
    ),
  },
};

/**
 * After a reconnect gap.
 *
 * `web/contract/sse/reconnect_gap.jsonl` records a `node_completed` for
 * `searcher` published while nobody was subscribed. Redis pub/sub keeps no
 * backlog and the stream writes no `id:` line, so it is gone — and this is
 * what the ledger shows on the NEW connection: what arrived on it, and
 * nothing else. `searcher` appears nowhere on this page.
 */
export const AfterReconnectGap: Story = {
  args: { checkpoints: [checkpoint("synthesizer", 9_000)], current: true },
};

/**
 * The same ledger, after the connection that observed it ended.
 *
 * The ticks are KEPT — they really were observed — and `current` is false,
 * which is what stops the surface implying they describe now (03 §5.4,
 * "Reconnecting: ticks kept, then a broken rule").
 */
export const NotCurrent: Story = { args: { checkpoints: THREE, current: false } };

/**
 * A `node_completed` whose payload carried no usable label.
 *
 * "not reported", never "unknown". There is no vocabulary to fall back on:
 * the node set is configuration-dependent (`workflow.py:366-430`) and
 * `state_delta` is an open scalar map, so absence is reported rather than
 * named.
 */
export const UnknownNodeLabel: Story = {
  args: { checkpoints: [checkpoint("planner", 1_000), checkpoint("", 2_000)] },
};

/** An opaque label from a graph this client has never heard of (H11). */
export const OpaqueLabel: Story = {
  args: { checkpoints: [checkpoint("claim_decomposer", 1_000)] },
};

export const Dark: Story = { args: { checkpoints: THREE }, globals: { theme: "dark" } };

export const ForcedColours: Story = {
  args: { checkpoints: THREE },
  globals: { theme: "forced-colors" },
};
