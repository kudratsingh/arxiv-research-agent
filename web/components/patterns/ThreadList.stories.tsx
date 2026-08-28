/**
 * ThreadRail — the rail's states, as stories (WO-14 criterion 9).
 *
 * WHY THE TITLE IS `ThreadRail` AND THE COMPONENT IS `ThreadList`. RC-10
 * splits the rail in two: `features/ThreadRail.tsx` owns the queries and
 * `patterns/ThreadList.tsx` owns every pixel. 04 §5.3 indexes the state
 * evidence by the SURFACE (`ConversationRail/*`, which RC-12 renames
 * `ThreadRail/*`), not by the module, so the story ids stay the ones the
 * Gate 3 state index names.
 *
 * That split is also what makes these stories cost nothing: 04 §5.1's layer
 * rule is that a pattern's states are reachable by passing props, "so their
 * stories need no MSW and no network". Seven of the rail's eight states are
 * below, driven entirely by props; the eighth — `deleting` — is
 * `DeleteConfirm` with `deletePending`, which is the same dialog with its
 * confirm button busy.
 *
 * IT IMPORTS NO DATA MODULE, DELIBERATELY. vitest.config.mts records the
 * measurement hazard: a module loaded by BOTH Vitest projects has its
 * function denominator concatenated, and an early draft of WO-12's stories
 * cost 9 points of the functions column by importing `@/lib/api`. Nothing
 * here reaches past `lib/copy`.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, screen, userEvent, within } from "storybook/test";

import { THREAD_RAIL, THREAD_ROW, deleteDialog } from "@/lib/copy/threads";

import { ThreadList, type ThreadSummary } from "./ThreadList";

const THREADS: ThreadSummary[] = [
  { id: "thread-1", title: "Retrieval-augmented verification" },
  { id: "thread-2", title: "Sparse attention survey" },
  { id: "thread-3", title: "Eval harness drift" },
];

/**
 * The rail is 260px in the shell (`--layout-rail-width`), and a story that
 * rendered it full-bleed would prove nothing about the one measurement that
 * matters — a title that has to truncate rather than push the overflow menu
 * off the edge.
 */
const meta = {
  title: "ThreadRail",
  component: ThreadList,
  args: { threads: THREADS },
  decorators: [
    (Story) => (
      <div className="h-[26rem] w-rail border border-border-subtle bg-surface">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ThreadList>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * 03 §2.2 row 2. Three rows at real row height with the chrome already
 * drawn, `aria-busy` on the list, and no spinner anywhere.
 */
export const Loading: Story = {
  args: { threads: [], loading: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("list")).toHaveAttribute("aria-busy", "true");
    await expect(canvas.getByRole("heading", { name: THREAD_RAIL.heading })).toBeVisible();
  },
};

/** 03 §2.2 row 3 — distinct from loading and from the error state. */
export const Empty: Story = {
  args: { threads: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(THREAD_RAIL.empty)).toBeVisible();
  },
};

/**
 * The destructive control is in the tab order of every row, at full
 * opacity, with no pointer event anywhere near it — criterion 2, and the
 * defect at `ConversationSidebar.tsx:133`.
 */
export const Populated: Story = {
  args: { activeConversationId: "thread-2" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const menus = canvas.getAllByRole("button", { name: /^Thread actions:/ });
    await expect(menus).toHaveLength(THREADS.length);
    for (const menu of menus) await expect(menu).toBeVisible();
  },
};

/**
 * "Load more" appears only when a page came back full (criterion 7). There
 * is no page count beside it and no "showing N of M": `GET /conversations`
 * returns a bare array with neither a total nor a `has_more` (03 §2.3).
 */
export const PopulatedWithMore: Story = {
  args: { canLoadMore: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: THREAD_RAIL.loadMore }),
    ).toBeVisible();
  },
};

/**
 * 03 §2.2 row 4 — an inline alert at the TOP of the rail, with a Retry that
 * re-runs `GET /conversations` and can reach no mutation at all.
 */
export const Error: Story = {
  args: {
    threads: [],
    notice: {
      sentence: THREAD_RAIL.error,
      recovery: THREAD_RAIL.errorRecovery,
      retryLabel: THREAD_RAIL.retry,
      onRetry: () => {},
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert")).toHaveTextContent(THREAD_RAIL.error);
    await expect(canvas.getByRole("button", { name: THREAD_RAIL.retry })).toBeVisible();
  },
};

/**
 * 03 §2.2 row 24 and §8.2 — the APG modal that replaces `confirm()`, with
 * the ratified sentence. `deletePending` is the eighth rail state
 * (*deleting*): the same dialog with its confirm button busy.
 */
export const DeleteConfirm: Story = {
  args: { pendingDelete: THREADS[0] },
  play: async () => {
    const dialog = await screen.findByRole("dialog");
    const copy = deleteDialog(THREADS[0]?.title ?? "");
    await expect(within(dialog).getByText(copy.body)).toBeVisible();
    await expect(
      within(dialog).getByRole("button", { name: copy.confirm }),
    ).toBeVisible();
  },
};

/**
 * Criterion 1 / R-02. The attached run's own row keeps `?job=` and is the
 * only row that does — every other row would be pointing the parameter at a
 * thread that never had that run.
 */
export const ActiveRunRow: Story = {
  args: { activeConversationId: "thread-1", attachedJobId: "job-4f2c" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const live = canvas.getByRole("link", { name: /Retrieval-augmented/ });
    await expect(live).toHaveAttribute("href", "/c/thread-1?job=job-4f2c");
    await expect(within(live).getByText(THREAD_ROW.live)).toBeVisible();
    await expect(canvas.getByRole("link", { name: /Sparse attention/ })).toHaveAttribute(
      "href",
      "/c/thread-2",
    );
  },
};

/**
 * The overflow menu opened from the keyboard alone — the roving-focus
 * behaviour RC-09 kept the `Menu` primitive for, on the one control in the
 * product that really is a menu.
 */
export const RowMenuOpen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getAllByRole("button", { name: /^Thread actions:/ })[0];
    // `TypeError` rather than `Error`: this module exports a story called
    // `Error`, which shadows the global inside it.
    if (trigger === undefined) throw new TypeError("no row menu rendered");
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    const menu = await screen.findByRole("menu");
    await expect(within(menu).getByRole("menuitem", { name: THREAD_ROW.delete })).toBeVisible();
  },
};
