/**
 * Primitives/Disclosure.
 *
 * Open and closed are both reachable from props — `defaultOpen` for the
 * uncontrolled case, `open` for the controlled one — so neither state needs
 * an interaction to photograph (criterion 2).
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import { Disclosure } from "./Disclosure";
import { StatusBadge } from "./StatusBadge";

const meta = {
  title: "Primitives/Disclosure",
  component: Disclosure,
  args: {
    label: "Diagnostics",
    children: "42 frames received. Last checkpoint: verifier_pass at 00:01:14.",
  },
} satisfies Meta<typeof Disclosure>;

export default meta;
type Story = StoryObj<typeof meta>;

function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className="flex max-w-measure flex-col gap-3">
      <h2 className="text-ui-xs font-semibold uppercase text-ink-muted">{heading}</h2>
      <div className="rounded-md border border-border-subtle bg-surface p-2">{children}</div>
    </section>
  );
}

export const Closed: Story = {};
export const Open: Story = { args: { defaultOpen: true } };
export const ControlledOpen: Story = { args: { open: true } };
export const ControlledClosed: Story = { args: { open: false } };
export const WithAside: Story = {
  args: {
    defaultOpen: true,
    aside: <StatusBadge severity="warning">2 gaps</StatusBadge>,
  },
};

const AllStatesRender = () => (
  <div className="flex flex-col gap-6 p-6">
    <Section heading="Closed — aria-expanded=false on a real button">
      <Disclosure label="Diagnostics">
        42 frames received. Last checkpoint: verifier_pass at 00:01:14.
      </Disclosure>
    </Section>

    <Section heading="Open">
      <Disclosure label="Diagnostics" defaultOpen>
        42 frames received. Last checkpoint: verifier_pass at 00:01:14.
      </Disclosure>
    </Section>

    <Section heading="With a status beside the label">
      <Disclosure
        label="Export"
        defaultOpen
        aside={<StatusBadge severity="warning">Partial report</StatusBadge>}
      >
        Markdown, JSON and plain text are all generated from the same partial
        run.
      </Disclosure>
    </Section>

    <Section heading="Control heights">
      <Disclosure label="Small" size="sm">
        Small trigger.
      </Disclosure>
      <Disclosure label="Medium" size="md">
        Medium trigger.
      </Disclosure>
      <Disclosure label="Large" size="lg">
        Large trigger.
      </Disclosure>
    </Section>
  </div>
);

export const AllStates: Story = { render: AllStatesRender };
export const Dark: Story = { render: AllStatesRender, globals: { theme: "dark" } };
export const ForcedColours: Story = {
  render: AllStatesRender,
  globals: { theme: "forced-colors" },
};
/** The chevron's rotation collapses to 1ms; `aria-expanded` never moved. */
export const ReducedMotion: Story = {
  render: AllStatesRender,
  globals: { motion: "reduce" },
};
