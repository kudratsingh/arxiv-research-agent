/**
 * Skeleton — a still placeholder.
 *
 * IT DOES NOT SHIMMER. 03 §3.7 forbids "skeleton shimmer" outright, along
 * with typewriter effects and any continuous decorative motion. So this
 * component has no animation at all, which makes criterion 9 trivially true
 * for it: there is no motion, so no information can be carried by motion.
 * What it has instead is a `--color-sunken` block — the same role the
 * product uses for any recessed surface — and a border radius from the
 * token scale.
 *
 * IT IS NOT ANNOUNCED. The bars are `aria-hidden`; a skeleton read aloud is
 * a stutter of nothing. `label` renders a clipped word for the case where
 * the loading region has no other accessible name, and the container that
 * owns the load should carry `aria-busy` — which is the caller's job,
 * because only the caller knows where the boundary is.
 *
 * No hooks: a server component.
 */

import "./primitives.css";
import { cx } from "./styles";
import { VisuallyHidden } from "./VisuallyHidden";

export interface SkeletonProps {
  /** Number of bars. The last one is short, the way a paragraph ends. */
  lines?: number;
  /** Any CSS length; defaults to filling the container. */
  width?: string;
  /** Any CSS length; defaults to the UI line height. */
  height?: string;
  /** A clipped word for a region that has no other name. */
  label?: string;
  className?: string;
}

export function Skeleton({
  lines = 1,
  width,
  height,
  label,
  className,
}: SkeletonProps) {
  const count = Math.max(1, Math.trunc(lines));

  return (
    <div className={cx("flex flex-col gap-2", className)} data-skeleton-lines={count}>
      {label ? <VisuallyHidden>{label}</VisuallyHidden> : null}
      {Array.from({ length: count }, (_, index) => (
        <div
          key={index}
          aria-hidden="true"
          className="ew-skeleton"
          style={{
            width: index === count - 1 && count > 1 ? "60%" : (width ?? "100%"),
            height: height ?? "var(--text-ui-base-line)",
          }}
        />
      ))}
    </div>
  );
}
