/**
 * Patterns/ThemeToggle — WO-08 criterion 11, and the discharge of one of
 * RC-10's four uncovered components.
 *
 * THE STORIES READ THE PRODUCT'S OWN STATE. `ThemeToggle` does not hold the
 * preference in React state: it reads `data-theme-preference` off `<html>`,
 * which is where WO-01's pre-paint script writes it. Storybook's theme
 * decorator writes the SAME attribute (.storybook/decorators/theme.tsx), so
 * `Light` and `Dark` below are not props — they are the real mechanism,
 * driven from the real place. That is also why `System` needs a decorator
 * of its own: the toolbar only offers the two *resolved* themes, and
 * "system" is the third *preference*, which is precisely the distinction
 * `data-theme-preference` exists to carry.
 *
 * WHAT A STORY CANNOT SHOW. That the choice survives a reload, and that no
 * flash occurs on the next load. Those are
 * web/tests/shell/themeToggle.test.tsx (storage and both attributes) and
 * WO-21's Playwright no-flash assertion respectively.
 */

import type { Decorator, Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent } from "storybook/test";

import { THEME_CONTROL } from "@/lib/copy/shell";
import {
  THEME_ATTRIBUTE,
  THEME_PREFERENCE_ATTRIBUTE,
  THEME_STORAGE_KEY,
} from "@/lib/tokens";

import { ThemeToggle } from "./ThemeToggle";

const meta = {
  title: "Patterns/ThemeToggle",
  component: ThemeToggle,
  decorators: [
    (Story) => (
      <div className="flex items-center gap-4 bg-canvas p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ThemeToggle>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * A story-level decorator runs inside the global ones, so it is the last
 * writer of the attribute before the component reads it.
 */
function withPreference(preference: string): Decorator {
  const WithPreference: Decorator = (Story) => {
    document.documentElement.setAttribute(THEME_PREFERENCE_ATTRIBUTE, preference);
    return <Story />;
  };
  return WithPreference;
}

/** An explicit light choice: `data-theme-preference="light"`. */
export const Light: Story = {
  globals: { theme: "light" },
};

/** An explicit dark choice. The control is legible on the dark canvas. */
export const Dark: Story = {
  globals: { theme: "dark" },
};

/**
 * Deferring to the OS. Distinguishable from `Light` only because the
 * product stores the *preference* separately from the resolved theme —
 * which is the reason `THEME_PREFERENCE_ATTRIBUTE` exists.
 */
export const System: Story = {
  decorators: [withPreference("system")],
};

/**
 * Making a choice, which is the one thing a static picture cannot show.
 *
 * The play function is the mechanism end to end: click, and `data-theme`
 * flips on `<html>` — so the canvas behind the control repaints — while the
 * *preference* is written to WO-01's storage key for the next load's
 * pre-paint script to find. web/tests/shell/themeToggle.test.tsx asserts
 * the same contract without a browser.
 */
export const Switching: Story = {
  decorators: [withPreference("light")],
  play: async ({ canvas }) => {
    await userEvent.click(canvas.getByRole("radio", { name: THEME_CONTROL.dark }));

    await expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe("dark");
    await expect(document.documentElement.getAttribute(THEME_PREFERENCE_ATTRIBUTE)).toBe("dark");
    await expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    window.localStorage.removeItem(THEME_STORAGE_KEY);
  },
};

/**
 * The focus ring, on the label rather than on the clipped input.
 *
 * The same honest caveat SkipLink's `Focused` story carries: `:focus-visible`
 * is granted for a keyboard-initiated focus, and a scripted `.focus()` may
 * not qualify. The story proves the input takes focus and that the ring has
 * somewhere to land; a Tab is what paints it.
 */
export const KeyboardFocus: Story = {
  play: async ({ canvasElement }) => {
    const input = canvasElement.querySelector<HTMLInputElement>(
      'input[type="radio"][value="dark"]',
    );
    input?.focus();
    await expect(input).toHaveFocus();
  },
};

export const ForcedColours: Story = {
  globals: { theme: "forced-colors" },
};
