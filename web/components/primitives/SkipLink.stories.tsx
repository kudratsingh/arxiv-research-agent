/**
 * Primitives/SkipLink.
 *
 * Press Tab with the canvas focused and the link appears at the top-left;
 * press it and focus moves to the target. That is the whole component, and
 * it is the first stop in the tab order 03 §7.2 specifies.
 *
 * `Focused` calls `.focus()` from a play function so the story is not blank
 * in a screenshot. Note the honest caveat: the reveal is `:focus-visible`,
 * and a browser grants that on a keyboard-initiated focus rather than on a
 * scripted one — so the story proves the link takes focus, and a Tab is what
 * actually shows the box. web/tests/primitives/SkipLink.test.tsx asserts the
 * href, the clip class and the tab position.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect } from "storybook/test";

import { SkipLink } from "./SkipLink";

const meta = {
  title: "Primitives/SkipLink",
  component: SkipLink,
} satisfies Meta<typeof SkipLink>;

export default meta;
type Story = StoryObj<typeof meta>;

function Page({ targetId = "main", label }: { targetId?: string; label?: string }) {
  return (
    <div className="flex flex-col gap-4 p-6">
      <SkipLink targetId={targetId}>{label}</SkipLink>
      <header className="rounded-md border border-border-subtle bg-surface p-4 text-ui-sm text-ink">
        Header — the skip link comes before this in the tab order.
      </header>
      <main id={targetId} className="rounded-md border border-border-subtle bg-surface p-4">
        <h2 className="text-ui-lg font-semibold text-ink">Main</h2>
        <p className="text-ui-sm text-ink-muted">
          The link points here. In the product this is WO-08&rsquo;s single
          <code className="font-mono"> &lt;main id=&quot;main&quot;&gt;</code>.
        </p>
      </main>
    </div>
  );
}

/** Clipped, which is what it looks like almost all of the time. */
export const Default: Story = { render: () => <Page /> };

export const Focused: Story = {
  render: () => <Page />,
  play: async ({ canvasElement }) => {
    const link = canvasElement.querySelector("a");
    link?.focus();
    await expect(link).toHaveFocus();
  },
};

/**
 * A route whose main region is named something else. The target really
 * exists in the story, because axe's `skip-link` rule checks that it does.
 */
export const CustomTarget: Story = {
  render: () => <Page targetId="report" label="Skip to the report" />,
};

export const Dark: Story = { render: () => <Page />, globals: { theme: "dark" } };
export const ForcedColours: Story = {
  render: () => <Page />,
  globals: { theme: "forced-colors" },
};
export const ReducedMotion: Story = {
  render: () => <Page />,
  globals: { motion: "reduce" },
};
