/**
 * Primitives/Dialog.
 *
 * WHY THE OPEN STORIES RENDER NO TRIGGER. A modal dialog puts
 * `aria-hidden="true"` on everything outside itself — that is what "modal"
 * means to the accessibility tree. axe forgives a focusable element inside
 * an aria-hidden subtree only when it can find the open modal
 * (`focusable-modal-open`), and in jsdom, where nothing has a box, that
 * detection is unreliable. Rather than paper over it with a rule exclusion,
 * the open stories simply have nothing focusable behind the dialog, which is
 * both honest and closer to what the user is actually looking at. `Closed`
 * is the story that shows the trigger.
 *
 * Focus trapping and focus restoration are not asserted here — a story is a
 * picture. They are asserted in web/tests/primitives/Dialog.test.tsx, which
 * is where criterion 5's evidence lives.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Button } from "./Button";
import { Dialog, DialogClose } from "./Dialog";

const meta = {
  title: "Primitives/Dialog",
  component: Dialog,
  args: { title: "Delete this thread?" },
} satisfies Meta<typeof Dialog>;

export default meta;
type Story = StoryObj<typeof meta>;

const CONFIRM_FOOTER = (
  <>
    <DialogClose asChild>
      <Button variant="secondary">Keep thread</Button>
    </DialogClose>
    <DialogClose asChild>
      <Button variant="critical">Delete thread</Button>
    </DialogClose>
  </>
);

/** The only story with a trigger: closed, so nothing is aria-hidden. */
export const Closed: Story = {
  args: {
    trigger: <Button variant="critical">Delete thread</Button>,
    description:
      "The thread, its jobs and its reports are removed. This cannot be undone.",
    footer: CONFIRM_FOOTER,
  },
};

export const Open: Story = {
  args: {
    defaultOpen: true,
    description:
      "The thread, its jobs and its reports are removed. This cannot be undone.",
    footer: CONFIRM_FOOTER,
  },
};

/** `tone="critical"` tints the title; the words still carry the meaning. */
export const CriticalTone: Story = {
  args: {
    defaultOpen: true,
    tone: "critical",
    description:
      "The thread, its jobs and its reports are removed. This cannot be undone.",
    footer: CONFIRM_FOOTER,
  },
};

/** No description: Radix's `aria-describedby` is cleared rather than dangling. */
export const TitleOnly: Story = {
  args: {
    defaultOpen: true,
    title: "Export unavailable",
    children: "There is no report to export yet. Run the query first.",
  },
};

export const Dark: Story = {
  args: { ...Open.args },
  globals: { theme: "dark" },
};
export const ForcedColours: Story = {
  args: { ...Open.args },
  globals: { theme: "forced-colors" },
};
/** The `ew-enter` fade is removed outright; the dialog is simply there. */
export const ReducedMotion: Story = {
  args: { ...Open.args },
  globals: { motion: "reduce" },
};
