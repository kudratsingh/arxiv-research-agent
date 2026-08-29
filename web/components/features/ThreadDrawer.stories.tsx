/**
 * ThreadRail/Drawer — the rail below 768px (WO-14 criterion 9's last two
 * stories; 04 §5.3's `ConversationRail/Drawer/*` under RC-12's names).
 *
 * WO-08 built the drawer and left it carrying `ConversationSidebar`; these
 * are the first stories of it with the real rail contents inside, which is
 * what makes them worth having: the one thing the drawer could not prove
 * with a stand-in is that the rail fits. WO-08's handoff note recorded the
 * failure — the legacy sidebar is `w-64 shrink-0`, 256px at every width,
 * wider than the dialog's content box at 320px, which is why the drawer had
 * a `ScrollRegion` around it. `ThreadList` has no fixed width, so the
 * wrapper is gone and the `Open` story at the 320px viewport is the
 * evidence.
 *
 * `open` is a prop, so both states are photographable without an
 * interaction, and neither story touches the network: the drawer takes its
 * contents as `children` and `ThreadList` takes its rows as props.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, screen, within } from "storybook/test";

import { ThreadList, type ThreadSummary } from "@/components/patterns/ThreadList";
import { THREAD_RAIL } from "@/lib/copy/threads";

import ThreadDrawer from "./ThreadDrawer";

const THREADS: ThreadSummary[] = [
  { id: "thread-1", title: "Retrieval-augmented verification" },
  { id: "thread-2", title: "Sparse attention survey" },
];

const meta = {
  title: "ThreadRail/Drawer",
  component: ThreadDrawer,
  args: {
    open: false,
    onOpenChange: () => {},
    children: <ThreadList threads={THREADS} activeConversationId="thread-1" />,
  },
} satisfies Meta<typeof ThreadDrawer>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Closed is not "hidden": Radix renders no portal at all, so the drawer's
 * subtree — and the second copy of the rail it would hold — does not exist.
 */
export const Closed: Story = {
  play: async () => {
    await expect(screen.queryByRole("dialog")).toBeNull();
  },
};

export const Open: Story = {
  args: { open: true },
  parameters: { viewport: { defaultViewport: "w320" } },
  play: async () => {
    const dialog = await screen.findByRole("dialog", { name: THREAD_RAIL.heading });
    // The rail is inside the dialog, and the dialog is the only scroller:
    // no second `region` focus stop wrapping it (see ThreadDrawer.tsx).
    await expect(
      within(dialog).getByRole("link", { name: /Retrieval-augmented/ }),
    ).toBeVisible();
    await expect(within(dialog).queryByRole("region")).toBeNull();
  },
};
