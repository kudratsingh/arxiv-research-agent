import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { LEARN } from "@/lib/copy/learn";

import { LearnLandingEntry } from "./LearnLandingEntry";

const meta = {
  title: "Landing",
  component: LearnLandingEntry,
  parameters: { layout: "centered" },
} satisfies Meta<typeof LearnLandingEntry>;

export default meta;
type Story = StoryObj<typeof meta>;

export const LearnEntry: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEARN.landingHeading })
    ).toBeVisible();
    await expect(
      canvas.getByRole("link", { name: LEARN.landingAction })
    ).toHaveAttribute("href", "/learn");
  },
};
