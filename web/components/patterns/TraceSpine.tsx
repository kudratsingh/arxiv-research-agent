/**
 * TraceSpine — the product's signature surface (03 §5, WO-15).
 *
 * ==========================================================================
 * WHAT THIS COMPONENT IS ALLOWED TO KNOW
 *
 * One prop carries data: `inputs`, which is 03 §5.2's four inputs and
 * nothing else. Every branch below reads `describeSpine(inputs)` and no
 * other source — no job id, no query, no `error`, no `cost_usd`, no frame
 * log, no clock. That is what makes criterion 1's purity test a property of
 * the file rather than a claim about it: two `JobState`s that differ in
 * every field except the four produce byte-identical DOM here.
 *
 * The derivation lives in `web/lib/spine/state.ts`, which is where the
 * twelve states of 03 §5.4 and the reasoning for each cell are written
 * down. This file is a renderer.
 *
 * ==========================================================================
 * THE FIVE STRUCTURAL RULES, AND THE CRITERION EACH ONE DISCHARGES
 *
 *  - AN `<ol>` OF FOUR SEGMENTS IN A LABELLED REGION, WITH A NESTED `<ol>`
 *    LEDGER (criterion 6, 03 §5.7). The region is a `<section>` named by a
 *    clipped `<h2>`; the ledger is `CheckpointLedger`, rendered inside the
 *    Run segment's own `<li>`.
 *
 *  - ONE `role="status"`, PRODUCT-WIDE (criterion 6, 03 §7.3). It wraps the
 *    ANNOUNCEMENT only. The count and the age sit beside it, outside the
 *    live region, precisely because they change on every `node_completed`
 *    and §5.7 says the region announces material transitions "never
 *    individual checkpoints". WO-12's StatusBanner has no branch that emits
 *    `role="status"`; its header says so and its tests hold it to that.
 *
 *  - EVERY MARK HAS A TEXT EQUIVALENT ON THE SAME VISUAL LINE (criterion 5,
 *    03 §3.4). `SEGMENT_MARK` and `SEGMENT_WORD` are two total maps over
 *    the same eight statuses, and the word is rendered as ordinary text.
 *    Colour is third: `SEGMENT_TONE` may be taken away by forced colours
 *    without removing a single fact from the page.
 *
 *  - THE TICK ENTRANCE IS OPACITY ONLY (criterion 7, 03 §5.6). See
 *    `spine.css`; there is no transform in this surface to begin with.
 *    jsdom cannot measure layout shift, so the CLS 0.000 claim is asserted
 *    here as "no property that could move anything" plus an unchanged-DOM
 *    check around an arriving tick, and MEASURED in WO-21's Playwright
 *    tier. That split is deliberate and is recorded in the test file — and
 *    WO-W13c is what the split costs when it is read as "no transform, so
 *    nothing moves": the status line below moved 3px every time the socket
 *    opened, because the `Live` badge joined a BASELINE-aligned row with a
 *    baseline synthesised from a mark. `spine.css` rule 4 is the fix and
 *    the measurement; nothing about it is visible in a transform audit.
 *
 *  - THE BLIND SPOT IS STATIC, AND AMBIENT MOTION NEEDS AN OPEN SOCKET
 *    (criterion 8, 03 §5.6). `.ew-spine-void` has no animation in any
 *    media condition. The `Live` badge is rendered only when
 *    `model.live` — which is `connection === "open"` — and its pulse is
 *    already removed under reduced motion by `primitives.css`, leaving a
 *    static mark and the word.
 *
 * ==========================================================================
 * INSERTION POINT — STRUCTURED EVIDENCE (criterion 10, 03 §2.3, D-007)
 *
 * Per-checkpoint structured evidence (the papers a `searcher` checkpoint
 * found, the claims a `verifier` checked) would attach HERE: as a
 * disclosure inside each `CheckpointLedger` entry, fed by a new field on a
 * VERSIONED backend contract.
 *
 * IT IS A COMMENT AND NOT CODE, ON PURPOSE. `node_completed.state_delta` is
 * an open, scalar-filtered map (`runner.py:947-955`) with no schema and no
 * guarantee; `JobDetail` has no evidence field at all. Rendering today's
 * `state_delta` as "evidence" would present a debug channel as a
 * defensible artefact, which is the exact failure mode this surface exists
 * to avoid. 06-WORK-ORDERS.md §7 lists this as not scheduled: "Not in
 * `JobDetail`. Separate versioned backend contract; WO-15 ships the
 * documented insertion point only." Nothing below reads `stateDelta`.
 */

import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Disclosure } from "@/components/primitives/Disclosure";
import { Mark, type StatusMarkShape } from "@/components/primitives/marks";
import { VisuallyHidden } from "@/components/primitives/VisuallyHidden";
import { SPINE_LEGEND, SPINE_SEGMENTS } from "@/lib/copy/trace";
import { SPINE, segmentLabel } from "@/lib/copy/spine";
import {
  SEGMENT_WORD,
  describeSpine,
  type SegmentStatus,
  type SpineInputs,
} from "@/lib/spine/state";

import { CheckpointLedger } from "./CheckpointLedger";
import "./spine.css";

// ---------------------------------------------------------------------------
// 03 §3.4's table, as three total maps over the same eight keys.
//
// Eight statuses, eight WORDS (in lib/spine/state.ts, because they are
// copy), eight distinct SHAPES, and five colour roles. The shapes are what
// survive forced colours; the words are what survive images being
// unavailable; the colour is third and is the only one of the three a user
// agent is allowed to take away.
// ---------------------------------------------------------------------------

/** Distinct per status. Eight keys, eight shapes, no repeats. */
export const SEGMENT_MARK: Record<SegmentStatus, StatusMarkShape> = {
  observed: "circle",
  live: "ring",
  "not-observed": "dashed-rule",
  "awaiting-review": "diamond",
  complete: "square",
  failed: "slashed-square",
  cancelled: "hollow-square",
  unavailable: "dashed-square",
};

/**
 * Colour, third and last.
 *
 * Every one of these is a `-text` role or an `ink-*` role, which are the
 * ones measured against a surface; criterion 9's test recomputes each ratio
 * out of `app/tokens.css` in both themes.
 */
export const SEGMENT_TONE: Record<SegmentStatus, string> = {
  observed: "text-signature-text",
  live: "text-signature-text",
  "not-observed": "text-ink-faint",
  "awaiting-review": "text-review-text",
  complete: "text-signature-text",
  failed: "text-critical-text",
  cancelled: "text-ink-muted",
  unavailable: "text-ink-faint",
};

/** The Run segment's index in `SPINE_SEGMENTS`. It holds the ledger. */
const RUN_SEGMENT = 2;

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part)).join(" ");
}

// ---------------------------------------------------------------------------

export interface TraceSpineProps {
  /**
   * 03 §5.2's four inputs, or `null` when there is no run on screen at all.
   *
   * `null` is not a thirteenth state — it is the absence of one. The spine
   * renders its four segment names inert and says nothing, which is the
   * same shape 03 §1.4's landing legend shows before a question is asked.
   */
  inputs: SpineInputs | null;
  /**
   * 03 §5.3: the legend is "rendered in the UI once per session and
   * available from a disclosure thereafter". The composing surface owns
   * that once-per-session decision (WO-20); this prop is how it says so.
   */
  legend?: "open" | "disclosure" | "none";
  /** Ids are derived from this so a page may hold more than one. */
  id?: string;
  className?: string;
}

export function TraceSpine({
  inputs,
  legend = "disclosure",
  id = "trace-spine",
  className,
}: TraceSpineProps) {
  const headingId = `${id}-label`;
  const model = inputs === null ? null : describeSpine(inputs);

  // No run: the four names from the dictionary, every one of them
  // unobserved. Nothing is claimed, and the shape the user is about to meet
  // is already on screen — which is the same shape 03 §1.4's landing legend
  // shows before a question is asked.
  const segments =
    model?.segments ??
    SPINE_SEGMENTS.map((name) => ({
      name,
      status: "not-observed" as SegmentStatus,
      word: SEGMENT_WORD["not-observed"],
    }));

  return (
    <section
      id={id}
      aria-labelledby={headingId}
      data-spine-state={model?.id ?? "none"}
      data-live={model?.live === true ? "true" : "false"}
      className={cx("flex flex-col gap-3", className)}
    >
      <VisuallyHidden as="h2" id={headingId}>
        {SPINE.regionLabel}
      </VisuallyHidden>

      <ol className="flex flex-wrap items-start gap-x-6 gap-y-3">
        {segments.map((segment, index) => (
          <li
            key={segment.name}
            data-segment={segment.name}
            data-status={segment.status}
            className={cx(
              "flex min-w-0 flex-col gap-1",
              // The run segment owns the ledger and the void, so it takes
              // the row's remaining width and wraps to its own line on a
              // narrow viewport rather than squeezing the other three.
              index === RUN_SEGMENT && "min-w-full flex-1 md:min-w-0",
            )}
          >
            <span className="flex items-center gap-2 text-ui-sm font-medium text-ink">
              <Mark
                mark={SEGMENT_MARK[segment.status]}
                className={SEGMENT_TONE[segment.status]}
              />
              {/* Both halves are on screen and both are clipped from the
                  accessibility tree, because the clipped line below is the
                  two of them joined: a reader hears "Question · observed"
                  once instead of the name and the word as two unrelated
                  fragments, and a viewer sees them on the same visual line
                  as the mark (03 §5.7). */}
              <span aria-hidden="true">{segment.name}</span>
              <VisuallyHidden>{segmentLabel(segment.name, segment.word)}</VisuallyHidden>
            </span>

            <span aria-hidden="true" className="text-ui-xs text-ink-muted">
              {segment.word}
            </span>

            {index === RUN_SEGMENT ? (
              <div className="ew-spine-run">
                {model === null ? null : (
                  <CheckpointLedger
                    checkpoints={model.ledger}
                    current={model.current}
                    empty="hidden"
                  />
                )}
                {/* The dimensioned, static, dashed void (03 §5.8). It is
                    aria-hidden because the word beside it and the sentence
                    below it are the accessible carriers; the shape is the
                    redundant channel, exactly as every other mark here. */}
                <span
                  aria-hidden="true"
                  data-spine-part="void"
                  data-current={model?.current === true ? "true" : "false"}
                  className="ew-spine-void"
                />
                {/* Suppressed only when the segment's own word already says
                    it, which is the one case it would be printed twice. */}
                {segment.status === "not-observed" ? null : (
                  <span className="whitespace-nowrap text-ui-xs text-ink-faint">
                    {SPINE.voidWord}
                  </span>
                )}
              </div>
            ) : null}
          </li>
        ))}
      </ol>

      <p className="text-ui-xs text-ink-faint">{SPINE.voidDescription}</p>

      {model === null ? null : (
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-ui-sm text-ink">
          {/* THE product's single role="status". Announcement only. */}
          <span role="status" data-spine-part="announcement">
            {model.announcement}
          </span>
          {model.detail === null ? null : (
            <span className="text-ink-muted" data-spine-part="detail">
              <span aria-hidden="true">{model.separator}</span>
              {model.detail}
            </span>
          )}
          {model.live ? (
            /* `ew-spine-live` is not decoration: it takes the badge OUT of
               this line's baseline alignment. The badge's baseline is
               synthesised from a 16px mark rather than from text, so
               aligning it grew the line from 20px to 23px and moved the
               reading column by 3px every time the socket opened — which is
               criterion 7's "a checkpoint arriving must never move the
               reading column". `spine.css` rule 4 has the measurement. */
            <StatusBadge severity="live" ambient className="ew-spine-live">
              {SEGMENT_WORD.live}
            </StatusBadge>
          ) : null}
        </p>
      )}

      {legend === "none" ? null : legend === "open" ? (
        <SpineLegend />
      ) : (
        <Disclosure label={SPINE.legendLabel}>
          <SpineLegend />
        </Disclosure>
      )}
    </section>
  );
}

/** 03 §5.3's legend, straight out of WO-12's `SPINE_LEGEND`. */
function SpineLegend() {
  return (
    <ul data-spine-part="legend" className="flex flex-wrap gap-x-6 gap-y-2">
      {SPINE_LEGEND.map((entry) => (
        <li key={entry.mark} className="flex items-center gap-2 text-ui-xs text-ink-muted">
          <Mark mark={entry.mark as StatusMarkShape} />
          {entry.meaning}
        </li>
      ))}
    </ul>
  );
}
