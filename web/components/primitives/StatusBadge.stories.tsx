/**
 * Primitives/StatusBadge — the word/mark/colour precedence of 03 §3.4.
 *
 * READ `ForcedColours` FIRST. It is the same matrix as `AllStates` with the
 * hue taken away, which is what the emulation in .storybook/preview.css
 * does: twenty-three roles collapse onto Canvas / CanvasText / GrayText.
 * Every row still says what it is, and every row still carries a shape no
 * other row carries. That is the whole claim of criterion 7, and this story
 * is where a reviewer can see it rather than take it.
 *
 * RC-17 is visible here too: `review` and `warning` share the review hue
 * because the palette ships no `warning` colour, and are told apart by an
 * outlined diamond against an outlined triangle plus their two words.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import { STATUS_MARKS } from "./marks";
import { StatusBadge } from "./StatusBadge";

const meta = {
  title: "Primitives/StatusBadge",
  component: StatusBadge,
  args: { severity: "live", children: "Live" },
} satisfies Meta<typeof StatusBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-ui-xs font-semibold uppercase text-ink-muted">{heading}</h2>
      <div className="flex flex-wrap items-center gap-4">{children}</div>
    </section>
  );
}

export const Info: Story = { args: { severity: "info", children: "Queued" } };
export const Review: Story = {
  args: { severity: "review", children: "Waiting for your review" },
};
export const Live: Story = { args: { severity: "live", children: "Live", ambient: true } };
export const Warning: Story = { args: { severity: "warning", children: "Partial metrics" } };
export const Critical: Story = { args: { severity: "critical", children: "Failed" } };

/**
 * The eight run states 03 §3.4 tabulates, each with its own mark. The
 * severities are the five RC-17 allows: the brief's `signature` colour is
 * reached through the `live` severity, which STATUS_SEVERITY_ROLE maps to it.
 */
const RUN_STATES = [
  { severity: "live" as const, word: "observed", mark: "circle" as const },
  { severity: "live" as const, word: "Live", mark: "ring" as const },
  { severity: "info" as const, word: "not observed", mark: "dashed-rule" as const },
  { severity: "review" as const, word: "Waiting for your review", mark: "diamond" as const },
  { severity: "live" as const, word: "Complete", mark: "square" as const },
  { severity: "critical" as const, word: "Failed", mark: "slashed-square" as const },
  { severity: "info" as const, word: "Cancelled", mark: "hollow-square" as const },
  { severity: "info" as const, word: "No longer available", mark: "dashed-square" as const },
];

const AllStatesRender = () => (
  <div className="flex flex-col gap-6 p-6">
    <Section heading="Five severities, quiet">
      <StatusBadge severity="info">Queued</StatusBadge>
      <StatusBadge severity="review">Waiting for your review</StatusBadge>
      <StatusBadge severity="live" ambient>
        Live
      </StatusBadge>
      <StatusBadge severity="warning">Partial metrics</StatusBadge>
      <StatusBadge severity="critical">Failed</StatusBadge>
    </Section>

    <Section heading="Five severities, on a surface">
      <StatusBadge severity="info" emphasis="surface">
        Queued
      </StatusBadge>
      <StatusBadge severity="review" emphasis="surface">
        Waiting for your review
      </StatusBadge>
      <StatusBadge severity="live" emphasis="surface">
        Live
      </StatusBadge>
      <StatusBadge severity="warning" emphasis="surface">
        Partial metrics
      </StatusBadge>
      <StatusBadge severity="critical" emphasis="surface">
        Failed
      </StatusBadge>
    </Section>

    <Section heading="The run states of 03 §3.4 — eight words, eight shapes">
      {RUN_STATES.map((state) => (
        <StatusBadge key={state.word} severity={state.severity} mark={state.mark}>
          {state.word}
        </StatusBadge>
      ))}
    </Section>

    <Section heading="Every mark in the set">
      {STATUS_MARKS.map((mark) => (
        <StatusBadge key={mark} severity="info" mark={mark}>
          {mark}
        </StatusBadge>
      ))}
    </Section>
  </div>
);

export const AllStates: Story = { render: AllStatesRender };
export const Dark: Story = { render: AllStatesRender, globals: { theme: "dark" } };
/** The evidence for criterion 7: the same matrix with the hue removed. */
export const ForcedColours: Story = {
  render: AllStatesRender,
  globals: { theme: "forced-colors" },
};
/** The ambient pulse stops; the word "Live" does not move. */
export const ReducedMotion: Story = {
  render: AllStatesRender,
  globals: { motion: "reduce" },
};
