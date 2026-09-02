/**
 * Shell/WorkbenchShell — criterion 11's five shell states, which are the
 * five 03-DESIGN-BRIEF.md §4.1 names: rail expanded, rail collapsed, drawer
 * closed, drawer open, offline.
 *
 * WHY EVERY STORY PASSES `railMode` INSTEAD OF SETTING A VIEWPORT. The
 * stories execute as component tests in jsdom (vitest.config.mts's
 * `storybook` project), and jsdom has no layout: `matchMedia("(min-width:
 * 1024px)")` cannot tell you which of the three modes a 320px toolbar
 * setting implies. Driving the mode by prop is what makes each state
 * deterministic in the test run *and* pickable from the toolbar in the
 * browser. The viewport toolbar still does its job there — the CSS in
 * workbench.css is what responds to it.
 *
 * WHY THE RAIL IS A STAND-IN. Two reasons, and the second is the
 * interesting one:
 *
 *   1. The real rail is `components/ConversationSidebar.tsx`, which fetches
 *      `GET /conversations` on mount. 04-ARCHITECTURE.md §5.1's layer rule
 *      is that a story needs no MSW and no network, and the shell's `rail`
 *      prop is the seam that keeps that true.
 *   2. The stand-in reproduces the one piece of the legacy rail's markup
 *      that interacts with the shell's landmarks: an **unlabelled
 *      `<aside>`** (ConversationSidebar.tsx:89). Nested inside
 *      `nav[aria-label="Threads"]`, HTML-AAM maps that aside to `generic`
 *      rather than `complementary` — an `aside` scoped to sectioning
 *      content and without an accessible name is not a landmark — so it
 *      cannot produce a nested-landmark finding. That is an assertion about
 *      axe's behaviour, so it is made where axe actually runs.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, screen, userEvent, waitFor } from "storybook/test";

import { railIsAvailable, railPresentation } from "@/.storybook/storyRail";
import { THREAD_RAIL, WORKSPACE, WORKSPACE_PILOT } from "@/lib/copy/threads";
import { RAIL_COLLAPSED_STORAGE_KEY } from "@/lib/tokens";

import { WorkbenchShell } from "./WorkbenchShell";

/** The legacy rail's markup shape, with no network behind it. */
function RailStandIn() {
  return (
    <aside className="flex h-full w-rail shrink-0 flex-col bg-surface">
      <div className="p-3">
        <button
          type="button"
          className="ew-focusable ew-target ew-target--sm w-full rounded-md border border-border-strong bg-surface px-3 text-ui-sm font-medium text-ink"
        >
          + New conversation
        </button>
      </div>
      <p className="px-3 pb-2 text-ui-xs font-semibold uppercase tracking-wide text-ink-faint">
        Recent
      </p>
      <ul className="flex flex-col gap-1 px-2">
        {["Retrieval-augmented verification", "Sparse attention survey", "Eval harness drift"].map(
          (title, index) => (
            <li key={title}>
              <a
                href={`/c/thread-${index + 1}`}
                className="ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken"
              >
                {title}
              </a>
            </li>
          ),
        )}
      </ul>
    </aside>
  );
}

/** Stands in for whatever route is mounted — the landing composer or a thread. */
function WorkSurface() {
  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-6">
      <h1 className="text-ui-xl font-semibold text-ink">Retrieval-augmented verification</h1>
      <p className="max-w-measure text-ui-sm text-ink-muted">
        The route renders here, inside the shell&rsquo;s single
        <code className="font-mono"> &lt;main id=&quot;main&quot;&gt;</code>. In M1 that is
        still the existing landing page or conversation thread, rendered
        unmodified.
      </p>
    </div>
  );
}

const meta = {
  title: "Shell/WorkbenchShell",
  component: WorkbenchShell,
  parameters: {
    // The strip's "Start a new question" control is a `next/link`, which
    // needs the App Router context rather than the Pages Router default.
    nextjs: { appDirectory: true },
  },
  args: {
    rail: <RailStandIn />,
    children: <WorkSurface />,
  },
} satisfies Meta<typeof WorkbenchShell>;

export default meta;
type Story = StoryObj<typeof meta>;

/** ≥1024px, the persistent 260px rail. The default the server renders. */
export const RailExpanded: Story = {
  args: { railMode: "expanded", railCollapsed: false },
};

/** ≥1024px with the persisted collapse preference set: the 56px icon strip. */
export const RailCollapsed: Story = {
  args: { railMode: "expanded", railCollapsed: true },
};

/**
 * The collapse toggle, and the preference it writes.
 *
 * This story deliberately omits `railCollapsed`, so the shell reads the real
 * `localStorage` key — RC-05's second and last persisted preference. The
 * play function is the only place the *write* is demonstrated rather than
 * described; web/tests/shell/shell.test.tsx asserts the same thing without a
 * browser.
 */
export const RailCollapseToggle: Story = {
  args: { railMode: "expanded" },
  // Before the render, not inside the play: the shell reads the preference
  // while it renders, so clearing it afterwards would be too late.
  beforeEach: () => {
    window.localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, "0");
    return () => window.localStorage.removeItem(RAIL_COLLAPSED_STORAGE_KEY);
  },
  // WO-27: the toggle exists only where the rail is laid out. Below `md`
  // `workbench.css` sets `display: none` on `.ew-shell__rail` regardless of
  // the `railMode` prop above, so at 320 and 412 this story's control is not
  // in the accessibility tree — which is the product working, and which used
  // to be 10 of the 48 play-function errors in `evidence/gate-3/known-gaps.md`
  // §2d. See `.storybook/storyRail.ts` for why the branch reads `display`
  // rather than a width.
  play: async ({ canvas }) => {
    if (!railIsAvailable()) {
      await expect(
        canvas.queryByRole("button", { name: THREAD_RAIL.collapse }),
        "below `md` the rail is out of the layout (04 §8.3 repair step 1), so " +
          "its collapse toggle must not be reachable either.",
      ).toBeNull();
      await expect(railPresentation()).toBe("hidden-by-css");
      return;
    }

    await userEvent.click(canvas.getByRole("button", { name: THREAD_RAIL.collapse }));

    await expect(
      canvas.getByRole("button", { name: THREAD_RAIL.expand }),
    ).toBeInTheDocument();
    await expect(window.localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe("1");
  },
};

/**
 * Below 768px. The rail is not in the layout at all (04 §8.3 item 1) — the
 * only way to it is the labelled header button.
 */
export const DrawerClosed: Story = {
  args: { railMode: "drawer" },
};

/**
 * The drawer as an APG modal dialog. Focus is trapped inside it, Escape
 * closes it, and focus returns to the trigger — asserted in
 * web/tests/shell/drawer.test.tsx, because a story is a picture.
 */
export const DrawerOpen: Story = {
  args: { railMode: "drawer", defaultDrawerOpen: true },
  play: async () => {
    // `screen`, not `canvas`: Radix portals the dialog to `document.body`,
    // outside the story's canvas element. The drawer's module is lazy (it
    // carries Radix), so the dialog is one microtask behind first render.
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: THREAD_RAIL.heading })).toBeInTheDocument();
    });
  },
};

/**
 * Offline. The shell states it and does not announce it: 03 §7.3 allows
 * exactly two live regions product-wide and both are spoken for, so the
 * announcement is WO-12's StatusBanner rather than a third.
 */
export const Offline: Story = {
  args: { railMode: "expanded", railCollapsed: false, offline: true },
};

/** 768–1023px: the 56px icon strip, every control named. */
export const IconStrip: Story = {
  args: { railMode: "compact" },
};

export const Dark: Story = {
  args: { ...RailExpanded.args },
  globals: { theme: "dark" },
};

export const ForcedColours: Story = {
  args: { ...RailExpanded.args },
  globals: { theme: "forced-colors" },
};

/* =========================================================================
 * The identity slot's three states (WO-W17b criterion 3).
 *
 * WHY THEY ARE STORIES OF THE SHELL AND NOT OF `IdentitySlot`. The slot
 * component still renders `null` — D-009 is unchanged, and
 * `IdentitySlot.stories.tsx` still asserts it draws nothing. What occupies the
 * identity position is the sentence beside it (03 §6), and that sentence is
 * the shell's to render, so this is where the three states are pickable, where
 * the a11y addon runs axe over them, and where a reviewer can read all three
 * side by side and check that the middle one does not read as a login.
 *
 * EACH STATE IS HERE IN BOTH THEMES because the indicator is the one place in
 * the header where a lead in `text-ink` sits inside a paragraph in
 * `text-ink-muted`, and that pair resolves differently under `[data-theme]`.
 * The dark stories are the same args with one global changed, so a divergence
 * between them would be a fact about the tokens rather than about this
 * component.
 *
 * THE DESCRIPTOR IS A PROP, WHICH IS THE POINT. `lib/server/identity.ts`
 * derives it per request in the two group layouts; the shell takes the answer
 * and renders it. That is what lets these three states exist with no
 * environment, no request, no network and no flag — SR-07's whole argument for
 * why this is not a runtime feature flag.
 * ========================================================================= */

/** Every deployment on `main`: one key, one principal, one shared workspace. */
export const IdentityShared: Story = {
  args: { ...RailExpanded.args, identity: { kind: "shared" } },
  play: async ({ canvas }) => {
    await expect(
      canvas.getByText(WORKSPACE.indicatorDetail, { exact: false }),
    ).toBeVisible();
  },
};

export const IdentitySharedDark: Story = {
  args: { ...IdentityShared.args },
  globals: { theme: "dark" },
};

/**
 * `PILOT_EDGE_AUTH=on`, and the edge vouched for this request.
 *
 * The username is the pilot's own and the browser already collected it from
 * them at the edge's credential dialog, so showing it back is not a new
 * disclosure. The sentence names what is per person AND what is shared,
 * because `docs/runbooks/pilot.md` §8 told each pilot both.
 */
export const IdentityPilot: Story = {
  args: {
    ...RailExpanded.args,
    identity: { kind: "pilot", username: "pilot-ada" },
  },
  play: async ({ canvas }) => {
    await expect(canvas.getByText(WORKSPACE_PILOT.indicator)).toBeVisible();
    await expect(canvas.getByText(/pilot-ada/)).toBeVisible();
    // The sentence this work order exists to remove must be gone, not merely
    // qualified — a header carrying both would be worse than either.
    await expect(canvas.queryByText(WORKSPACE.indicator)).toBeNull();
  },
};

export const IdentityPilotDark: Story = {
  args: { ...IdentityPilot.args },
  globals: { theme: "dark" },
};

/**
 * Pilot mode is on and this request resolved to nobody.
 *
 * A spoofed username header, a missing edge secret, a username nobody was
 * issued, or a configuration the deployment refuses to serve under — the slot
 * says the same thing for all of them, names no pilot, and gives no fault. The
 * distinction between them is the operator's, and it reaches them through the
 * `pilot_principal` log line.
 */
export const IdentityUnresolved: Story = {
  args: { ...RailExpanded.args, identity: { kind: "unresolved" } },
  play: async ({ canvas }) => {
    await expect(
      canvas.getByText(WORKSPACE_PILOT.unresolvedIndicator),
    ).toBeVisible();
    await expect(canvas.queryByText(WORKSPACE.indicator)).toBeNull();
    await expect(canvas.queryByText(/pilot-ada/)).toBeNull();
  },
};

export const IdentityUnresolvedDark: Story = {
  args: { ...IdentityUnresolved.args },
  globals: { theme: "dark" },
};
