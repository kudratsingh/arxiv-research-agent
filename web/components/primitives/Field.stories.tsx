/**
 * Primitives/Field.
 *
 * `Invalid` is the 03 §2.2 "validation (422) field mapping" state, reached
 * by passing an `error` string and nothing else — no request, no MSW
 * (criterion 2). Note what it is NOT: a live region. 03 §7.3 allows exactly
 * two product-wide and this is not one of them.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import { Field } from "./Field";

const meta = {
  title: "Primitives/Field",
  component: Field,
  args: { label: "Thread title", placeholder: "Attention mechanisms" },
} satisfies Meta<typeof Field>;

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

export const Default: Story = {};
export const WithHint: Story = {
  args: { hint: "Shown in the thread rail. 80 characters or fewer." },
};
export const Required: Story = { args: { required: true } };
export const Invalid: Story = {
  args: {
    defaultValue: "",
    error: "Enter a title before saving.",
    hint: "Shown in the thread rail.",
  },
};
export const Disabled: Story = { args: { disabled: true, defaultValue: "Retrieval-augmented generation" } };
export const LabelHidden: Story = {
  args: { labelHidden: true, label: "Search threads", type: "search", placeholder: "Search threads" },
};

const AllStatesRender = () => (
  <div className="flex flex-col gap-6 p-6">
    <Section heading="Default">
      <Field label="Thread title" placeholder="Attention mechanisms" />
    </Section>

    <Section heading="With a hint, and required">
      <Field
        label="Thread title"
        required
        hint="Shown in the thread rail. 80 characters or fewer."
      />
    </Section>

    <Section heading="Invalid — mark, then colour, with the word in the message">
      <Field
        label="Thread title"
        error="Enter a title before saving."
        hint="Shown in the thread rail."
      />
    </Section>

    <Section heading="Disabled">
      <Field label="Job id" disabled defaultValue="job_01HX8Z4N2R" />
    </Section>

    <Section heading="Clipped label — the control keeps its name">
      <Field label="Search threads" labelHidden type="search" placeholder="Search threads" />
    </Section>

    <Section heading="Control heights — 32 / 40 / 44px">
      <Field label="Small" size="sm" />
      <Field label="Medium" size="md" />
      <Field label="Large" size="lg" />
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
