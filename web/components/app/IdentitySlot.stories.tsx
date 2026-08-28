/**
 * Shell/IdentitySlot — criterion 11's `IdentitySlot/Empty`, which asserts
 * that the component renders nothing at all.
 *
 * A story for a component that draws nothing looks like a joke until you
 * read D-009. The slot is the one place in the product where somebody will
 * eventually be tempted to put a greyed-out avatar or a "Sign in" that does
 * nothing — 03-DESIGN-BRIEF.md §6: "A disabled login button is still a fake
 * login." This story is the tripwire: it fails the moment the slot renders
 * a single element, in the same `npm run test` run as everything else.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect } from "storybook/test";

import { IdentitySlot } from "./IdentitySlot";

const meta = {
  title: "Shell/IdentitySlot",
  component: IdentitySlot,
} satisfies Meta<typeof IdentitySlot>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Nothing. Not an avatar, not a placeholder, not a zero-height box with a
 * border — the slot contributes no element and no text.
 */
export const Empty: Story = {
  render: () => (
    <div data-identity-slot-probe="">
      <IdentitySlot />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const probe = canvasElement.querySelector("[data-identity-slot-probe]");
    await expect(probe).toBeTruthy();
    await expect(probe?.childElementCount).toBe(0);
    await expect(probe?.textContent).toBe("");
  },
};
