/**
 * StatusBadge — word, then mark, then colour (03 §3.4, criterion 7).
 *
 * THE PRECEDENCE IS ENFORCED, NOT DOCUMENTED. The word is `children` and is
 * required: a badge with no word throws rather than rendering a coloured
 * dot that means nothing to a screen reader, to a forced-colours user, or
 * to anyone with a red/green deficiency. The mark is an `aria-hidden` SVG
 * shape, distinct per severity. Colour is third and is the only one of the
 * three that a user agent is allowed to take away.
 *
 * SEVERITY → ROLE COMES FROM web/lib/tokens.ts (RC-17). The palette ships
 * neither `success` nor `warning`, so `warning` and `review` share the
 * `review` hue and are told apart by their word and by an outlined triangle
 * against an outlined diamond. RC-17 forbids a new *hue*; a distinct shape
 * is precisely what it asks for instead.
 *
 * No hooks and no state: a server component, so a surface pays nothing in
 * route JavaScript for a status word (04 §8.1).
 */

import type { ReactNode } from "react";

import { STATUS_SEVERITY_ROLE, type StatusSeverity } from "@/lib/tokens";

import { Mark, type StatusMarkShape } from "./marks";
import "./primitives.css";
import { cx } from "./styles";

/** The role each severity resolves to. */
type StatusRole = (typeof STATUS_SEVERITY_ROLE)[StatusSeverity];

/**
 * Role → colour classes. The `-text` variants carry copy (they are the ones
 * measured against surface in both themes); the base role is for fills and
 * marks. `primary` has no `-text` variant and does not need one.
 */
const ROLE_CLASS: Record<StatusRole, { quiet: string; surface: string }> = {
  primary: {
    quiet: "text-primary",
    surface: "border-border-subtle bg-sunken text-primary",
  },
  review: {
    quiet: "text-review-text",
    surface: "border-review bg-review-surface text-review-text",
  },
  signature: {
    quiet: "text-signature-text",
    surface: "border-signature bg-surface text-signature-text",
  },
  critical: {
    quiet: "text-critical-text",
    surface: "border-critical bg-critical-surface text-critical-text",
  },
};

/**
 * The default shape per severity. Five severities, five distinct shapes —
 * which is the property that has to hold when the hue is gone.
 */
export const SEVERITY_MARK: Record<StatusSeverity, StatusMarkShape> = {
  info: "circle",
  review: "diamond",
  live: "ring",
  warning: "triangle",
  critical: "slashed-square",
};

export interface StatusBadgeProps {
  severity: StatusSeverity;
  /** The word. Required — see the header. */
  children: ReactNode;
  /** Override the default shape, e.g. the `square` of a succeeded run. */
  mark?: StatusMarkShape;
  /** `quiet` is a word and a mark; `surface` adds a bordered chip. */
  emphasis?: "quiet" | "surface";
  /**
   * The ambient receiving indicator (03 §3.7): opacity 1 → 0.55 → 1 on the
   * mark only, and only while an EventSource is open. Ignored unless the
   * severity is `live`, because that is the only state the brief allows it
   * for. Reduced motion stops it; the word "Live" is unaffected.
   */
  ambient?: boolean;
  id?: string;
  className?: string;
}

export function StatusBadge({
  severity,
  children,
  mark,
  emphasis = "quiet",
  ambient = false,
  id,
  className,
}: StatusBadgeProps) {
  if (children === null || children === undefined || children === "") {
    throw new Error(
      "StatusBadge: the word is required. 03 §3.4 puts the word first and " +
        "colour last, so a badge with only a mark and a hue is not a status " +
        "— it is a decoration.",
    );
  }

  const role = STATUS_SEVERITY_ROLE[severity];
  const colour = ROLE_CLASS[role];
  const pulsing = ambient && severity === "live";

  return (
    <span
      id={id}
      data-severity={severity}
      data-role={role}
      className={cx(
        "inline-flex items-center gap-2 whitespace-nowrap text-ui-sm font-medium",
        emphasis === "surface" && "rounded-sm border px-2 py-05",
        emphasis === "surface" ? colour.surface : colour.quiet,
        className,
      )}
    >
      <Mark mark={mark ?? SEVERITY_MARK[severity]} className={cx(pulsing && "ew-pulse")} />
      {children}
    </span>
  );
}
