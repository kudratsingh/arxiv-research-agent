/**
 * NotFound — the 404 surface, for both of the product's two 404s (03 §4.9).
 *
 * ONE COMPONENT, TWO STATES, BECAUSE THE API MAKES THEM ONE SHAPE.
 * 03 §2.2 lists them separately — row 22 "Route not found" and row 21
 * "Thread not found (inline)" — and they arrive from different places:
 *
 *   row 22  the address matches no route. Next raises it; `app/not-found.tsx`
 *           catches it. Story `Shell/NotFoundFramework`.
 *   row 21  `GET /conversations/{id}` answered 404. The API raises it; the
 *           thread renders this inline. Story `Shell/NotFoundProduct`.
 *
 * What they share is the only thing this component has to get right: a real
 * `h1`, an explanation, and a way out. The baseline had none of the three —
 * `conversation-not-found` is the single state in the Gate 1 axe set that
 * fails `page-has-heading-one` (03 §7.1), and the framework 404 is a
 * two-line `next-error-h1` with no rail, no landmarks and no product
 * navigation.
 *
 * WHY THE ACTIONS ARE HREFS AND NOT HANDLERS. Both ways out of a 404 are
 * navigation, and navigation is an anchor. A `<button onClick={router.push}>`
 * would lose middle-click, open-in-new-tab and the status-bar preview, and
 * it would need this component to be a client component to hold the
 * handler. As anchors it stays a server component, so a route pays nothing
 * in first-load JavaScript for a 404 it is not showing (04 §8.1) — which
 * matters here, because `/` has 4,632 B of headroom against RC-01's
 * ceiling.
 *
 * IT CARRIES NO STRINGS OF ITS OWN. Every word arrives as a prop from
 * `web/lib/copy/`, and the `copy/no-inline-text` ESLint rule makes that
 * structural for this directory rather than a habit of this file.
 *
 * THE FOCUS AND TARGET POLICIES ARE NOT RESTATED HERE. `ew-focusable` and
 * `ew-target` are WO-07's product-wide rules, declared once in
 * components/primitives/primitives.css; a pattern that renders its own
 * interactive element adopts them by class rather than by copying the
 * 2px/2px ring and the 44px coarse-pointer floor into a second place.
 */

import Link from "next/link";

import "@/components/primitives/primitives.css";

export interface NotFoundProps {
  /** The `h1`. Criterion 2: every recovery surface renders exactly one. */
  heading: string;
  /**
   * Why the address or the thread is not there. For row 21 this is the H8
   * sentence: missing OR another principal's, never "deleted" and never
   * "no permission", because `_check_ownership` (`src/api/routes.py:59`)
   * answers 404 for both and the client cannot tell which.
   */
  body: string;
  /** The primary way out. Row 22's is "Start a new question" (criterion 1). */
  actionLabel: string;
  actionHref: string;
  /**
   * The second way out (03 §2.2 row 21: "two routes out"). Omitted for the
   * route 404, whose single primary action is what criterion 1 names.
   */
  secondaryLabel?: string;
  secondaryHref?: string;
  className?: string;
}

/** Shared by both anchors: the focus ring, the hit target, the type step. */
const ACTION_CLASS =
  "ew-focusable ew-target ew-target--md inline-flex items-center justify-center " +
  "rounded-md border px-4 text-ui-base font-medium no-underline";

const PRIMARY_CLASS =
  "border-transparent bg-primary text-primary-on hover:bg-primary-strong";

const SECONDARY_CLASS = "border-border-strong bg-surface text-ink hover:bg-sunken";

export function NotFound({
  heading,
  body,
  actionLabel,
  actionHref,
  secondaryLabel,
  secondaryHref,
  className,
}: NotFoundProps) {
  return (
    <div
      data-recovery-surface="not-found"
      className={[
        "mx-auto flex h-full max-w-content flex-col justify-center gap-4 px-6 py-10",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <h1 className="text-ui-xl font-semibold tracking-tight text-ink">{heading}</h1>

      <p className="max-w-measure text-balance text-ui-base text-ink-muted">{body}</p>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Link href={actionHref} className={`${ACTION_CLASS} ${PRIMARY_CLASS}`}>
          {actionLabel}
        </Link>

        {secondaryLabel !== undefined && secondaryHref !== undefined ? (
          <Link href={secondaryHref} className={`${ACTION_CLASS} ${SECONDARY_CLASS}`}>
            {secondaryLabel}
          </Link>
        ) : null}
      </div>
    </div>
  );
}
