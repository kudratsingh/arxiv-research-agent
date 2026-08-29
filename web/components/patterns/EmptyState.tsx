/**
 * EmptyState — an absence that says which absence it is (RC-10, WO-14 c5).
 *
 * THREE DIFFERENT ABSENCES LOOK THE SAME IN THE BASELINE, and that is the
 * defect this exists to stop repeating: `ConversationSidebar.tsx:104-113`
 * renders "Loading…" and "No conversations yet." as two identical 12px grey
 * rows in the same place, and a backend failure renders a third one in the
 * corner. 03-DESIGN-BRIEF.md §2.2 row 3 is explicit that the empty state is
 * "distinct from state 2 and from state 12", so this component is shaped to
 * make that distinction structural: it is never rendered while loading, it
 * carries no `aria-busy`, and it is the only one of the three that can
 * carry an action.
 *
 * IT CARRIES NO STRINGS OF ITS OWN. Every word arrives as a prop from
 * `web/lib/copy/`, which the `copy/no-inline-text` ESLint rule makes
 * structural for this whole directory (WO-12 criterion 1).
 *
 * No hooks and no state: a server component, so a surface pays nothing in
 * route JavaScript for the state where there is nothing to show (04 §8.1).
 */

import type { ReactNode } from "react";

import { cx } from "@/components/primitives/styles";

export interface EmptyStateProps {
  /**
   * The sentence. Required — an empty state with no words is the grey box
   * this component replaces.
   */
  body: string;
  /**
   * An optional heading ABOVE the sentence. Omitted in the rail, where the
   * `Threads` heading is already the chrome and a second one would push the
   * list down for a state that is meant not to move it.
   */
  heading?: string;
  /** The `h2`…`h4` the heading renders as, when there is one. */
  headingLevel?: 2 | 3 | 4;
  /** One control at most: what starts the thing that is missing. */
  action?: ReactNode;
  id?: string;
  className?: string;
}

export function EmptyState({
  body,
  heading,
  headingLevel = 3,
  action,
  id,
  className,
}: EmptyStateProps) {
  const Heading = `h${headingLevel}` as const;

  return (
    <div
      id={id}
      // The hook WO-21 asserts against, and the one a reviewer can grep for
      // to prove state 3 is not state 2 wearing different words.
      data-empty-state=""
      className={cx(
        "flex flex-col items-start gap-2 px-3 py-4 text-ui-sm text-ink-muted",
        className,
      )}
    >
      {heading ? (
        <Heading className="text-ui-base font-medium text-ink">{heading}</Heading>
      ) : null}
      <p>{body}</p>
      {action}
    </div>
  );
}
