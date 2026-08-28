/**
 * Primitives/ScrollRegion — the pan surface of 04 §8.3 item 4.
 *
 * Open this one at the 320 and 412px viewports. The table inside the region
 * pans; the page does not, which is the whole of SC 1.4.10 Reflow and the
 * defect the baseline's mobile screenshots record. The region is a tab stop
 * with a name, so a keyboard user can reach the pan and hears what they have
 * reached.
 *
 * There is no story for the missing-name case, because there cannot be one:
 * the component throws. That case is asserted in
 * web/tests/primitives/ScrollRegion.test.tsx (criterion 6).
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import { ScrollRegion } from "./ScrollRegion";
import { VISUALLY_HIDDEN_CLASS } from "./VisuallyHidden";

const meta = {
  title: "Primitives/ScrollRegion",
  component: ScrollRegion,
  // `Table` is a hoisted function declaration, so it is defined by the time
  // this element is created.
  args: { label: "Retrieval metrics table, scrollable", children: <Table /> },
} satisfies Meta<typeof ScrollRegion>;

export default meta;
type Story = StoryObj<typeof meta>;

const COLUMNS = [
  "Sub-question",
  "Papers found",
  "Papers used",
  "Faithfulness",
  "Coverage",
  "Latency (s)",
  "Tokens in",
  "Tokens out",
];

const ROWS = [
  ["Sparse attention scaling", "18", "6", "0.92", "0.81", "42.1", "18,204", "2,910"],
  ["Kernel fusion on commodity GPUs", "11", "4", "0.88", "0.74", "31.7", "12,880", "2,140"],
  ["Long-context evaluation sets", "23", "7", "0.95", "0.90", "55.4", "24,610", "3,502"],
];

function Table() {
  return (
    <table className="w-max border-collapse text-ui-sm">
      <caption className={VISUALLY_HIDDEN_CLASS}>Retrieval metrics by sub-question</caption>
      <thead>
        <tr>
          {COLUMNS.map((column) => (
            <th
              key={column}
              scope="col"
              className="whitespace-nowrap border border-border-subtle bg-sunken px-3 py-2 text-left font-semibold text-ink"
            >
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {ROWS.map((row) => (
          <tr key={row[0]}>
            {row.map((cell, index) => (
              <td
                key={`${row[0]}-${COLUMNS[index]}`}
                className="whitespace-nowrap border border-border-subtle px-3 py-2 text-ink"
              >
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-ui-xs font-semibold uppercase text-ink-muted">{heading}</h2>
      {children}
    </section>
  );
}

export const WideTable: Story = { args: { children: <Table /> } };

export const NarrowContent: Story = {
  args: {
    label: "Run summary, scrollable",
    children: <p className="text-ui-sm text-ink">Nothing here overflows.</p>,
  },
};

export const BothAxes: Story = {
  args: {
    axis: "both",
    label: "Diagnostics frames, scrollable",
    className: "max-h-40",
    children: <Table />,
  },
};

const AllStatesRender = () => (
  <div className="flex flex-col gap-6 p-6">
    <Section heading="A table wider than the page — the table pans, the page does not">
      <ScrollRegion label="Retrieval metrics table, scrollable">
        <Table />
      </ScrollRegion>
    </Section>

    <Section heading="Content that fits — still a named, focusable region">
      <ScrollRegion label="Run summary, scrollable">
        <p className="text-ui-sm text-ink">Nothing here overflows.</p>
      </ScrollRegion>
    </Section>

    <Section heading="Both axes, for a diagnostics pane taller than its box">
      <ScrollRegion axis="both" label="Diagnostics frames, scrollable" className="max-h-40">
        <Table />
      </ScrollRegion>
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
