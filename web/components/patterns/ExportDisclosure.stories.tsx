/**
 * Patterns/ExportDisclosure — WO-19 criterion 7, second group.
 *
 * FOUR OF THE FIVE STORIES ARE STATES 03 §4.8 NAMES: closed, open, absent
 * (no briefing) and error after 409. The fifth, `KeyboardFocus`, is a
 * behaviour rather than a resting layout, so it is a `play` function: it
 * opens the panel from the keyboard, walks it with the arrow keys, dismisses
 * it with Escape and asserts focus is back on the trigger. Criterion 3 asks
 * for that as a test, and `web/tests/patterns/ExportDisclosure.test.tsx`
 * carries the full version; this one runs in the Storybook project so the
 * behaviour is visible in the docs and covered under the axe run too.
 *
 * `UnavailableNoReport` IS A STORY THAT RENDERS NOTHING, deliberately. The
 * control is ABSENT with no briefing (criterion 4), not disabled and not
 * apologetic, so the frame below is empty on purpose — the same shape
 * `SectionRail/Absent` takes for the same reason.
 *
 * `OnFailedRun` IS THE COMPOSED ONE, and it is the only story in this file
 * that reaches for another pattern. Criterion 5 is a claim about a
 * composition — "export is present on a failed run with a retained briefing"
 * — and it cannot be shown by a button on its own. It renders the whole 03
 * §2.2 row 14 surface: WO-18's `ReportReader` with the recorded failure
 * above the briefing, this control in the header's `actions` slot, and the
 * metrics strip in the `metrics` slot BENEATH the briefing, which is the
 * placement criterion 1 asks for.
 *
 * THE IMPORT LIST ADDS NO MODULE TO THE STORYBOOK PROJECT'S GRAPH.
 * `ReportReader`, `lib/report/renderer` and `lib/copy/report` are all
 * already loaded by `ReportReader.stories.tsx`; `@/lib/api` is not loaded by
 * anything and is not imported here either (`web/vitest.config.mts` records
 * why that matters).
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { loadReportRenderer, type ReportRenderer } from "@/lib/report/renderer";

import { ExportDisclosure } from "./ExportDisclosure";
import { MetricsStrip, readRunMetrics } from "./MetricsStrip";
import { ReportReader } from "./ReportReader";

/** `job.succeeded.json`'s id — a recorded one, not a plausible-looking one. */
const JOB_ID = "baseline-succeeded";

/** `job.failed_partial.json`: the run whose export 03 §8.1 refuses to hide. */
const PARTIAL_JOB_ID = "baseline-failed-partial";

const PARTIAL_BRIEFING = [
  "# Partial briefing",
  "",
  "The run retained an incomplete synthesis before verification failed.",
  "",
  "## What remains useful",
  "",
  "- Initial retrieval completed.",
  "- Final claim verification did not complete.",
].join("\n");

/** The same fixture's two backend strings, unedited (RC-16). */
const PARTIAL_FAILURE = {
  errorType: "verification_incomplete",
  error: "Verification stopped before all claims could be checked.",
};

const PARTIAL_METRICS = readRunMetrics({
  iterations: 1,
  quality_score: null,
  cost_usd: 0.18,
  llm_calls: 4,
  elapsed_sec: 36.0,
});

const meta = {
  title: "Patterns/ExportDisclosure",
  component: ExportDisclosure,
  args: { jobId: JOB_ID, hasBriefing: true },
  render: (args) => (
    <div className="max-w-xs p-6">
      <ExportDisclosure {...args} />
    </div>
  ),
} satisfies Meta<typeof ExportDisclosure>;

export default meta;
type Story = StoryObj<typeof meta>;

/** At rest: one button, `aria-expanded="false"`, three links out of reach. */
export const Closed: Story = {};

/** The three formats the backend accepts, as ordinary links in flow. */
export const Open: Story = { args: { defaultOpen: true } };

/**
 * Criterion 3, in the browser: open with the keyboard, traverse, dismiss,
 * and get focus back.
 */
export const KeyboardFocus: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Export" });

    // Open from the keyboard. A real <button> takes Enter, which is half of
    // why criterion 3 says "a real button" rather than "role=button".
    await userEvent.tab();
    await expect(trigger).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    // Arrow into the list and along it.
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("link", { name: "Markdown" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("link", { name: "PDF" })).toHaveFocus();

    // Escape closes it and returns focus, which is the half a disclosure
    // usually forgets.
    await userEvent.keyboard("{Escape}");
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(trigger).toHaveFocus();
  },
};

/**
 * 03 §2.2 row 23, resting: no briefing, so no control. This frame is empty,
 * and that is the state.
 */
export const UnavailableNoReport: Story = { args: { hasBriefing: false } };

/**
 * 03 §2.2 row 23, after the fact: the proxy answered 409 to an export that
 * was offered, and the message names the cause instead of the status code.
 */
export const Refused409: Story = { args: { refused: true } };

/**
 * Criterion 5 — the whole of 03 §2.2 row 14, composed.
 *
 * The failure is a banner ABOVE a briefing that still renders, export sits
 * beside the title, and the metrics are attached BENEATH the body. Nothing
 * in this arrangement knows the run's status: `export_research` gates on a
 * falsy `result` alone (`src/api/routes.py:364-368`), so the only question
 * asked here is whether there is a briefing.
 */
export const OnFailedRun: Story = {
  args: { jobId: PARTIAL_JOB_ID, defaultOpen: true },
  loaders: [async () => ({ renderer: await loadReportRenderer() })],
  render: (args, context) => (
    <div className="p-6">
      <ReportReader
        markdown={PARTIAL_BRIEFING}
        renderer={context.loaded.renderer as ReportRenderer}
        failure={PARTIAL_FAILURE}
        actions={<ExportDisclosure {...args} />}
        metrics={<MetricsStrip metrics={PARTIAL_METRICS} />}
      />
    </div>
  ),
};

/** 03 §2.2 row 8 — the same control on the dark token set. */
export const Dark: Story = {
  args: { defaultOpen: true },
  globals: { theme: "dark" },
};
