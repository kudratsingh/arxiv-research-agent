/**
 * StatusBanner — one component, five severities (03 §4.9, WO-12 c4).
 *
 * IT CARRIES NO STRINGS OF ITS OWN. Every word it renders arrives as a
 * prop from `web/lib/copy/` — criterion 1's single edit site — and the
 * `copy/no-inline-text` ESLint rule in `web/eslint.config.mjs` makes that
 * structural for this whole directory rather than a habit of this file.
 * The only literals below are class names and the two ARIA values the
 * live-region rule is written in terms of.
 *
 * THE LIVE-REGION RULE IS THE PART TO READ TWICE (03 §7.3). There are
 * exactly TWO live regions product-wide: one `role="status"` (the trace
 * spine's status line) and one `role="alert"` (user-triggered failures —
 * submission, review, delete, export). So:
 *
 *   - `userTriggered` renders `role="alert"`, and nothing else does.
 *   - This component NEVER renders `role="status"`. That region belongs to
 *     the spine (WO-15); a second one would announce twice and neither
 *     would be the authority. A banner that is not a user-triggered
 *     failure is ordinary content, which is what a reader arriving late
 *     wants anyway.
 *   - `role="alert"` additionally requires a failure severity. An
 *     announcement that interrupts a screen-reader user has to be worth
 *     the interruption; "the plan was saved" is not, and the constructor
 *     throws rather than letting that ship.
 *
 * SEVERITY IS NEVER COLOUR ALONE (03 §3.4, RC-17). The five severities map
 * onto four roles — the palette ships no `warning` hue, so `warning` and
 * `review` share one — which means the hue cannot be the discriminator.
 * The word is (`SEVERITY_WORD`), and after it the mark (`SEVERITY_MARK`).
 * Both come through `StatusBadge`, so a banner cannot be rendered wordless
 * and a forced-colours user loses nothing but decoration.
 *
 * No hooks and no state: a server component, so a surface pays nothing in
 * route JavaScript for a failure it is not showing (04 §8.1).
 */

import type { ReactNode } from "react";

import { SEVERITY_MARK, StatusBadge } from "@/components/primitives/StatusBadge";
import type { StatusMarkShape } from "@/components/primitives/marks";
import { SEVERITY_WORD, type RawEvidenceRow } from "@/lib/copy/errors";
import { STATUS_SEVERITY_ROLE, type StatusSeverity } from "@/lib/tokens";

/** The two severities a `role="alert"` announcement is allowed to carry. */
export const ALERT_SEVERITIES: readonly StatusSeverity[] = ["warning", "critical"];

/** Role → the banner's surface and border classes. */
const ROLE_SURFACE: Record<
  (typeof STATUS_SEVERITY_ROLE)[StatusSeverity],
  string
> = {
  primary: "border-border-subtle bg-sunken",
  review: "border-review bg-review-surface",
  signature: "border-signature bg-surface",
  critical: "border-critical bg-critical-surface",
};

export interface StatusBannerProps {
  severity: StatusSeverity;
  /**
   * The primary sentence. Always ours, never raw backend text (RC-16).
   * A mapped `error_type` sentence goes here; the raw string goes in
   * `evidence`.
   */
  sentence: string;
  /**
   * The status word. Defaults to the severity's own word so a banner is
   * never wordless; surfaces override it with something specific.
   */
  word?: string;
  /** What the user can do next. Never an automatic retry (H6). */
  recovery?: ReactNode;
  /**
   * Raw, labelled backend strings rendered UNDER the sentence — the
   * visible half of RC-16 and of criterion 6's fall-through. Never the
   * primary message, always one glance away from it.
   */
  evidence?: readonly RawEvidenceRow[];
  /** Controls, e.g. "Retry" or "Ask again". */
  actions?: ReactNode;
  /** Override the severity's mark, e.g. the dashed square of an expired run. */
  mark?: StatusMarkShape;
  /**
   * `true` ONLY when this banner reports a failure the user just caused
   * by acting: a submission, a review, a delete, an export (03 §7.3).
   * Anything that merely became true — a poll failing, a stream closing —
   * is ordinary content and must not interrupt.
   */
  userTriggered?: boolean;
  id?: string;
  className?: string;
  /** Extra content below the recovery line, e.g. a diagnostics disclosure. */
  children?: ReactNode;
}

export function StatusBanner({
  severity,
  sentence,
  word,
  recovery,
  evidence,
  actions,
  mark,
  userTriggered = false,
  id,
  className,
  children,
}: StatusBannerProps) {
  if (userTriggered && !ALERT_SEVERITIES.includes(severity)) {
    throw new Error(
      `StatusBanner: role="alert" is reserved for user-triggered failures ` +
        `(03 §7.3), so severity must be one of ${ALERT_SEVERITIES.join(", ")} ` +
        `— received "${severity}". An announcement that interrupts has to be ` +
        `worth the interruption.`,
    );
  }

  const role = STATUS_SEVERITY_ROLE[severity];
  const evidenceRows = evidence ?? [];

  return (
    <div
      id={id}
      // The ONLY live-region attribute this component can emit. There is no
      // branch that produces role="status": that region is the spine's, and
      // 03 §7.3 allows exactly one of it product-wide.
      {...(userTriggered ? { role: "alert" } : {})}
      data-severity={severity}
      data-role={role}
      data-user-triggered={userTriggered ? "true" : "false"}
      className={[
        "flex flex-col gap-2 rounded-md border p-4 text-ui-base text-ink",
        ROLE_SURFACE[role],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <StatusBadge severity={severity} mark={mark ?? SEVERITY_MARK[severity]}>
        {word ?? SEVERITY_WORD[severity]}
      </StatusBadge>

      <p className="text-balance">{sentence}</p>

      {recovery === undefined ? null : (
        <p className="text-ui-sm text-ink-muted">{recovery}</p>
      )}

      {evidenceRows.length === 0 ? null : (
        <dl className="flex flex-col gap-1">
          {evidenceRows.map((row) => (
            <div key={row.label} className="flex flex-wrap gap-2">
              <dt className="font-mono text-mono-sm text-ink-muted">{row.label}</dt>
              <dd
                className="break-words font-mono text-mono-sm text-ink"
                data-present={row.present ? "true" : "false"}
              >
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {actions === undefined ? null : (
        <div className="flex flex-wrap items-center gap-3">{actions}</div>
      )}

      {children}
    </div>
  );
}
