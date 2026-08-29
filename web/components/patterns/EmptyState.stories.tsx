/**
 * Patterns/EmptyState — RC-10's union table, `patterns/` layer.
 *
 * WHY THIS FILE EXISTS. The Gate 3 evidence pack
 * (`docs/revamp/evidence/gate-3/storybook-states.md` §3) records
 * `EmptyState/*` as one of three RC-10 modules with **no story**, which is
 * criterion 1's failure. The pack also records exactly how it slipped:
 * RC-10's discharge sentence named four modules to extend §5.3 with, the
 * union table lists six, and WO-14 criterion 9's story list — which
 * delivered `ThreadRail/*` in full — does not include `EmptyState`. No card
 * ever carried the criterion. This file is that card.
 *
 * THE GROUP NAME. §3 calls it `EmptyState/*`; the shipped title is
 * `Patterns/EmptyState`, which is the layer prefix §2 of the same document
 * already records for nine other pattern groups ("layer prefix only" —
 * expressly not a coverage gap). Beside `Patterns/StatusBanner` and
 * `Patterns/SectionRail` is where a reviewer will look for it.
 *
 * WHAT THE STORIES HAVE TO SHOW, AND IT IS NOT "a grey box". The component
 * exists to stop three different absences from looking the same
 * (`EmptyState.tsx`: `ConversationSidebar.tsx:104-113` renders "Loading…"
 * and "No conversations yet." as two identical rows in the same place). So
 * the set below is the three shapes the product actually composes —
 * bodyless-heading in the rail, heading + body in the thread, and the one
 * with an action — at each of the three heading levels the prop offers, and
 * `Default` is deliberately the one that carries `data-empty-state` and no
 * `aria-busy`, because that pair is the whole structural distinction from
 * the loading state next to it.
 *
 * IT IMPORTS NOTHING BUT COPY, and that is a coverage decision copied from
 * `ThreadList.stories.tsx`. `vitest.config.mts` records the hazard: a module
 * both Vitest projects load has its function list CONCATENATED in the merged
 * report. `lib/copy/threads` is already loaded by both (WO-14's stories), so
 * this file adds no module to the storybook project's graph at all.
 *
 * NO STRING IS RENDERED AS TEXT HERE. `copy/no-inline-text` covers
 * `components/patterns/**`, stories included; every word below arrives from
 * `lib/copy/threads` through a prop.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { Button } from "@/components/primitives/Button";
import { THREAD, THREAD_RAIL } from "@/lib/copy/threads";

import { EmptyState } from "./EmptyState";

const meta = {
  title: "Patterns/EmptyState",
  component: EmptyState,
  args: { body: THREAD_RAIL.empty },
} satisfies Meta<typeof EmptyState>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * 03 §2.2 row 3, as the rail composes it: the sentence and nothing else.
 *
 * No heading, because `THREAD_RAIL.heading` is already the chrome above it
 * and a second one would push the list down for a state whose whole job is
 * not to move it (`EmptyState.tsx`, the `heading` prop's own note).
 *
 * The two assertions are the structural half of "this is not the loading
 * state": the hook a reviewer can grep for is present, and `aria-busy` —
 * which `ThreadList/Loading` really does set — is absent.
 */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(THREAD_RAIL.empty)).toBeVisible();

    const box = canvasElement.querySelector("[data-empty-state]");
    await expect(box).not.toBeNull();
    await expect(box).not.toHaveAttribute("aria-busy");
    await expect(canvas.queryByRole("heading")).toBeNull();
  },
};

/**
 * The default `headingLevel`, which is `h3`.
 *
 * A lone `h3` is not a `heading-order` violation — axe compares each heading
 * with the one before it and this render has none before it — but it is only
 * correct where an `h2` is genuinely overhead, which is why the level is a
 * prop and why the story below exists.
 */
export const WithHeading: Story = {
  args: { heading: THREAD.emptyHeading, body: THREAD.emptyBody },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("heading", { level: 3, name: THREAD.emptyHeading }),
    ).toBeVisible();
  },
};

/**
 * §4 row 5's configuration — `headingLevel: 2`, which is what
 * `ThreadTimeline` passes.
 *
 * Not a preference. On a thread with no run there is no spine between the
 * thread's own `h1` and this heading to supply the level in between, so the
 * default `h3` skips one and axe's `heading-order` caught it on exactly that
 * state (`ThreadTimeline.tsx`, the comment above the `EmptyState` call).
 * `Features/ThreadTimeline/Empty` shows it composed; this shows the prop.
 */
export const HeadingLevelTwo: Story = {
  args: { heading: THREAD.emptyHeading, body: THREAD.emptyBody, headingLevel: 2 },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("heading", { level: 2, name: THREAD.emptyHeading }),
    ).toBeVisible();
  },
};

/**
 * The third level the prop offers, under a heading that makes it correct.
 *
 * Rendered as a real `h2` → `h3` → `h4` descent rather than as a lone `h4`,
 * so the story is also the `heading-order` check for the whole prop range in
 * one render.
 */
export const HeadingLevels: Story = {
  render: (args) => (
    <div className="flex flex-col gap-4 p-4">
      <EmptyState {...args} heading={THREAD.emptyHeading} headingLevel={2} />
      <EmptyState {...args} heading={THREAD.emptyHeading} headingLevel={3} />
      <EmptyState {...args} heading={THREAD.emptyHeading} headingLevel={4} />
    </div>
  ),
  args: { body: THREAD.emptyBody },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const level of [2, 3, 4] as const) {
      await expect(
        canvas.getByRole("heading", { level, name: THREAD.emptyHeading }),
      ).toBeVisible();
    }
  },
};

/**
 * "One control at most: what starts the thing that is missing."
 *
 * The control is a plain `Button` and it is the only interactive element in
 * the box, so an empty state can never become a second place a run is
 * started from by accident — `QueryComposer` is the one place, and it is
 * what `THREAD.emptyBody` points at on the thread surface.
 */
export const WithAction: Story = {
  args: {
    heading: THREAD.emptyHeading,
    body: THREAD_RAIL.empty,
    action: (
      <Button variant="secondary" size="sm">
        {THREAD_RAIL.newThread}
      </Button>
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: THREAD_RAIL.newThread }),
    ).toBeVisible();
    // One control at most — asserted, not assumed.
    await expect(canvas.getAllByRole("button")).toHaveLength(1);
  },
};

/**
 * The rail's real width (`--layout-rail-width`, 260px), because that is the
 * one measurement a full-bleed render cannot make: the sentence has to wrap
 * inside the rail rather than widen it.
 */
export const InTheRail: Story = {
  decorators: [
    (Story) => (
      <div className="w-rail border border-border-subtle bg-surface">
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(THREAD_RAIL.empty)).toBeVisible();
  },
};

/** 03 §2.2 row 8 as an explicit render rather than only as a toolbar axis. */
export const Dark: Story = {
  args: { heading: THREAD.emptyHeading, body: THREAD.emptyBody, headingLevel: 2 },
  globals: { theme: "dark" },
};

/**
 * RC-17's question, on the surface that has the least to lose: with every
 * `--color-*` role collapsed onto system colours, an empty state that said
 * what it said through hue alone would say nothing. This one says it in
 * words, so it survives.
 */
export const ForcedColours: Story = {
  args: { heading: THREAD.emptyHeading, body: THREAD.emptyBody, headingLevel: 2 },
  globals: { theme: "forced-colors" },
};
