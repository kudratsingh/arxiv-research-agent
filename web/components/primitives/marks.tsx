/**
 * The mark shapes of 03 §3.4 — "Each status carries a distinct word, a
 * distinct mark shape and a colour, in that order of precedence."
 *
 * Nine shapes, drawn as inline SVG in `currentColor` and `aria-hidden`,
 * because the word beside them is the accessible carrier. Drawing them
 * rather than typing the Unicode characters the brief names (● ◇ ■ □ ┈)
 * matters for two reasons: the dashed and slashed variants have no
 * character at all, and a glyph is at the mercy of whichever font the
 * platform substitutes, which is exactly the sort of silent degradation
 * the precedence rule exists to survive.
 *
 * Sized off `--size-icon-sm` so a mark and its word stay in proportion when
 * the type scale moves. Internal to the primitives library: StatusBadge is
 * the public way to render one, Field and Textarea use the critical mark
 * for their error rows.
 */

import { size } from "@/lib/tokens";

/** The shapes 03 §3.4 names, plus `triangle` — see RC-17 in StatusBadge. */
export const STATUS_MARKS = [
  "circle",
  "ring",
  "diamond",
  "triangle",
  "square",
  "slashed-square",
  "hollow-square",
  "dashed-square",
  "dashed-rule",
] as const;
export type StatusMarkShape = (typeof STATUS_MARKS)[number];

const STROKE = 1.6;

/** The path content of each shape, in a 16×16 box. */
function shape(mark: StatusMarkShape) {
  switch (mark) {
    case "circle":
      return <circle cx="8" cy="8" r="4.5" fill="currentColor" />;
    case "ring":
      return (
        <>
          <circle cx="8" cy="8" r="3" fill="currentColor" />
          <circle
            cx="8"
            cy="8"
            r="6.2"
            fill="none"
            stroke="currentColor"
            strokeWidth={STROKE}
          />
        </>
      );
    case "diamond":
      return (
        <path
          d="M8 1.6 14.4 8 8 14.4 1.6 8Z"
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
          strokeLinejoin="round"
        />
      );
    case "triangle":
      return (
        <path
          d="M8 1.8 15 14.2H1Z"
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
          strokeLinejoin="round"
        />
      );
    case "square":
      return <rect x="2.5" y="2.5" width="11" height="11" fill="currentColor" />;
    case "slashed-square":
      return (
        <>
          <rect
            x="2.5"
            y="2.5"
            width="11"
            height="11"
            fill="none"
            stroke="currentColor"
            strokeWidth={STROKE}
          />
          <path
            d="M3.6 12.4 12.4 3.6"
            stroke="currentColor"
            strokeWidth={STROKE}
            strokeLinecap="round"
          />
        </>
      );
    case "hollow-square":
      return (
        <rect
          x="2.5"
          y="2.5"
          width="11"
          height="11"
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
        />
      );
    case "dashed-square":
      return (
        <rect
          x="2.5"
          y="2.5"
          width="11"
          height="11"
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
          strokeDasharray="3 2.4"
        />
      );
    case "dashed-rule":
      return (
        <path
          d="M1.5 8h13"
          stroke="currentColor"
          strokeWidth={STROKE}
          strokeDasharray="3 2.4"
          strokeLinecap="round"
        />
      );
  }
}

export interface MarkProps {
  mark: StatusMarkShape;
  className?: string;
}

/**
 * `aria-hidden` and `focusable="false"`: the mark is the redundant channel,
 * never the announced one. A screen reader hears the word.
 */
export function Mark({ mark, className }: MarkProps) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 16 16"
      width={size["icon-sm"]}
      height={size["icon-sm"]}
      className={className}
      data-mark={mark}
      style={{ flex: "none" }}
    >
      {shape(mark)}
    </svg>
  );
}
