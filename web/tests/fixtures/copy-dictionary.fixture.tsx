/**
 * WO-12 criterion 1 — the fixture that MUST pass lint.
 *
 * The negative fixture proves `copy/no-inline-text` fires. This one proves
 * it is not merely a ban on writing components: everything a pattern
 * legitimately does is here, and none of it trips the rule.
 *
 *   - Sentences arrive from web/lib/copy and are rendered through
 *     identifiers and member expressions.
 *   - Composed status strings arrive from the dictionary's functions, not
 *     from a template in the component.
 *   - Non-rendered strings — aria-label, data attributes, class names,
 *     keys, a `role` — are out of scope and stay where they are useful.
 *   - Colours come from token utilities, so WO-01's selectors stay silent
 *     too. That silence is the evidence that this block carries both rule
 *     sets rather than replacing one with the other.
 */

import { describeErrorType, rawErrorEvidence } from "@/lib/copy/errors";
import { RUN_STATUS_LINE, failedStatusLine, runningStatusLine } from "@/lib/copy/run";
import { THREAD_RAIL } from "@/lib/copy/threads";

export function DictionaryFixture({
  checkpoints,
  node,
  errorType,
  error,
}: {
  checkpoints: number;
  node: string | null;
  errorType: string | null;
  error: string | null;
}) {
  const failure = describeErrorType(errorType, error);
  return (
    <section className="flex flex-col gap-2 bg-surface text-ink" data-kind="fixture">
      <h2 className="text-ui-lg">{THREAD_RAIL.heading}</h2>
      <p>{runningStatusLine(checkpoints)}</p>
      <p>{failedStatusLine(node)}</p>
      <p>{RUN_STATUS_LINE.reconnecting}</p>
      <p>{failure.sentence}</p>
      <p>{failure.recovery}</p>
      <dl>
        {rawErrorEvidence(errorType, error).map((row) => (
          <div key={row.label}>
            <dt className="font-mono text-mono-sm">{row.label}</dt>
            <dd className="font-mono text-mono-sm">{row.value}</dd>
          </div>
        ))}
      </dl>
      <button type="button" aria-label={THREAD_RAIL.retry} data-action="retry">
        {THREAD_RAIL.retry}
      </button>
    </section>
  );
}
