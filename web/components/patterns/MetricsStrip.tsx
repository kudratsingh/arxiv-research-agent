/**
 * MetricsStrip — the run's five real numbers, under the briefing (WO-19).
 *
 * WHAT SURVIVES FROM `JobSummary`, AND WHAT DOES NOT (RC-21). The MUST-KEEP
 * is the contract, not the module: the five fields (iterations, quality
 * score, cost, LLM calls, elapsed — `00-DISCOVERY.md` MUST-KEEP 10), their
 * order, their formats (`$0.1800`, `0.82`, `12.4s`) and the `<dl>` shape are
 * reproduced here exactly. What changes is where it lives, what it is made
 * of, and where it sits: 03 §4.7 asks for the strip "attached beneath the
 * briefing they describe rather than floating as a dashboard row", and
 * `JobSummary.tsx:11` is a bordered card that renders ABOVE the report in
 * `ConversationThread.tsx:239`. The position is the design change; the
 * numbers are untouched.
 *
 * NULL IS AN EM DASH WITH A VISIBLE EXPLANATION (criterion 2). Three things
 * are wrong with `JobSummary.tsx:36`'s `-`: a hyphen-minus in a column of
 * figures reads as a minus sign, it says nothing about WHY the number is
 * missing, and there is nowhere for it to say so. Here the dash is U+2014,
 * the `dd` carries "not reported" for a screen reader in place of a glyph
 * most ATs either skip or read as "dash", and a visible note under the strip
 * explains the symbol whenever one is on screen. Not a `title`: 03 §4.7 says
 * "title-free" and the reason is that a `title` is unreachable by keyboard,
 * invisible on touch and unread by most screen readers.
 *
 * NO HOOKS, SO NOT A CLIENT COMPONENT. Every state is reachable by passing
 * props (04 §5.1), which is what keeps its three stories free of MSW, and it
 * costs the `/c/[id]` route no JavaScript at all — the strip renders on the
 * server and ships as HTML.
 *
 * NO STRING IS WRITTEN IN THIS FILE. `copy/no-inline-text` covers
 * `components/patterns/`; every label and sentence arrives from
 * `lib/copy/metrics`. The number FORMATS below are not copy and are
 * deliberately not in the dictionary: `$` and `s` are how a quantity is
 * written, not something the product says, and `web/tests/copy/forbidden.test.ts`
 * gates sentences.
 */

import { VisuallyHidden } from "@/components/primitives/VisuallyHidden";
import { cx } from "@/components/primitives/styles";
import { METRICS } from "@/lib/copy/metrics";

import "./metrics.css";

// ---------------------------------------------------------------------------
// The five numbers.
// ---------------------------------------------------------------------------

/**
 * What a run reported about itself. `null` for every field the API left out.
 *
 * Camel-cased and flat rather than a `JobDetail`, because a pattern takes
 * plain props: `MetricsStrip` cannot be handed a shape only the data layer
 * can build, or its stories would need the data layer to build one.
 * `readRunMetrics` below is the one adapter between the two.
 */
export interface RunMetrics {
  iterations: number | null;
  qualityScore: number | null;
  costUsd: number | null;
  llmCalls: number | null;
  elapsedSec: number | null;
}

/**
 * The five fields of `JobDetail` this strip reads, structurally.
 *
 * Deliberately NOT `Pick<JobDetail, …>`: an `import type` from `@/lib/api`
 * would be erased at build time but is still a real edge in the module
 * graph, and `web/vitest.config.mts` records what happened the last time
 * `lib/api` reached the Storybook project through a story's component. The
 * structural shape here is pinned to the generated one by a compile-time
 * assignability assertion in `web/tests/patterns/MetricsStrip.test.tsx`, so
 * a renamed field upstream still fails a check — it fails that one.
 */
export interface RunMetricsSource {
  iterations?: number | null;
  quality_score?: number | null;
  cost_usd?: number | null;
  llm_calls?: number | null;
  elapsed_sec?: number | null;
}

/**
 * A `JobDetail`'s five metric fields, normalised.
 *
 * `undefined` and a non-finite number both become `null` — the strip has one
 * absent state and it means "the API did not report this". A `NaN` reaching
 * the `dd` would render the literal text "NaN", which is the one outcome
 * worse than a dash.
 */
export function readRunMetrics(detail: RunMetricsSource): RunMetrics {
  return {
    iterations: finite(detail.iterations),
    qualityScore: finite(detail.quality_score),
    costUsd: finite(detail.cost_usd),
    llmCalls: finite(detail.llm_calls),
    elapsedSec: finite(detail.elapsed_sec),
  };
}

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// ---------------------------------------------------------------------------
// Formats, carried over from JobSummary unchanged.
// ---------------------------------------------------------------------------

/** Iterations and LLM calls: whole numbers, printed as they arrived. */
export function formatCount(value: number): string {
  return String(value);
}

/** `quality_score` is a 0–1 fraction; two places is what the baseline shows. */
export function formatScore(value: number): string {
  return value.toFixed(2);
}

/**
 * Four decimal places, because a run can genuinely cost $0.0002 and two
 * places would round the whole strip to `$0.00` — the number the user is
 * most likely to be checking, reported as zero.
 */
export function formatCost(value: number): string {
  return `$${value.toFixed(4)}`;
}

/** Seconds, one place. `elapsed_sec` is a float on the wire. */
export function formatDuration(value: number): string {
  return `${value.toFixed(1)}s`;
}

interface MetricField {
  key: keyof RunMetrics;
  label: string;
  format: (value: number) => string;
}

/**
 * The five, in `JobSummary`'s order (`JobSummary.tsx:12-16`).
 *
 * The order is part of what RC-21 preserves: iterations and LLM calls
 * bracket the two numbers a reader actually judges the run by — quality and
 * cost — and elapsed closes it.
 */
const FIELDS: readonly MetricField[] = [
  { key: "iterations", label: METRICS.iterationsLabel, format: formatCount },
  { key: "qualityScore", label: METRICS.qualityLabel, format: formatScore },
  { key: "costUsd", label: METRICS.costLabel, format: formatCost },
  { key: "llmCalls", label: METRICS.callsLabel, format: formatCount },
  { key: "elapsedSec", label: METRICS.durationLabel, format: formatDuration },
];

// ---------------------------------------------------------------------------
// The component.
// ---------------------------------------------------------------------------

export interface MetricsStripProps {
  metrics: RunMetrics;
  id?: string;
  className?: string;
}

export function MetricsStrip({ metrics, id, className }: MetricsStripProps) {
  // The note is a legend for a symbol; it renders only when the symbol does.
  const hasAbsent = FIELDS.some((field) => metrics[field.key] === null);

  return (
    <section
      id={id}
      // A named `section` is a `region`, which is the one generic container
      // that can carry an accessible name without inventing a heading the
      // design does not have. The strip needs the name: five bare numbers
      // under a briefing are not self-describing when read out of order.
      aria-label={METRICS.label}
      data-metrics="true"
      data-absent={hasAbsent ? "true" : "false"}
      className={cx("ew-metrics", className)}
    >
      <dl className="ew-metrics__list">
        {FIELDS.map((field) => {
          const value = metrics[field.key];
          return (
            <div key={field.key} className="ew-metrics__item">
              <dt className="ew-metrics__label font-ui">{field.label}</dt>
              <dd
                data-field={field.key}
                data-reported={value === null ? "false" : "true"}
                className={cx(
                  // The family is a utility, not a rule: WO-02 criterion 6
                  // keeps every family declaration in app/tokens.css.
                  "ew-metrics__value font-mono",
                  value === null && "ew-metrics__value--absent",
                )}
              >
                {value === null ? (
                  <>
                    {/* Visible, and hidden from the accessibility tree, so a
                        screen reader reads the words beside it instead of a
                        glyph it may not announce at all. */}
                    <span aria-hidden="true">{METRICS.absent}</span>
                    <VisuallyHidden>{METRICS.absentReading}</VisuallyHidden>
                  </>
                ) : (
                  field.format(value)
                )}
              </dd>
            </div>
          );
        })}
      </dl>

      {hasAbsent ? <p className="ew-metrics__note font-ui">{METRICS.absentNote}</p> : null}
    </section>
  );
}
