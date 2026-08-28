/**
 * Primitives/Menu — the thread-row overflow menu of RC-09.
 *
 * `Open` and `Closed` are both props (`defaultOpen`), so the open surface is
 * photographable without an interaction (criterion 2). The roving focus that
 * distinguishes this from the `ExportDropdown.tsx:69` defect is behaviour
 * rather than appearance and is asserted in
 * web/tests/primitives/Menu.test.tsx.
 *
 * `InlineSurface` is the one story that turns the portal off, for a caller
 * whose surface is not clipped and would rather keep the menu in the same
 * DOM subtree; every other story uses the shipped default, which portals.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Button } from "./Button";
import { Menu, MenuItem, MenuSeparator } from "./Menu";

function Overflow() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <circle cx="8" cy="3" r="1.4" fill="currentColor" />
      <circle cx="8" cy="8" r="1.4" fill="currentColor" />
      <circle cx="8" cy="13" r="1.4" fill="currentColor" />
    </svg>
  );
}

const TRIGGER = (
  <Button iconOnly aria-label="Thread actions">
    <Overflow />
  </Button>
);

const meta = {
  title: "Primitives/Menu",
  component: Menu,
  args: {
    trigger: TRIGGER,
    children: (
      <>
        <MenuItem>Rename</MenuItem>
        <MenuItem>Duplicate</MenuItem>
        <MenuSeparator />
        <MenuItem tone="critical">Delete</MenuItem>
      </>
    ),
  },
} satisfies Meta<typeof Menu>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Named by its trigger, which is the APG pattern. */
export const Closed: Story = {};

export const Open: Story = { args: { defaultOpen: true } };

export const WithDisabledItem: Story = {
  args: {
    defaultOpen: true,
    children: (
      <>
        <MenuItem>Rename</MenuItem>
        <MenuItem disabled>Duplicate</MenuItem>
        <MenuSeparator />
        <MenuItem tone="critical">Delete</MenuItem>
      </>
    ),
  },
};

/** An explicit name, which has to clear Radix's `aria-labelledby` to apply. */
export const NamedMenu: Story = {
  args: { defaultOpen: true, label: "Thread actions for “Sparse attention”" },
};

export const AlignedStart: Story = { args: { defaultOpen: true, align: "start" } };

/** Same menu, rendered in place rather than into `document.body`. */
export const InlineSurface: Story = { args: { defaultOpen: true, portal: false } };

export const Dark: Story = { args: { defaultOpen: true }, globals: { theme: "dark" } };
export const ForcedColours: Story = {
  args: { defaultOpen: true },
  globals: { theme: "forced-colors" },
};
export const ReducedMotion: Story = {
  args: { defaultOpen: true },
  globals: { motion: "reduce" },
};
