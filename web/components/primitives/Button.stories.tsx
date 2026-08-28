/**
 * Primitives/Button.
 *
 * Every state below is reached by passing props — no MSW, no network, no
 * context (criterion 2). `AllStates` puts the whole matrix on one canvas so
 * the per-story axe run sees all of it at once, and the three pinned stories
 * underneath re-run that same matrix in dark, in forced colours and with
 * reduced motion (criterion 8). The viewport toolbar's five RC-14 widths
 * apply to every story with no wiring here.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import { Button } from "./Button";

const meta = {
  title: "Primitives/Button",
  component: Button,
  args: { children: "Review plan" },
} satisfies Meta<typeof Button>;

export default meta;
type Story = StoryObj<typeof meta>;

function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-ui-xs font-semibold uppercase text-ink-muted">{heading}</h2>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </section>
  );
}

function Close() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <path d="M4 4 12 12M12 4 4 12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export const Primary: Story = { args: { variant: "primary" } };
export const Secondary: Story = { args: { variant: "secondary" } };
export const Ghost: Story = { args: { variant: "ghost" } };
export const Critical: Story = { args: { variant: "critical", children: "Delete thread" } };
export const Disabled: Story = { args: { variant: "primary", disabled: true } };
/** `aria-busy` + `aria-disabled`, and still focusable — see the component header. */
export const Busy: Story = { args: { variant: "primary", busy: true, children: "Submitting" } };
export const FullWidth: Story = { args: { variant: "primary", fullWidth: true } };
export const IconOnly: Story = {
  args: { iconOnly: true, "aria-label": "Close", children: <Close /> },
};

const AllStatesRender = () => (
  <div className="flex flex-col gap-6 p-6">
    <Section heading="Variants">
      <Button variant="primary">Review plan</Button>
      <Button variant="secondary">Cancel</Button>
      <Button variant="ghost">Diagnostics</Button>
      <Button variant="critical">Delete thread</Button>
    </Section>

    <Section heading="Sizes — 32 / 40 / 44px, and 44px for all three under a coarse pointer">
      <Button size="sm">Small</Button>
      <Button size="md">Medium</Button>
      <Button size="lg">Large</Button>
    </Section>

    <Section heading="Unavailable — disabled leaves the tab order, busy does not">
      <Button variant="primary" disabled>
        Disabled
      </Button>
      <Button variant="primary" busy>
        Submitting
      </Button>
    </Section>

    <Section heading="Icon only — an accessible name is required, not optional">
      <Button iconOnly aria-label="Close">
        <Close />
      </Button>
      <Button iconOnly variant="primary" aria-label="Dismiss diagnostics">
        <Close />
      </Button>
    </Section>

    <Section heading="Full width">
      <Button variant="primary" fullWidth>
        Ask a new question
      </Button>
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
