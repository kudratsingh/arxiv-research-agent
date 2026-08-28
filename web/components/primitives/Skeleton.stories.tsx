/**
 * Primitives/Skeleton.
 *
 * There is nothing to watch. 03 §3.7 forbids skeleton shimmer by name, so
 * the `ReducedMotion` story below is byte-identical to `AllStates` — which
 * is the point rather than an omission: a placeholder that carries no motion
 * cannot lose information when motion is removed (criterion 9).
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import { Skeleton } from "./Skeleton";

const meta = {
  title: "Primitives/Skeleton",
  component: Skeleton,
} satisfies Meta<typeof Skeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className="flex max-w-measure flex-col gap-3">
      <h2 className="text-ui-xs font-semibold uppercase text-ink-muted">{heading}</h2>
      {children}
    </section>
  );
}

export const OneLine: Story = {};
export const Paragraph: Story = { args: { lines: 4 } };
export const Titled: Story = { args: { lines: 1, height: "var(--text-ui-xl-line)" } };
export const Narrow: Story = { args: { lines: 3, width: "60%" } };
export const Labelled: Story = { args: { lines: 3, label: "Loading the thread list" } };

const AllStatesRender = () => (
  <div className="flex flex-col gap-6 p-6">
    <Section heading="One line">
      <Skeleton />
    </Section>

    <Section heading="A paragraph — the last bar is short, the way a paragraph ends">
      <Skeleton lines={4} />
    </Section>

    <Section heading="A heading-sized bar">
      <Skeleton height="var(--text-ui-xl-line)" width="40%" />
    </Section>

    <Section heading="With a clipped name for a region that has no other one">
      <Skeleton lines={3} label="Loading the thread list" />
    </Section>

    <Section heading="A thread row, as the rail will use it">
      <div className="flex flex-col gap-4 rounded-md border border-border-subtle bg-surface p-4">
        <Skeleton height="var(--text-ui-sm-line)" width="70%" />
        <Skeleton height="var(--text-ui-xs-line)" width="45%" />
      </div>
    </Section>
  </div>
);

export const AllStates: Story = { render: AllStatesRender };
export const Dark: Story = { render: AllStatesRender, globals: { theme: "dark" } };
export const ForcedColours: Story = {
  render: AllStatesRender,
  globals: { theme: "forced-colors" },
};
export const ReducedMotion: Story = {
  render: AllStatesRender,
  globals: { motion: "reduce" },
};
