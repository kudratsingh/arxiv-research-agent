/**
 * Session — WO-W13 criterion 3.
 *
 * ONE STORY PER §4.2 SESSION STATE, NAMED AFTER THE STATE.
 * `05-WEDGE-WORK-ORDERS.md` §4.2 rows 6-16 name the twelve story ids this
 * card owes: `Session/CheckIn`, `Session/Passage`, `Session/AwaitingTurn`,
 * `Session/Working`, `Session/ExplainBack`, `Session/Probe`,
 * `Session/Complete`, `Session/Unassessed`, `Session/AtCap`,
 * `Session/Reconnecting`, `Session/Resumed`, `Session/Unavailable`. The
 * exports below ARE that list — the meta title is the group prefix, so an
 * id in the table and an id in Storybook are the same string and a reviewer
 * can walk one against the other. Three stories sit beyond the table
 * (`AtCapDegradedClose`, `TranscriptUnavailable`, `Stopped`) because the
 * card's scope names behaviours the table's row counts as one.
 *
 * AXE IS NOT WIRED HERE, AND THAT IS THE POINT. `.storybook/preview.ts`
 * runs the baseline's tag set over every story with `test: "error"`, so the
 * Vitest addon fails the story on a violation. Row 20's dark axis is the
 * theme global, applied the same way. Nothing in this file opts in, and
 * nothing in it could opt out.
 *
 * WHY THE IMPORT LIST IS SHORT. `web/vitest.config.mts` records the
 * measurement hazard for WO-13 … WO-19: a module both Vitest projects load
 * has its function list CONCATENATED in the merged coverage report, so a
 * story importing a module it does not exercise moves the functions column
 * without changing a line of product code. This file imports the component,
 * its copy file, the renderer boundary it drives, and two recorded
 * fixtures. `@/lib/api` is imported for TYPES only — `import type` is
 * erased, so it never joins either project's module graph.
 *
 * THE SESSION BODIES ARE RECORDED, NOT AUTHORED. Every story starts from
 * `contract/fixtures/learn.session.awaiting.json` and overrides the fields
 * the state is about, so no story can pass against a `SessionDetail` shape
 * the API does not produce. The transcript entries and the turn prompts are
 * sample DOCUMENTS — a learner's own prose and a tutor's question are data,
 * not product copy; every word of product copy on screen comes from
 * `lib/copy/learn` through the component.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, within } from "storybook/test";

import pathFixture from "@/contract/fixtures/learn.path.detail.json";
import sessionFixture from "@/contract/fixtures/learn.session.awaiting.json";
import type { LearnPathDetail, SessionDetail } from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";
import { loadReportRenderer, type ReportRenderer } from "@/lib/report/renderer";

import { GuidedSessionUnavailable, GuidedSessionView } from "./GuidedSessionView";

const path = pathFixture.body as LearnPathDetail;
const awaiting = sessionFixture.body as SessionDetail;
const entry = path.entries[0]!;

/** Two turns already behind the learner. Sample prose, not product copy. */
const transcript: SessionDetail["transcript"] = [
  {
    role: "tutor",
    text: "Before we read this paper, what do you expect it to help you understand?",
  },
  {
    role: "learner",
    text: "I expect a way to model sequence relationships without recurrence.",
  },
];

/** The margin after the explain-back has been written and saved. */
const explainedTranscript: SessionDetail["transcript"] = [
  ...transcript,
  {
    role: "tutor",
    text: "Explain the central move back in your own words, and name one thing you are unsure about.",
  },
  {
    role: "learner",
    text: "Attention lets every position read every other position directly, so the path length between two tokens stops growing with the distance between them. I am unsure why the scaling by the square root of the key dimension matters.",
  },
];

/**
 * The renderer comes from the product's own boundary, through a loader — the
 * same dynamic import a route performs (`lib/report/renderer.ts`), so the
 * briefing companion these stories lay out is parsed by the real pipeline.
 * The loader also removes the async frame: `loaders` resolve before the
 * story renders, so no story is audited or captured as a skeleton.
 */
function rendererFrom(context: { loaded: Record<string, unknown> }): ReportRenderer {
  return context.loaded.renderer as ReportRenderer;
}

const meta = {
  title: "Session",
  component: GuidedSessionView,
  loaders: [async () => ({ renderer: await loadReportRenderer() })],
  args: {
    session: awaiting,
    entry,
    renderer: null,
    machinePhase: "awaiting_learner",
    connection: "open",
    response: "",
    onResponseChange: fn(),
    onSubmit: fn(),
  },
  render: (args, context) => (
    <GuidedSessionView {...args} renderer={rendererFrom(context)} />
  ),
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof GuidedSessionView>;

export default meta;
type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// §4.2 row 6 — check-in, awaiting the learner.
// ---------------------------------------------------------------------------

/** Turn 1. Nothing in the margin yet, because nothing has been said yet. */
export const CheckIn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The composer is `required`, and the primitive appends its own
    // "(required)" indicator to the label — so the accessible name is the
    // label PLUS that indicator, and an exact match would be asserting
    // against a name the product does not render.
    await expect(
      canvas.getByRole("textbox", { name: new RegExp(LEARN.replyLabel) })
    ).toBeVisible();
    await expect(canvas.getByText(LEARN.currentTurnLabel)).toBeVisible();
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 7 — the passage: briefing companion beside the primary source.
// ---------------------------------------------------------------------------

/**
 * The reading surface itself. `ReportReader`'s document surface carries the
 * briefing companion; the arXiv link-out sits in the header beside it,
 * because the paper — not the companion — is the source of record (the
 * path's licensing posture is link-out-only, `02-CONTENT.md` §2.2).
 */
export const Passage: Story = {
  args: { session: { ...awaiting, transcript } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const source = canvas.getByRole("link", { name: LEARN.openPaper });
    await expect(source).toHaveAttribute("href", entry.canonical_url);
    await expect(canvas.getByText(LEARN.passageLabel)).toBeVisible();
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 8 — a tutor turn parked on the learner.
// ---------------------------------------------------------------------------

/**
 * Mid-session: the tutor has responded to the previous answer and asked the
 * next question. The feedback line is the tutor's, verbatim; the surface
 * adds no summary of its own.
 */
export const AwaitingTurn: Story = {
  args: {
    session: {
      ...awaiting,
      transcript,
      turn: {
        turn_number: 2,
        kind: "guided_question",
        phase: "tutor",
        prompt:
          "Which connection between self-attention and the older recurrent approach feels least obvious to you?",
        feedback: "Your opening expectation is saved in the margin above.",
      },
    },
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 9 — a turn in flight.
// ---------------------------------------------------------------------------

/**
 * The honest working state: a heading and a sentence saying what is and is
 * not known. No percentage, no estimate, no fake typing indicator — the
 * service publishes no such number, so the surface shows none.
 */
export const Working: Story = {
  args: {
    session: { ...awaiting, status: "running", turn: null, transcript },
    machinePhase: "live",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEARN.workingHeading })
    ).toBeVisible();
    await expect(
      canvas.queryByRole("textbox", { name: new RegExp(LEARN.replyLabel) })
    ).toBeNull();
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 10 — the explain-back prompt.
// ---------------------------------------------------------------------------

/** `src/agents/tutor.py:323-335` — the `explain_back` turn, as the tutor asks it. */
export const ExplainBack: Story = {
  args: {
    session: {
      ...awaiting,
      transcript,
      turn: {
        turn_number: 4,
        kind: "explain_back",
        phase: "tutor",
        prompt:
          "Explain the paper's central move back in your own words. Include one point you are unsure about; uncertainty is useful evidence.",
        feedback: "Your earlier note has been preserved.",
      },
    },
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 11 — the judge's one grounded follow-up.
// ---------------------------------------------------------------------------

/**
 * `follow_up_probe` (`src/agents/tutor.py:398-413`), offered at most once and
 * never as a revision loop. The tutor's own framing — what happens to the
 * answer — is carried through as feedback rather than restated by the UI.
 */
export const Probe: Story = {
  args: {
    session: {
      ...awaiting,
      transcript: explainedTranscript,
      assessment_status: "assessed",
      turn: {
        turn_number: 6,
        kind: "follow_up_probe",
        phase: "tutor",
        prompt:
          "You said the scaling factor is unclear. What would go wrong in the softmax if the dot products grew with the key dimension?",
        // Mirrors `assessment_probe_agent` in src/agents/tutor.py verbatim.
        // WO-W03b reworded it: the surface renders service copy unedited, so
        // a denial there ("not a grade") plants the frame it rejects.
        feedback:
          "I found one point worth checking, based on the words in your explain-back. Your answer is recorded with the rest of the session.",
      },
    },
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 12 — the close.
// ---------------------------------------------------------------------------

/**
 * One honest line about what this session advanced, and the service's own
 * result beneath it. No score, no percentage, no claim that anything was
 * mastered.
 */
export const Complete: Story = {
  args: {
    session: {
      ...awaiting,
      status: "succeeded",
      turn: null,
      transcript: explainedTranscript,
      assessment_status: "recorded_ungraded",
      result:
        "You identified the paper's use of parallel self-attention and named one open question about the scaling factor.",
    },
    machinePhase: "settled",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEARN.completeHeading })
    ).toBeVisible();
    await expect(canvas.getByText(LEARN.completeAdvance)).toBeVisible();
    await expect(canvas.getByText(LEARN.recordedUngraded)).toBeVisible();
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 13 — the judge did not assess.
// ---------------------------------------------------------------------------

/**
 * A missing assessment is reported as a missing assessment. Not an apology,
 * not a provisional grade, not a spinner that never resolves.
 */
export const Unassessed: Story = {
  args: {
    session: {
      ...awaiting,
      status: "succeeded",
      turn: null,
      transcript: explainedTranscript,
      assessment_status: "unassessed",
      result: "The session closed without an assessment event.",
    },
    machinePhase: "settled",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEARN.unassessedHeading })
    ).toBeVisible();
    await expect(canvas.getByText(LEARN.unassessedBody)).toBeVisible();
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 14 — at the cost cap. WO-W06 publishes two behaviours; both are
// products of the same ceiling and both are shown.
// ---------------------------------------------------------------------------

/** Refused: the next call was not made, and the session says so. */
export const AtCap: Story = {
  args: {
    session: {
      ...awaiting,
      status: "failed",
      turn: null,
      transcript,
      cost_cap_status: "refused",
      cost_cap_message: "No call was made beyond the configured limit.",
    },
    machinePhase: "settled",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEARN.costCapHeading })
    ).toBeVisible();
    await expect(canvas.getByText(LEARN.costCapRefused)).toBeVisible();
  },
};

/** Degraded close: the session ended inside the ceiling rather than past it. */
export const AtCapDegradedClose: Story = {
  args: {
    session: {
      ...awaiting,
      status: "succeeded",
      turn: null,
      transcript,
      cost_cap_status: "degraded_close",
      cost_cap_message: "The bounded close used no further model call.",
      assessment_status: "recorded_ungraded",
      result: "The session ended at the configured cost boundary.",
    },
    machinePhase: "settled",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(LEARN.costCapDegraded)).toBeVisible();
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 15 — the transport states.
// ---------------------------------------------------------------------------

/**
 * The stream dropped. The session is not lost and is not claimed to be
 * progressing: the browser is reattaching to the same session, which is what
 * the line says.
 */
export const Reconnecting: Story = {
  args: { session: { ...awaiting, transcript }, connection: "reconnecting" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(LEARN.reconnecting)).toBeVisible();
  },
};

/**
 * The reload case, and the one criterion 2 proves end to end against the
 * seeded stack: the margin below came out of the durable checkpoint, not out
 * of stream frames this page happened to still be holding.
 */
export const Resumed: Story = {
  args: { session: { ...awaiting, transcript }, restored: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(LEARN.resumed)).toBeVisible();
    await expect(canvas.getByText(transcript[1]!.text)).toBeVisible();
  },
};

/**
 * The job row survived and the checkpoint read did not. Beyond §4.2's rows
 * because it is a state the API can genuinely report
 * (`transcript_status: "unavailable"`), and the honest thing to say is that
 * the margin could not be loaded — not to reconstruct one from frames.
 */
export const TranscriptUnavailable: Story = {
  args: {
    session: { ...awaiting, transcript: [], transcript_status: "unavailable" },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(LEARN.transcriptUnavailable)).toBeVisible();
  },
};

/** The run stopped. What the learner wrote stays on screen. */
export const Stopped: Story = {
  args: {
    session: { ...awaiting, status: "failed", turn: null, transcript },
    machinePhase: "settled",
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 16 — expired, or the flag is off.
// ---------------------------------------------------------------------------

/**
 * One surface for three causes, on purpose: expired, owned by another
 * reader, or turned off. Distinguishing them in the browser would leak
 * whether a session id exists — `src/api/sessions.py` answers 404 to all
 * three for the same reason.
 */
export const Unavailable: Story = {
  render: () => <GuidedSessionUnavailable onRetry={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEARN.sessionUnavailableHeading })
    ).toBeVisible();
    await expect(canvas.getByText(LEARN.sessionUnavailableBody)).toBeVisible();
  },
};

// ---------------------------------------------------------------------------
// §4.2 row 20 — the theme axis. Every story above carries it through the
// global; this one pins the mid-session render in dark explicitly, so the
// group has a dark member even when the toolbar is at its default.
// ---------------------------------------------------------------------------

export const DarkTheme: Story = {
  args: { session: { ...awaiting, transcript } },
  globals: { theme: "dark" },
};
