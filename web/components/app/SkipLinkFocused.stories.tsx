/**
 * Shell/SkipLinkFocused — the skip link, on a recovery surface, in the one
 * state it is ever visible in.
 *
 * WHY THIS STORY BELONGS TO WO-09 RATHER THAN TO `Primitives/SkipLink`.
 * The primitive's stories document the component; this documents the
 * product claim that survives a 404. 03 §7.2 fixes the tab order as
 * "skip link → header → thread rail → main → composer", and a recovery
 * surface is exactly where that guarantee usually quietly disappears: the
 * framework 404 replaces the document, so there is no skip link, no
 * landmarks and nothing to skip to. Rendering the 404 inside the shell is
 * what keeps all three, and this story is the assertion that it did.
 *
 * `.ew-skip-link` is clipped until `:focus-visible`, then revealed as a
 * fixed overlay at the top-left. jsdom matches no `:focus-visible`, so the
 * REVEAL is a browser claim and this story is where a reviewer sees it;
 * what the play function can assert without layout is the part that
 * actually matters for the keyboard user — that it is the first tab stop in
 * the document, that it points at `#main`, and that `#main` is the single
 * `<main>` the shell renders.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { NotFound } from "@/components/patterns/NotFound";
import { ROUTE_ERROR } from "@/lib/copy/recovery";
import { WORKSPACE } from "@/lib/copy/threads";

import { MAIN_ID, WorkbenchShell } from "./WorkbenchShell";

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

const meta: Meta = {
  title: "Shell/SkipLinkFocused",
  parameters: { nextjs: { appDirectory: true } },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Focused: Story = {
  render: () => (
    <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
      <NotFound
        heading={ROUTE_ERROR.notFoundHeading}
        body={ROUTE_ERROR.notFoundBody}
        actionLabel={ROUTE_ERROR.notFoundAction}
        actionHref="/"
      />
    </WorkbenchShell>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    const skip = canvas.getByRole("link", { name: WORKSPACE.skipToContent });
    await expect(skip).toHaveAttribute("href", `#${MAIN_ID}`);

    // First in the DOM, and therefore first in the tab order without a
    // `tabindex` anywhere (WO-08 criterion 10).
    await userEvent.tab();
    await expect(skip).toHaveFocus();

    // And the thing it skips to is real, and singular.
    const mains = canvasElement.querySelectorAll("main");
    await expect(mains).toHaveLength(1);
    await expect(mains[0]?.id).toBe(MAIN_ID);

    // The recovery surface's own heading is inside that landmark, which is
    // what makes "skip to content" true on a 404 rather than merely
    // present.
    await expect(
      within(mains[0] as HTMLElement).getByRole("heading", {
        level: 1,
        name: ROUTE_ERROR.notFoundHeading,
      }),
    ).toBeInTheDocument();
  },
};
