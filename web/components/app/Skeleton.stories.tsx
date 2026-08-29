/**
 * Shell/Skeleton — the thread route's loading state (03 §2.2 row 6),
 * inside the shell it actually loads into.
 *
 * DISTINCT FROM `Primitives/Skeleton`, which documents the bar. This
 * documents the *reservation*: which boxes are held open, at which heights,
 * and against which loaded geometry. That claim is only visible with the
 * shell around it, because the shell is what makes the report column's
 * height definite — `.ew-shell__surface` is a fixed-height box
 * (workbench.css), so `min-h-0 flex-1` inside it resolves to the remaining
 * track rather than to the content's own height. A skeleton whose height
 * comes from its content cannot promise CLS 0; this one's comes from the
 * container, in both the loading and the loaded state.
 *
 * `Loaded` is the same shell rendering a stand-in for the arrived thread,
 * with the same header geometry. Flipping between the two stories in the
 * sidebar is the visual form of the CLS claim: the title row, the meta row
 * and the top of the report column do not move. The measured number — a
 * Lighthouse run against `next start` over the cold-load transition — is in
 * the PR body, because CLS is a browser measurement and a story cannot make
 * it.
 *
 * NOTHING SHIMMERS. 03 §3.7 forbids skeleton shimmer by name, so there is
 * no motion here to lose under `prefers-reduced-motion` — which is why this
 * file has no reduced-motion story: it would be byte-identical.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { ThreadSkeleton } from "@/components/patterns/ThreadSkeleton";
import { RECOVERY } from "@/lib/copy/recovery";
import { turnCount } from "@/lib/copy/threads";

import { WorkbenchShell } from "./WorkbenchShell";

/** The rail's shape, with no `GET /conversations` behind it. */
const RAIL = (
  <ul className="flex flex-col gap-1 p-3">
    {["Retrieval-augmented verification", "Sparse attention survey"].map((title, index) => (
      <li key={title}>
        <a
          href={`/c/thread-${index + 1}`}
          className="ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken"
        >
          {title}
        </a>
      </li>
    ))}
  </ul>
);

const meta = {
  title: "Shell/Skeleton",
  component: ThreadSkeleton,
  parameters: { nextjs: { appDirectory: true } },
  // Through `render`, not `decorators`: story-level decorators COMPOSE with
  // the meta's, so the narrow-mode story below would otherwise sit inside
  // two shells and fail `landmark-no-duplicate-main` for a reason that
  // exists only in the harness.
  render: () => (
    <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
      <ThreadSkeleton />
    </WorkbenchShell>
  ),
} satisfies Meta<typeof ThreadSkeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Loading: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    // Criterion 2 holds here too: the surface has an `h1`. It is clipped,
    // because the thread's title is exactly what has not arrived — and a
    // heading that is drawn and then replaced is the layout shift this
    // component exists to remove.
    await expect(
      canvas.getByRole("heading", { level: 1, name: RECOVERY.loadingHeading }),
    ).toBeInTheDocument();

    const surface = canvasElement.querySelector('[data-recovery-surface="loading"]');
    await expect(surface).not.toBeNull();
    await expect(surface?.getAttribute("aria-busy")).toBe("true");

    // The bars are hidden from assistive technology: a placeholder read
    // aloud is a stutter of nothing.
    const bars = canvasElement.querySelectorAll(".ew-skeleton");
    await expect(bars.length).toBeGreaterThan(0);
    for (const bar of bars) {
      await expect(bar.getAttribute("aria-hidden")).toBe("true");
    }
  },
};

/**
 * The arrived thread, at the geometry the skeleton reserved. The header's
 * padding, its two line boxes and its bottom rule are the ones
 * `ThreadSkeleton`'s header holds open; the transcript fills the same
 * `min-h-0 flex-1` track the placeholder lines filled.
 */
export const Loaded: Story = {
  render: () => (
    <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
      <div className="flex h-full flex-col">
        <header className="border-b border-border-subtle px-6 py-4">
          <h1 className="truncate text-ui-xl font-semibold tracking-tight text-ink">
            Retrieval-augmented verification
          </h1>
          {/*
            The meta line comes from the dictionary's own composer rather
            than from a typed string: "3 turns" is exactly the shape
            `turnCount` exists to get right, and a stand-in that hand-types
            it is a stand-in that can drift from the thing it stands in for.
          */}
          <p className="mt-05 text-ui-xs text-ink-muted">
            {turnCount(3)} · 12 Mar 2026, 09:41
          </p>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <p className="max-w-measure text-report-body text-ink">
            The briefing arrives into the track the placeholder lines held
            open, so the reading position does not move when it does.
          </p>
        </div>
      </div>
    </WorkbenchShell>
  ),
};

/** Below 768px, where the rail is absent from the layout entirely. */
export const Narrow: Story = {
  globals: { viewport: { value: "w412" } },
  render: () => (
    <WorkbenchShell rail={RAIL} railMode="drawer">
      <ThreadSkeleton />
    </WorkbenchShell>
  ),
};
