import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";
import { ITEMS } from "@/lib/daily/fixtures";
import { DailyShell } from "./DailyShell";
import { Today } from "./Today";
import { Reader } from "./Reader";
import { Library } from "./Library";

const meta = {
  title: "Daily workspace/Connected preview",
  component: Today,
  parameters: {
    nextjs: { appDirectory: true, navigation: { pathname: "/today" } },
  },
} satisfies Meta<typeof Today>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Briefing: Story = {
  render: () => (
    <DailyShell>
      <Today />
    </DailyShell>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("heading", { level: 1 }),
    ).toBeVisible();
  },
};
export const AbstractReader: Story = {
  render: () => (
    <DailyShell>
      <Reader item={ITEMS[0]!} />
    </DailyShell>
  ),
};
export const MetadataReader: Story = {
  render: () => (
    <DailyShell>
      <Reader item={ITEMS[1]!} />
    </DailyShell>
  ),
};
export const SavedLibrary: Story = {
  render: () => (
    <DailyShell>
      <Library />
    </DailyShell>
  ),
};
