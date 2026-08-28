"use client";

/**
 * ReportReader — the briefing, as a document (WO-18).
 *
 * ONE RENDERER, AND THE FAILURE THAT MADE THAT NECESSARY (c2). Three
 * Markdown code paths exist on `main`: `ReportView.tsx:39-48` for the
 * current run, `ConversationThread.tsx:301-306` for a historical turn, and
 * the collapsed-turn path that renders nothing at all. They already differ —
 * one wraps the body in a bordered card with an export control, the other
 * does not — and nothing prevents them differing further. This component is
 * the single one, and it takes the SAME renderer for both cases, so "current
 * turn" and "history turn" are one prop apart rather than one component
 * apart. `web/tests/patterns/ReportReader.test.tsx` asserts the two produce
 * byte-identical DOM for identical input; `renderer-uniqueness` in the same
 * file asserts nothing outside the legacy files WO-20/WO-31 retire imports
 * `react-markdown` a second time.
 *
 * NO EARLY RETURN ON FAILURE (c1, H5, D-010 ruling 2). `ReportView` returns
 * before the report when `status === "failed" && detail.error`
 * (`ReportView.tsx:13-27`), which throws away a briefing the user has
 * already paid for — the committed `failed-partial` fixture carries $0.1800
 * and 4 LLM calls behind that early return. Here the failure is a banner
 * ABOVE the briefing and the briefing still renders; there is no branch in
 * this file that suppresses a non-empty `markdown`, and a regression test
 * drives the committed fixture to prove it.
 *
 * THE RENDERER IS A PROP, NOT A HOOK (04 §5.1). Patterns take plain props
 * and never call a hook that fetches, which is what makes every state
 * reachable from Storybook without MSW. `renderer={null}` is the loading
 * state — the Markdown pipeline is a dynamic `import()`
 * (`loadReportRenderer`, `lib/report/renderer.ts`) and a route that has not
 * resolved it yet has nothing to render. WO-20 wires WO-11's
 * `useReportRenderer(expanded)` in; nothing about that boundary is
 * reimplemented here.
 *
 * THE SECTION LIST IS READ OFF THE RENDERED DOM (c4). `readHeadings` walks
 * the `h2`/`h3` elements the Markdown actually produced, after commit. That
 * is not a stylistic choice: a rail built from a parse of the source, or
 * worse from an expected section vocabulary, would be a claim about
 * structure this component did not observe — the reading surface's version
 * of H11. A briefing with no headings yields an empty array and
 * `SectionRail` returns `null`.
 *
 * NO STRING IS WRITTEN IN THIS FILE. `copy/no-inline-text` covers
 * `components/patterns/`; every sentence arrives from `lib/copy/report` or
 * `lib/copy/errors`, and the report's own words — headings, paragraphs,
 * table cells — are the document's, passed through unedited.
 */

import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ScrollRegion } from "@/components/primitives/ScrollRegion";
import { Skeleton } from "@/components/primitives/Skeleton";
import { cx } from "@/components/primitives/styles";
import { describeErrorType, rawErrorEvidence } from "@/lib/copy/errors";
import { REPORT, codeRegionLabel, tableRegionLabel } from "@/lib/copy/report";
import type { BriefingFailure } from "@/lib/report/briefings";
import type { ReportRenderer } from "@/lib/report/renderer";

import { SectionRail, type ReportHeading } from "./SectionRail";
import { StatusBanner } from "./StatusBanner";

// ---------------------------------------------------------------------------
// Headings, derived from what was rendered.
// ---------------------------------------------------------------------------

/**
 * A heading's text as a URL fragment.
 *
 * Latin-only on purpose, and honest about it: a heading with no `[a-z0-9]`
 * at all — a CJK section title, a line of maths — collapses to `section`,
 * and `readHeadings` then numbers the collisions. An invented
 * transliteration would be a worse answer than a numbered fallback.
 */
export function headingSlug(text: string): string {
  const slug = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug === "" ? "section" : slug;
}

/**
 * Every `h2`/`h3` the briefing rendered, in document order, with a unique
 * `id` assigned to each.
 *
 * The `id` is written onto the element here rather than through a
 * `components` override because the override cannot see its siblings, and
 * uniqueness is a property of the set: two sections both called "Limits"
 * need two fragments. Assigning it after commit is idempotent — the same
 * input produces the same ids — so React StrictMode's double-invoked effect
 * changes nothing, and React never removes an attribute it did not set.
 *
 * Exported so a test can drive it against a DOM it built by hand, without
 * going through the Markdown pipeline.
 */
export function readHeadings(root: ParentNode): ReportHeading[] {
  const used = new Map<string, number>();
  const found: ReportHeading[] = [];

  for (const element of Array.from(root.querySelectorAll("h2, h3"))) {
    const text = (element.textContent ?? "").trim();
    // A heading with no text is not a section anyone can navigate to.
    if (text === "") continue;

    const base = headingSlug(text);
    const seen = (used.get(base) ?? 0) + 1;
    used.set(base, seen);
    const id = seen === 1 ? base : `${base}-${seen}`;
    if (element.id !== id) element.id = id;

    found.push({ id, text, level: element.tagName === "H2" ? 2 : 3 });
  }

  return found;
}

/**
 * A heading list as one comparable string, so the effect can stop.
 *
 * The effect below runs on every commit that changes the body or the
 * renderer and always produces a NEW array; without an equality check that
 * array would be a new state value every time and the component would
 * re-render for ever. Comparing a flattened key rather than walking the two
 * arrays keeps that check to one expression with no index arithmetic.
 *
 * Exported for the test that pins the loop closed.
 */
export function headingKey(headings: readonly ReportHeading[]): string {
  return headings.map((heading) => `${heading.level}:${heading.id}:${heading.text}`).join("\n");
}

// ---------------------------------------------------------------------------
// Ordinals for the scroll regions.
// ---------------------------------------------------------------------------

/**
 * A stable "which one is this?" for a rendered node.
 *
 * Keyed on the hast node rather than on a bare counter because
 * `reactStrictMode` is on (`web/next.config.mjs`) and StrictMode invokes a
 * component's render function twice with the SAME props object. A bare
 * counter would make the first table "Table 1" and then "Table 2" on the
 * second invocation, so the accessible name would depend on the build mode.
 * A Map keyed on the node returns the same ordinal both times.
 */
function ordinalCounter(): (node: unknown) => number {
  const seen = new Map<unknown, number>();
  return (node) => {
    const existing = seen.get(node);
    if (existing !== undefined) return existing;
    const next = seen.size + 1;
    seen.set(node, next);
    return next;
  };
}

/** The subset of a Markdown element's props these overrides read. */
interface MarkdownElementProps {
  node?: unknown;
  children?: ReactNode;
}

// ---------------------------------------------------------------------------
// The component.
// ---------------------------------------------------------------------------

/**
 * The two backend strings a failed run carries (RC-16). Never edited.
 *
 * An alias rather than a second declaration: `selectBriefings`
 * (`lib/report/briefings.ts`) is what hands this to a surface, so the two
 * cannot describe different shapes. Type-only, so the selector's code does
 * not enter this component's bundle.
 */
export type ReportFailure = BriefingFailure;

export interface ReportReaderProps {
  /** The briefing body, raw Markdown. `""` is the absent state. */
  markdown: string;
  /**
   * The one Markdown renderer, or `null` while the pipeline is still being
   * imported. WO-20 supplies it from `useReportRenderer`.
   */
  renderer: ReportRenderer | null;
  /**
   * Present when the run failed. With a non-empty `markdown` this is the
   * partial-briefing state (03 §2.2 row 14); with an empty one it is row 15.
   */
  failure?: ReportFailure | null;
  /** The heading the reader is currently at, if the composer tracks one. */
  activeHeadingId?: string | null;
  /** Beside the title — WO-19's `ExportDisclosure`. */
  actions?: ReactNode;
  /** Beneath the briefing, never above it — WO-19's `MetricsStrip`. */
  metrics?: ReactNode;
  id?: string;
  className?: string;
}

export function ReportReader({
  markdown,
  renderer: Renderer,
  failure = null,
  activeHeadingId = null,
  actions,
  metrics,
  id,
  className,
}: ReportReaderProps) {
  const titleId = useId();
  const bodyRef = useRef<HTMLElement>(null);
  const [headings, setHeadings] = useState<readonly ReportHeading[]>([]);

  const body = markdown.trim();
  const hasBriefing = body !== "";
  const described =
    failure === null ? null : describeErrorType(failure.errorType, failure.error);

  useEffect(() => {
    const root = bodyRef.current;
    const next = root === null ? [] : readHeadings(root);
    setHeadings((previous) =>
      headingKey(previous) === headingKey(next) ? previous : next,
    );
  }, [body, Renderer]);

  /**
   * The parsed briefing, memoised on its two real inputs.
   *
   * Not an optimisation for its own sake. A scroll-spy that moves
   * `activeHeadingId` re-renders this component on every heading the reader
   * passes, and without the memo each of those would re-parse the whole
   * Markdown document and rebuild every DOM node under it — which would also
   * throw away the ids `readHeadings` wrote and make the rail flicker.
   * Returning the same element makes React skip the subtree outright.
   *
   * The two ordinal counters live INSIDE the memo, so they restart with each
   * parse and are stable across every render that reuses one.
   */
  const parsed = useMemo(() => {
    if (Renderer === null) return null;

    const tableOrdinal = ordinalCounter();
    const codeOrdinal = ordinalCounter();

    return (
      <Renderer
        components={{
          // 03 §7.5 / 04 §8.3 item 4: the TABLE pans, the PAGE does not. The
          // region is focusable and named, so it is reachable by keyboard and
          // announced as something rather than as "region".
          table: ({ node, children }: MarkdownElementProps) => (
            <ScrollRegion label={tableRegionLabel(tableOrdinal(node))}>
              <table>{children}</table>
            </ScrollRegion>
          ),
          // A fenced block is the other thing in a briefing that is wider
          // than 68ch and cannot be wrapped without changing its meaning.
          pre: ({ node, children }: MarkdownElementProps) => (
            <ScrollRegion label={codeRegionLabel(codeOrdinal(node))}>
              <pre>{children}</pre>
            </ScrollRegion>
          ),
        }}
      >
        {body}
      </Renderer>
    );
  }, [Renderer, body]);

  return (
    <section
      id={id}
      aria-labelledby={titleId}
      data-report-reader="true"
      data-partial={hasBriefing && described !== null ? "true" : "false"}
      className={cx("ew-report-reader", className)}
    >
      {described === null || failure === null ? null : (
        <StatusBanner
          severity="critical"
          // No `word` in the no-briefing case: `StatusBanner` falls back to
          // `SEVERITY_WORD.critical` ("Failed"), so that word has one home.
          word={hasBriefing ? REPORT.partialWord : undefined}
          sentence={hasBriefing ? REPORT.partial : described.sentence}
          recovery={
            hasBriefing ? (
              <>
                {described.sentence} {described.recovery}
              </>
            ) : (
              described.recovery
            )
          }
          evidence={rawErrorEvidence(failure.errorType, failure.error)}
          className="ew-report-reader__banner"
        >
          {hasBriefing ? (
            <p className="ew-report-reader__note">{REPORT.partialDetail}</p>
          ) : null}
        </StatusBanner>
      )}

      <header className="ew-report-reader__header">
        <h2 id={titleId} className="ew-report-reader__title">
          {REPORT.heading}
        </h2>
        {actions === undefined ? null : (
          <div className="ew-report-reader__actions">{actions}</div>
        )}
      </header>

      {!hasBriefing ? (
        <p className="ew-report-reader__note">
          {described === null ? REPORT.empty : REPORT.noBriefing}
        </p>
      ) : Renderer === null ? (
        <div className="ew-report-reader__loading" aria-busy="true">
          <Skeleton lines={7} label={REPORT.loading} />
        </div>
      ) : (
        <div className="ew-report-reader__columns">
          <SectionRail
            headings={headings}
            label={REPORT.railLabel}
            activeId={activeHeadingId}
          />
          <article ref={bodyRef} data-briefing="true" className="ew-report">
            {parsed}
          </article>
        </div>
      )}

      {metrics === undefined ? null : (
        <div className="ew-report-reader__metrics">{metrics}</div>
      )}
    </section>
  );
}
