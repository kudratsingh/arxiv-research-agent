import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import type { LearnPathDetail } from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";

import { PathUnavailable, PathView } from "./PathView";

const fixturePath = detailFixture.body as LearnPathDetail;

const meta = {
  title: "PathView",
  component: PathView,
  args: { path: fixturePath },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof PathView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FixtureLabeled: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(LEARN.fixtureLabel)).toBeVisible();
    await expect(canvas.getAllByRole("link", { name: LEARN.openPaper })).toHaveLength(3);
  },
};

export const NoProgress: Story = {
  args: { path: { ...fixturePath, fixture: false, banner: null } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(LEARN.noProgress)).toBeVisible();
    await expect(canvas.getAllByText(LEARN.notObserved)).toHaveLength(3);
  },
};

export const WithProgress: Story = {
  args: {
    path: { ...fixturePath, fixture: false, banner: null },
    observations: fixturePath.entries.slice(0, 2).map((entry, index) => ({
      path_id: fixturePath.path_id,
      resource_id: entry.resource_id,
      sessions_completed: 1,
      last_observed_at: `2026-08-2${index + 4}T09:00:00.000000Z`,
      event_ids: [`evt-${index + 1}`],
    })),
  },
  play: async ({ canvasElement }) => {
    const entries = canvasElement.querySelectorAll("[data-path-entry]");
    await expect(entries[0]).toHaveAttribute("data-observation", "observed");
    await expect(entries[1]).toHaveAttribute("data-observation", "observed");
    await expect(entries[2]).toHaveAttribute("data-observation", "not-observed");
  },
};

export const Unavailable: Story = {
  render: () => <PathUnavailable onRetry={() => undefined} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEARN.pathUnavailableHeading })
    ).toBeVisible();
    await expect(canvas.getByRole("button", { name: LEARN.retry })).toBeVisible();
  },
};
