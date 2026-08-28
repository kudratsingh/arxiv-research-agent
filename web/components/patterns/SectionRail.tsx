/**
 * SectionRail — the briefing's own headings, as navigation (WO-18 c4).
 *
 * IT HAS NO LIST OF ITS OWN AND CANNOT BE GIVEN ONE. Every entry arrives in
 * `headings`, and `ReportReader` builds that array by reading the `h2` and
 * `h3` elements the Markdown actually rendered — never from a vocabulary of
 * expected sections. 03 §4.7 states why in one sentence: the rail is
 * "truthful because those headings genuinely exist in the Markdown". A
 * fixed list would be the reading surface's version of an invented stage
 * (H1/H11) — a structure the product asserts about content it did not
 * inspect.
 *
 * THE ABSENT STATE IS `null`, NOT AN EMPTY SHELL. A report with no headings
 * is common — the synthesizer emits short briefings — and a titled,
 * bordered navigation box with nothing in it tells the reader the page is
 * broken. Criterion 4 asks for a test that a heading-free report leaves the
 * rail *absent*, and the only implementation that can pass it is an early
 * return before any chrome is emitted.
 *
 * `activeId` is a prop rather than an observer. Scroll-spy needs
 * `IntersectionObserver`, which is a data-flow decision for whoever owns
 * the scroll container — WO-20's route composition — and a pattern that
 * grew one would stop being reachable by props alone (04 §5.1), which is
 * what keeps its stories free of MSW and its states enumerable.
 *
 * NO STRING IS WRITTEN HERE. `label` comes from `lib/copy/report`, and
 * every link's text is the report's own heading, passed through verbatim
 * for the same reason a checkpoint's node name is (H11): it is the
 * document's word, not ours.
 *
 * No hooks and no state: a server component.
 */

// The rail's own rules live in the WO-18 fence at the foot of
// app/tokens.css, beside the report-surface rules they share tokens with
// (06-WORK-ORDERS.md §5.4). primitives.css is imported for `ew-focusable`
// alone: the rail's links are the only focusable thing it renders, and the
// focus policy has exactly one definition (WO-07).
import "@/components/primitives/primitives.css";
import { cx } from "@/components/primitives/styles";

/** One heading the report rendered. `level` is the tag, not a nesting depth. */
export interface ReportHeading {
  /** The `id` on the rendered heading, and the anchor's fragment. */
  id: string;
  /** The heading's own text, verbatim. */
  text: string;
  /** 2 for `h2`, 3 for `h3`. Nothing else reaches the rail. */
  level: 2 | 3;
}

export interface SectionRailProps {
  /** Derived from rendered nodes. Empty means the rail does not render. */
  headings: readonly ReportHeading[];
  /** The `nav`'s accessible name. From `lib/copy/report`. */
  label: string;
  /** The heading currently being read, if the composer tracks one. */
  activeId?: string | null;
  id?: string;
  className?: string;
}

export function SectionRail({
  headings,
  label,
  activeId = null,
  id,
  className,
}: SectionRailProps) {
  // Criterion 4: absent, not empty-shelled.
  if (headings.length === 0) return null;

  return (
    <nav
      id={id}
      aria-label={label}
      data-heading-count={headings.length}
      className={cx("ew-section-rail", className)}
    >
      <ol className="ew-section-rail__list">
        {headings.map((heading) => (
          <li
            key={heading.id}
            data-level={heading.level}
            className="ew-section-rail__item"
          >
            <a
              href={`#${heading.id}`}
              // `location` rather than `true`: the link is not a "current
              // page", it is the reader's position inside one (APG).
              aria-current={activeId === heading.id ? "location" : undefined}
              className="ew-section-rail__link ew-focusable"
            >
              {heading.text}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
