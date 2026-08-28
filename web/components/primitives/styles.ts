/**
 * The library's internal style helpers. Not a primitive: no stories, no
 * rendering, nothing a surface work order imports directly. The eleven
 * primitives are named explicitly in web/tests/primitives/boundary.test.tsx
 * rather than read off the directory, so a helper module like this one does
 * not owe a `.stories.tsx`.
 *
 * `cx` is eight lines instead of a `clsx` dependency, because 04 §8.1's
 * route budgets are tight enough that ~500 bytes of vendor code for a string
 * join is not a trade worth making.
 */

/** Join class names, dropping the falsy ones. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part)).join(" ");
}

/**
 * Control heights, from 03 §3.6: "Control heights 32 / 40 / 44". Every one
 * of them is at or above the 24px SC 2.5.8 floor before the coarse-pointer
 * rule in primitives.css lifts them all to 44px.
 */
export const CONTROL_SIZES = ["sm", "md", "lg"] as const;
export type ControlSize = (typeof CONTROL_SIZES)[number];

/** The focus policy's hook. One rule, in primitives.css. */
export const FOCUSABLE_CLASS = "ew-focusable";

/** The target policy's hook, plus the modifier for a given control height. */
export function targetClass(size: ControlSize): string {
  return `ew-target ew-target--${size}`;
}

/** Horizontal padding and type step per control height. */
export const CONTROL_PADDING: Record<ControlSize, string> = {
  sm: "px-3 text-ui-sm",
  md: "px-4 text-ui-base",
  lg: "px-5 text-ui-base",
};
