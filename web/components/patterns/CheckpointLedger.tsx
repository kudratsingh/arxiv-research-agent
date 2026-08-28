/**
 * CheckpointLedger — the append-only list of what this connection saw.
 *
 * THE ONE RULE (03 §5.9 obligation 3, WO-15 criterion 2): **the ledger
 * never contains a label that did not arrive in a `node_completed`
 * payload.** There is exactly one way a label reaches the DOM below —
 * `checkpointName(checkpoint.node)` on an entry the caller passed in — and
 * there is no vocabulary, no lookup table, no default and no placeholder
 * label anywhere in this file. Grep it: the only strings here come from
 * `lib/copy/`, and the only one that describes a checkpoint is the word
 * "observed".
 *
 * COPY COMES FROM `@/lib/copy/trace`, NOT `@/lib/copy/run`. Same strings,
 * same single edit site (`run.ts` re-exports the module); the boundary
 * keeps the landing composer's and the metrics strip's functions out of
 * this component's module graph, which is what `web/vitest.config.mts`'s
 * recorded measurement hazard costs when it is not done. See
 * `web/lib/copy/trace.ts`'s header.
 *
 * WHY `checkpointName` AND NOT `checkpointLabel`. `lib/job/machine.ts`
 * exports `checkpointLabel()`, which returns the literal `"unknown"` when
 * nothing has been observed. That string is banned product-wide (03 §5.5:
 * "not reported" rather than "unknown", because silence is the API's
 * behaviour and not a gap in our knowledge of it) and
 * `web/tests/copy/forbidden.test.ts` fails on it. So `checkpointLabel` is a
 * diagnostic helper that nothing renders; the machine exposes the RAW
 * absence through `observedNode()`, and this file turns it into text with
 * the dictionary's `checkpointName()`. A node the payload did not name
 * reads "not reported" — never "unknown", and never a guess.
 *
 * WHY THE LEDGER IS ITS OWN COMPONENT. It has states the spine never shows
 * it in: empty on its own, a single entry, forty entries that have to pan
 * rather than reflow the page, and an entry whose label the payload did not
 * carry. That is RC-10's fourth uncovered component and WO-15 criterion
 * 11's second story group.
 *
 * No hooks and no state: a server component (04 §8.1).
 */

import { Mark } from "@/components/primitives/marks";
import { ScrollRegion } from "@/components/primitives/ScrollRegion";
import { VisuallyHidden } from "@/components/primitives/VisuallyHidden";
import { checkpointName, observedCheckpoint } from "@/lib/copy/trace";
import { SPINE } from "@/lib/copy/spine";
import type { ObservedCheckpoint } from "@/lib/job/types";

import "./spine.css";

export interface CheckpointLedgerProps {
  /**
   * Every `node_completed` observed on the currently-open stream, in
   * receive order. Reset on every open, including the browser's own retry
   * (04 §4.4 rule 2) — which is why the count is only ever true "on this
   * connection".
   */
  checkpoints: readonly ObservedCheckpoint[];
  /**
   * `sentence` states the empty case in words; `hidden` renders nothing at
   * all. `TraceSpine` passes `hidden` because its status line already
   * carries the count, and a run segment that said "No checkpoints observed
   * on this connection" beside a status line saying the same thing would be
   * noise rather than honesty.
   */
  empty?: "sentence" | "hidden";
  /**
   * `false` once the connection that observed these ended (03 §5.4,
   * "Reconnecting: ticks kept"). The entries stay — they really were
   * observed — and this is what stops the surface implying they describe
   * now. Exposed as `data-current` for the spine's trailing rule.
   */
  current?: boolean;
  id?: string;
  className?: string;
}

export function CheckpointLedger({
  checkpoints,
  empty = "sentence",
  current = true,
  id,
  className,
}: CheckpointLedgerProps) {
  if (checkpoints.length === 0) {
    if (empty === "hidden") return null;
    return (
      <p
        id={id}
        data-checkpoint-count={0}
        className={["text-ui-xs text-ink-muted", className].filter(Boolean).join(" ")}
      >
        {SPINE.ledgerEmpty}
      </p>
    );
  }

  return (
    <ScrollRegion
      label={SPINE.ledgerLabel}
      className={["ew-spine-ledger", className].filter(Boolean).join(" ")}
    >
      <ol
        id={id}
        aria-label={SPINE.ledgerLabel}
        data-checkpoint-count={checkpoints.length}
        data-current={current ? "true" : "false"}
        className="flex items-center gap-3"
      >
        {checkpoints.map((checkpoint, index) => (
          <li
            // Neither the label nor the receive time is unique — the
            // supervisor graph may revisit a node, and two frames can land
            // in the same millisecond — so the position in an append-only
            // list is the only stable identity an entry has.
            key={`${index}-${checkpoint.node}`}
            data-checkpoint-index={index}
            className="ew-spine-tick flex items-center gap-1 whitespace-nowrap"
          >
            {/* The word first, then the mark (03 §3.4), and the qualifier
                travels with the name: an entry reads "observed planner" to
                a screen reader and shows `planner` on screen. The visible
                span is `aria-hidden` so the label is announced ONCE — the
                clipped form is the complete sentence, not a prefix to it. */}
            <VisuallyHidden>{observedCheckpoint(checkpoint.node)}</VisuallyHidden>
            <Mark mark="circle" className="text-signature-text" />
            <span aria-hidden="true" className="font-mono text-mono-xs text-ink">
              {checkpointName(checkpoint.node)}
            </span>
          </li>
        ))}
      </ol>
    </ScrollRegion>
  );
}
