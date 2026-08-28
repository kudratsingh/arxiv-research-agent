/**
 * Primitives/VisuallyHidden.
 *
 * A story about something you cannot see is a contradiction, so each panel
 * below shows the rendered result AND the text that is in the accessibility
 * tree but not on the screen. The clipped text really is clipped — inspect
 * the DOM, or run the axe panel and watch the region acquire a name it does
 * not visibly display.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import { VisuallyHidden } from "./VisuallyHidden";

const meta = {
  title: "Primitives/VisuallyHidden",
  component: VisuallyHidden,
  args: { children: "Opens in a new tab" },
} satisfies Meta<typeof VisuallyHidden>;

export default meta;
type Story = StoryObj<typeof meta>;

function Panel({ heading, note, children }: { heading: string; note: string; children: ReactNode }) {
  return (
    <section className="flex max-w-measure flex-col gap-2 rounded-md border border-border-subtle bg-surface p-4">
      <h2 className="text-ui-xs font-semibold uppercase text-ink-muted">{heading}</h2>
      <div className="text-ui-sm text-ink">{children}</div>
      <p className="text-ui-xs text-ink-faint">{note}</p>
    </section>
  );
}

export const Default: Story = {};
export const AsHeading: Story = { args: { as: "h2", children: "Thread list" } };

const AllStatesRender = () => (
  <div className="flex flex-col gap-4 p-6">
    <Panel
      heading="Extending a visible label"
      note="A screen reader reads “Export report, Markdown”; the screen shows “Export report”."
    >
      Export report
      <VisuallyHidden>, Markdown</VisuallyHidden>
    </Panel>

    <Panel
      heading="Naming a region that shows no heading"
      note="The h2 is in the accessibility tree and takes no vertical space."
    >
      <VisuallyHidden as="h2">Thread list</VisuallyHidden>
      <ul className="list-none">
        <li>Sparse attention kernels</li>
        <li>Retrieval-augmented generation</li>
      </ul>
    </Panel>

    <Panel
      heading="Carrying the word when only a mark is drawn"
      note="03 §3.4's precedence, applied to a mark that has no room for its word."
    >
      <span aria-hidden="true">■</span>
      <VisuallyHidden>Complete</VisuallyHidden>
    </Panel>
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
