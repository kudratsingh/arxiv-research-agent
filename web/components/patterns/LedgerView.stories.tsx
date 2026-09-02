import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import progressFixture from "@/contract/fixtures/learn.progress.json";
import type { LearnerProgressSummary } from "@/lib/api";
import { LEDGER, scheduleFigure } from "@/lib/copy/ledger";

import { LedgerUnavailable, LedgerView } from "./LedgerView";

/**
 * The three Ledger states of §4.2's coverage table, plus the unavailable
 * surface the feature falls back to — one story each, so axe runs on every
 * one of them in both themes (the theme decorator is global).
 *
 * The data is `contract/fixtures/learn.progress.json`, which is the verbatim
 * response of the real `/learn/progress` route over the committed raw event
 * log — not an invented object. A story that made up a ledger would be
 * exactly the failure this surface exists to prevent.
 *
 * IMPORTS ARE DELIBERATELY NARROW. `vitest.config.mts`'s measurement hazard:
 * a module loaded by both the unit and the storybook project has its
 * function list concatenated in the merged coverage report. These stories
 * load `lib/copy/ledger` and nothing else from `lib/` at runtime — the
 * `LearnerProgressSummary` import is type-only and erased.
 */

const summary = progressFixture.body as LearnerProgressSummary;

const EMPTY: LearnerProgressSummary = {
  principal_key_id: summary.principal_key_id,
  event_count: 0,
  sessions_per_day: [],
  schedule_progress: [],
  resource_observations: [],
  assessments: [],
  artifacts: [],
};

const meta = {
  title: "Ledger",
  component: LedgerView,
  args: { summary },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof LedgerView>;

export default meta;
type Story = StoryObj<typeof meta>;

/** State 17 — the Ledger with nothing in it. Honest, calm, offering nothing. */
export const Empty: Story = {
  args: { summary: EMPTY },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEDGER.emptyHeading }),
    ).toBeVisible();
    await expect(canvas.getByText(LEDGER.emptyBody)).toBeVisible();

    // Criterion 4: the export is not built, so nothing offers it.
    await expect(canvasElement.querySelectorAll("button, a")).toHaveLength(0);
    await expect(canvasElement.textContent).not.toMatch(/export|download|share/i);

    // And an empty ledger states no arithmetic at all.
    await expect(canvasElement.querySelectorAll("[data-ledger-row]")).toHaveLength(0);
    await expect(
      canvasElement.querySelectorAll("[data-ledger-schedule-row]"),
    ).toHaveLength(0);
  },
};

/** State 18 — populated, every row carrying the record that backs it. */
export const WithEvidence: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEDGER.evidenceHeading }),
    ).toBeVisible();

    // Criterion 1, at story level: three evidence events in the fixture,
    // three rows, and not one of them without an `evidence_ref`.
    const rows = canvasElement.querySelectorAll("[data-ledger-row]");
    await expect(rows).toHaveLength(3);
    for (const row of rows) {
      await expect(row.getAttribute("data-evidence-ref")).toBeTruthy();
      await expect(row.getAttribute("data-event-ids")).toBeTruthy();
    }
    await expect(canvas.getByText("transcript:s-1001#explain-back")).toBeVisible();
    await expect(canvas.getByText("job:9f2c1ab4d7e60351")).toBeVisible();

    // Nothing offers to export the record (criterion 4).
    await expect(canvasElement.textContent).not.toMatch(/export|download|share/i);
  },
};

/** State 19 — session arithmetic, labelled as schedule inside one unit. */
export const ScheduleLabeled: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEDGER.scheduleHeading }),
    ).toBeVisible();

    // Criterion 3: the label and the figure are ONE element's text, so no
    // layout can separate "3 of 3 sessions" from the word that says it is
    // schedule progress rather than knowledge.
    const figures = canvasElement.querySelectorAll("[data-ledger-schedule-figure]");
    await expect(figures).toHaveLength(3);
    for (const figure of figures) {
      await expect(figure.textContent).toContain(LEDGER.scheduleLabel);
    }
    await expect(figures[0]?.textContent).toBe(scheduleFigure("3 of 3 sessions"));

    // A path with no assessment event says so, and is not shown as a zero.
    const unobserved = canvasElement.querySelectorAll(
      '[data-ledger-schedule-row][data-observation="not-observed"]',
    );
    await expect(unobserved).toHaveLength(1);
    await expect(canvas.getByText(LEDGER.notObserved)).toBeVisible();

    // No percentage, no grade, no scalar of any kind reaches the page.
    await expect(canvasElement.textContent).not.toMatch(/%|master|score|grade/i);
  },
};

/** The state the feature falls back to when the record cannot be read. */
export const Unavailable: Story = {
  render: () => <LedgerUnavailable onRetry={() => undefined} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEDGER.unavailableHeading }),
    ).toBeVisible();
    await expect(canvas.getByRole("button", { name: LEDGER.retry })).toBeVisible();
  },
};
