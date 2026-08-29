/**
 * RouteError — what an `error.tsx` boundary renders (03 §4.9, 03 §2.2).
 *
 * WHY IT IS NOT A `StatusBanner`. WO-12's banner is the right component for
 * a failure that happens *beside* content the user is still reading — a
 * submission error above a composer, a partial briefing under a failure
 * line. A route error boundary is the opposite case: the content is gone,
 * this is the whole surface, and criterion 2 requires it to carry the
 * page's `h1`. A banner has a `sentence`, not a heading, and giving it one
 * would make every banner in the product a potential heading. So this is a
 * separate, smaller component. Both route boundaries load this module only
 * after an error, keeping `StatusBadge`, the mark vocabulary, this surface,
 * and its copy out of the normal route's first-load union.
 *
 * NOT A LIVE REGION. 03 §7.3 allows exactly two product-wide — one
 * `role="status"` and one `role="alert"` — and both are spoken for. A route
 * error boundary replaces the page; a screen reader lands on it by
 * navigation, and the `h1` is what tells it where it is. There is nothing
 * here to interrupt.
 *
 * THE DIGEST IS EVIDENCE, NEVER THE MESSAGE (RC-16). Next hands the
 * boundary an `error.digest` — a hash the server logged the real stack
 * under — and only when the failure happened on the server. It is rendered
 * labelled, under the sentence, in mono, exactly the way
 * `StatusBanner`'s `evidence` rows render a raw backend string. When there
 * is no digest the row is absent rather than filled: "not reported" is for
 * a value the API was silent about, not for a field that does not exist on
 * this error.
 *
 * `reset` IS A BUTTON, NOT A LINK, AND IT IS THE ONLY ACTION. It re-renders
 * the segment that threw; it is not navigation and it is not a retry of any
 * request. Nothing here re-sends a mutation — H6 and R-01 hold on this
 * surface exactly as they hold everywhere else.
 *
 * WHY IT IS A PLAIN `<button>` AND NOT WO-07's `Button` PRIMITIVE, WHICH IS
 * "the product's only clickable control". Measured, not preferred. A direct
 * import originally put a whole copy of the primitive and
 * `components/primitives/styles.ts` into both small boundary entries; after
 * the boundary moved behind an error-only chunk, it still added 1,014 B gzip
 * to the recovery request for behavior this idempotent control does not use.
 * What the primitive contributes that this surface needs is the focus ring,
 * the hit target and the variant's colours, and those are
 * `ew-focusable`, `ew-target` and `--color-primary*` — declared once in
 * components/primitives/primitives.css and in the token layer, not owned by
 * the component. So the classes are named here and the policy still has one
 * definition. `busy`, `iconOnly` and the `aria-disabled` click guard are
 * the parts that genuinely live in the primitive, and a boundary with one
 * idempotent action needs none of them. `NotFound` renders its anchors the
 * same way, for the same reason.
 *
 * IT CARRIES NO STRINGS OF ITS OWN. Every word arrives as a prop from
 * `web/lib/copy/`, enforced for this directory by the `copy/no-inline-text`
 * ESLint rule.
 */

import "@/components/primitives/primitives.css";

import { RECOVERY, ROUTE_ERROR } from "@/lib/copy/recovery";

/**
 * The primary control, as classes. `ew-focusable` and `ew-target` are
 * WO-07's product-wide focus and target policies, declared once in
 * primitives.css; the colours are the `primary` role from the token layer.
 * Identical in effect to `<Button variant="primary" size="md">` — see the
 * header for why it is not that.
 */
const ACTION_CLASS =
  "ew-focusable ew-target ew-target--md inline-flex items-center justify-center " +
  "rounded-md border border-transparent bg-primary px-4 text-ui-base font-medium " +
  "text-primary-on transition-colors duration-fast ease-standard hover:bg-primary-strong";

export interface RouteErrorProps {
  /** The `h1`. Criterion 2: every recovery surface renders exactly one. */
  heading: string;
  body: string;
  /** The `reset` control's label. */
  actionLabel: string;
  /** Next's `reset()`. Re-renders the segment; sends nothing. */
  onReset: () => void;
  /** `error.digest`, when the runtime produced one. */
  digest?: string;
  /** The digest row's label. */
  digestLabel: string;
  /** What the digest is for. Rendered only when there is a digest. */
  digestRecovery: string;
  className?: string;
}

export function RouteError({
  heading,
  body,
  actionLabel,
  onReset,
  digest,
  digestLabel,
  digestRecovery,
  className,
}: RouteErrorProps) {
  return (
    <div
      data-recovery-surface="route-error"
      className={[
        "mx-auto flex h-full max-w-content flex-col justify-center gap-4 px-6 py-10",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <h1 className="text-ui-xl font-semibold tracking-tight text-ink">{heading}</h1>

      <p className="max-w-measure text-balance text-ui-base text-ink-muted">{body}</p>

      {digest === undefined || digest === "" ? null : (
        <div className="flex flex-col gap-1 rounded-md border border-border-subtle bg-sunken p-3">
          <dl className="flex flex-wrap items-baseline gap-2">
            <dt className="font-mono text-mono-sm text-ink-muted">{digestLabel}</dt>
            <dd className="break-all font-mono text-mono-sm text-ink" data-error-digest="">
              {digest}
            </dd>
          </dl>
          <p className="text-ui-xs text-ink-muted">{digestRecovery}</p>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onReset}
          data-route-error-reset=""
          className={ACTION_CLASS}
        >
          {actionLabel}
        </button>
      </div>
    </div>
  );
}

export interface BoundaryRouteErrorProps {
  kind: "workspace" | "thread";
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * The error-only entry shared by both Next boundaries. Keeping the copy
 * selection here is deliberate: if either boundary imports the dictionary
 * before `lazy()`, webpack places both copy objects back into first-load JS.
 */
export default function BoundaryRouteError({
  kind,
  error,
  reset,
}: BoundaryRouteErrorProps) {
  const thread = kind === "thread";
  return (
    <RouteError
      heading={thread ? RECOVERY.threadErrorHeading : ROUTE_ERROR.errorHeading}
      body={thread ? RECOVERY.threadErrorBody : ROUTE_ERROR.errorBody}
      actionLabel={ROUTE_ERROR.errorAction}
      onReset={reset}
      digest={error.digest}
      digestLabel={RECOVERY.referenceLabel}
      digestRecovery={RECOVERY.referenceRecovery}
    />
  );
}
