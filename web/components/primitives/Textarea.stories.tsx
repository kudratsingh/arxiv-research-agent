/**
 * Primitives/Textarea.
 *
 * `NearLimit` and `OverLimit` are 03 §2.2 composer states, and both are
 * reached by passing a `value` and a `limit` — nothing is typed, nothing is
 * submitted, nothing is fetched (criterion 2). `OverLimit` exists at all
 * because the component refuses to truncate: see the component header.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import { Textarea } from "./Textarea";

const LIMIT = 60;
const NEAR = "How do sparse attention kernels change long-context scaling?";
const OVER = `${NEAR} And what does that cost at inference time on commodity accelerators?`;

const meta = {
  title: "Primitives/Textarea",
  component: Textarea,
  args: { label: "Research question", placeholder: "Ask a question about ML/AI papers" },
} satisfies Meta<typeof Textarea>;

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

export const Empty: Story = {};
export const Filled: Story = { args: { defaultValue: NEAR } };
export const WithHint: Story = {
  args: { hint: "One question at a time gets the better plan." },
};
export const NearLimit: Story = { args: { value: NEAR, limit: LIMIT, readOnly: true } };
export const OverLimit: Story = { args: { value: OVER, limit: LIMIT, readOnly: true } };
export const Invalid: Story = {
  args: { value: "", readOnly: true, error: "Enter a question before submitting." },
};
export const Disabled: Story = { args: { disabled: true, defaultValue: NEAR } };

const AllStatesRender = () => (
  <div className="flex flex-col gap-6 p-6">
    <Section heading="Empty, with a hint">
      <Textarea
        label="Research question"
        placeholder="Ask a question about ML/AI papers"
        hint="One question at a time gets the better plan."
      />
    </Section>

    <Section heading="Within budget">
      <Textarea label="Research question" value={NEAR.slice(0, 30)} limit={LIMIT} readOnly />
    </Section>

    <Section heading="Near the limit — the counter warns before it refuses">
      <Textarea label="Research question" value={NEAR} limit={LIMIT} readOnly />
    </Section>

    <Section heading="Over the limit — stated, not truncated">
      <Textarea label="Research question" value={OVER} limit={LIMIT} readOnly />
    </Section>

    <Section heading="Invalid">
      <Textarea
        label="Research question"
        value=""
        readOnly
        error="Enter a question before submitting."
      />
    </Section>

    <Section heading="Disabled">
      <Textarea label="Research question" disabled defaultValue={NEAR} />
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
