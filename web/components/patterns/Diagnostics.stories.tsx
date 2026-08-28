/**
 * Diagnostics/* — WO-16 criterion 9.
 *
 * "Stories — `Diagnostics/`: `Collapsed` `Expanded` `Empty` `UnknownEvent`
 * `StreamNote`. This is one of RC-10's four components absent from
 * `04` §5.3, so the group is named explicitly rather than left implied."
 *
 * The title is `Diagnostics`, not `Patterns/Diagnostics`, because that is
 * the group RC-10 names and the one a reviewer will look for beside
 * `SectionRail/*` and `TraceSpine/*`.
 *
 * `Collapsed` is the default state and the one to check first: the panel is
 * `hidden`, so the `role="log"` region is out of the accessibility tree and
 * routine frames are not announced (criterion 2, 03 §7.3).
 *
 * `UnknownEvent` is criterion 3 on screen — `node_started` and
 * `paper_indexed` are names the backend does not emit (`streaming.py:13-35`
 * says `node_started` does not exist at all), and `claim_decomposer` with
 * `decomposition_strategy` is a node label and a `state_delta` key from no
 * vocabulary. Every one of them renders verbatim. The rows below are
 * transcribed from `web/contract/sse/unknown_event_name.jsonl` and
 * `unknown_state_delta_keys.jsonl`; `web/tests/diagnostics/Diagnostics.test.tsx`
 * replays those same recordings through `FakeEventSource` so the two cannot
 * drift silently.
 *
 * `StreamNote` is the risk note: the baseline's raw `stream_note` row
 * (`EventLog.tsx:16`) moves HERE and must not leak back into the primary
 * surface (03 §2.2 rows 11 and 25). It shows a reconnect and a server-side
 * recycle at the duration ceiling as ordinary records.
 *
 * TWO DELIBERATE IMPORT CHOICES, both copied from WO-12's stories and both
 * about the Storybook project's coverage rather than taste. `DiagnosticRecord`
 * is imported as a TYPE, so loading a story does not drag `lib/diagnostics/ring`
 * (and its module-scope buffer) into a run that never pushes to it; and
 * `onCopy` is always supplied, so no story reaches for a clipboard jsdom
 * does not have or loads the redactor.
 *
 * NO STRING IN THIS FILE IS RENDERED AS TEXT. `copy/no-inline-text` covers
 * components/patterns/**, stories included. The literals below are frame
 * names, node labels and `state_delta` keys — wire data, which is exactly
 * what H11 says must pass through untranslated.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { DiagnosticRecord } from "@/lib/diagnostics/ring";

import { Diagnostics } from "./Diagnostics";

/** A fixed wall clock, so no story renders a different time on every run. */
const T0 = Date.UTC(2026, 7, 28, 9, 14, 3, 120);

let nextSeq = 0;

function record(input: Partial<DiagnosticRecord> & Pick<DiagnosticRecord, "kind" | "event">): DiagnosticRecord {
  const seq = nextSeq++;
  return {
    seq,
    at: T0 + seq * 1_400,
    jobId: "baseline-running",
    phase: "live",
    from: null,
    failureKind: null,
    detail: null,
    ...input,
  };
}

/** `live_success.jsonl`'s shape: a start, two checkpoints, a completion. */
const LIVE: DiagnosticRecord[] = [
  record({ kind: "transition", event: "attaching", phase: "attaching", from: "idle" }),
  record({ kind: "connection", event: "open", from: "opening" }),
  record({ kind: "frame", event: "job_started", detail: { job_id: "baseline-running" } }),
  record({
    kind: "frame",
    event: "node_completed",
    detail: { node: "planner", state_delta: { iteration: 0, sub_questions_count: 3 } },
  }),
  record({
    kind: "frame",
    event: "node_completed",
    detail: { node: "searcher", state_delta: { iteration: 1, papers_found: 9 } },
  }),
  record({ kind: "frame", event: "job_completed", detail: { llm_calls: 11 } }),
  record({ kind: "terminal", event: "job_completed", detail: { shape: "live" } }),
  record({ kind: "transition", event: "reconciling", phase: "reconciling", from: "live" }),
];

const meta = {
  title: "Diagnostics",
  component: Diagnostics,
  args: {
    records: LIVE,
    capacity: 200,
    dropped: 0,
    onCopy: () => undefined,
  },
} satisfies Meta<typeof Diagnostics>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Criterion 2. The panel is `hidden`, the live region is out of the tree,
 * and nothing about a running stream is announced.
 */
export const Collapsed: Story = {};

/** The same records, opened. Three columns, panning inside their own box. */
export const Expanded: Story = {
  args: { defaultOpen: true },
};

/**
 * 03 §4.5's fourth state: "No frames received on this connection."
 *
 * The `<table>` is still there — the live region's content does not change
 * shape when it is empty, only its rows.
 */
export const Empty: Story = {
  args: { defaultOpen: true, records: [] },
};

/**
 * Criterion 3. Two names outside `SERVER_EVENT_NAMES`, a node label from no
 * graph, and four `state_delta` keys from no vocabulary — all verbatim.
 */
export const UnknownEvent: Story = {
  args: {
    defaultOpen: true,
    records: [
      record({ kind: "frame", event: "job_started", detail: { job_id: "baseline-running" } }),
      record({ kind: "frame", event: "node_started", detail: { node: "searcher" } }),
      record({
        kind: "frame",
        event: "paper_indexed",
        detail: { arxiv_id: "2601.00001", node: "searcher", score: 0.71 },
      }),
      record({
        kind: "frame",
        event: "node_completed",
        detail: {
          node: "claim_decomposer",
          state_delta: {
            claims_extracted: 14,
            decomposition_strategy: "per-sentence",
            iteration: 1,
            unreleased_feature_flag: true,
          },
        },
      }),
      record({ kind: "frame", event: "node_completed", detail: { node: "searcher", state_delta: {} } }),
    ],
  },
};

/**
 * The risk note (03 §2.2 rows 11 and 25). The raw stream note lives here
 * and nowhere else: a reconnect, a server-side recycle at the duration
 * ceiling, and the normalized failure kind beside them.
 */
export const StreamNote: Story = {
  args: {
    defaultOpen: true,
    dropped: 3,
    records: [
      record({ kind: "frame", event: "job_started", detail: { job_id: "baseline-running" } }),
      record({ kind: "connection", event: "reconnecting", from: "open" }),
      record({ kind: "connection", event: "open", from: "reconnecting" }),
      record({
        kind: "frame",
        event: "stream_timeout",
        detail: { reason: "max_duration", elapsed_sec: 900 },
      }),
      record({
        kind: "failure",
        event: "poll",
        failureKind: "upstream_unavailable",
        detail: { status: 502, error: "upstream returned 502" },
      }),
    ],
  },
};
