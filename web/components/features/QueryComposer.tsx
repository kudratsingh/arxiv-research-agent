"use client";

/**
 * QueryComposer — the surface a question is asked from (WO-13; 03 §4.3).
 *
 * Two variants, one component: **landing** (display prompt, disclosure,
 * process strip, "Generate plan") and **follow-up** (the same field and the
 * same disclosure, without the display heading or the strip). States, from
 * 03 §4.3: empty · typing with the counter · over 8,000 with submit blocked
 * and the counter critical · submitting · refusing because the research
 * service is unreachable · failed with the question retained.
 *
 * IT HOLDS NO DATA AND MAKES NO REQUEST. Every state above is reachable by
 * passing props, which is what lets `QueryComposer.stories.tsx` render all
 * ten of criterion 9's states with no MSW, no network and no provider — and
 * what keeps `lib/job/` and `lib/queries/` out of the Storybook project's
 * module graph, where a partly-exercised module inflates the merged
 * functions denominator (the measurement hazard `vitest.config.mts` records
 * for WO-13 … WO-19). The wiring — `useJobRun().submit`, the thread that is
 * created first, the `?job=` hand-off — is one file over, in
 * `LandingComposer.tsx`.
 *
 * FOUR THINGS ARE LOAD-BEARING RATHER THAN STYLISTIC.
 *
 * 1. **The disclosure is body copy, immediately above the button.** 03 §1.4:
 *    "not a tooltip, not a footnote, not revealed on hover". It is a `<p>`
 *    that is the button's immediately-preceding sibling, it is in the
 *    accessible description of the button, and it is on screen before any
 *    interaction. Criterion 1 asserts every one of those.
 *
 * 2. **The counter comes from `queryCounter()`, not from `Textarea`'s own
 *    `limit` counter.** The primitive prints `{count} / {limit}` — "0 /
 *    8000" — and 03 §1.4 prints `0 / 8,000`, which criterion 1 asserts
 *    string-for-string. Two counters differing only in a comma would be
 *    worse than either, so the composer renders §1.4's and the primitive's
 *    is left off. The property the `limit` prop exists for is kept exactly:
 *    **no `maxLength` is ever passed**, so an over-length paste is retained
 *    in full and refused in words rather than silently truncated, and
 *    `Textarea`'s `error` slot carries `queryOverLimit()` so the field is
 *    `aria-invalid` and critical-bordered at the same moment the counter
 *    turns critical. A test asserts the missing `maxLength` and the
 *    retained paste.
 *
 * 3. **Submit is refused with `aria-disabled`, never with `disabled`**
 *    (criterion 7, 03 §2.2 row 4). A `disabled` button drops out of the tab
 *    order and takes its own explanation with it; `aria-disabled` keeps the
 *    control focusable and `aria-describedby` puts the reason — the
 *    unreachable sentence, or the over-limit sentence, or "type a question
 *    first" — into its accessible description. Every refusal has a stated
 *    reason; none of them is a grey rectangle.
 *
 * 4. **There is exactly one submit control, and it never fires twice for
 *    one intent** (criterion 5, R-01, H6). `POST /research` has no
 *    idempotency key (`routes.py:179-197`), so a duplicate is a duplicate
 *    charge. The guard here is a ref that flips synchronously inside the
 *    handler and clears only when the returned promise settles, which holds
 *    across a double click, across Enter-plus-click, and across a
 *    `Cmd/Ctrl+Enter` that lands in the same tick as a click. It is the
 *    outermost of three: the machine's `submitInFlightRef` and the
 *    reducer's own refusal of `submit_requested` while `submitting` sit
 *    under it. And there is no automatic retry on any path — no timer, no
 *    effect, no `online` listener. After a failure the same single button
 *    is the manual resubmit, which is why no second "Retry" control is
 *    rendered: a control labelled *retry* invites a reflex where the
 *    honest action is a decision.
 *
 * NO STRING IS TYPED IN THIS FILE. `copy/no-inline-text` covers
 * `components/features/**`; every word comes from `lib/copy/composer` —
 * which owns 03 §1.4 verbatim, and which `lib/copy/run` re-exports for
 * every other consumer — or from `lib/copy/errors`, whose
 * `describeFailure()` is the one accessor for a normalized failure.
 */

import {
  useCallback,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { ALERT_SEVERITIES, StatusBanner } from "@/components/patterns/StatusBanner";
import { Button } from "@/components/primitives/Button";
import { Textarea } from "@/components/primitives/Textarea";
import {
  VISUALLY_HIDDEN_CLASS,
  VisuallyHidden,
} from "@/components/primitives/VisuallyHidden";
import {
  COMPOSER,
  LANDING,
  MAX_QUERY_LEN,
  queryCounter,
  queryOverLimit,
} from "@/lib/copy/composer";
import { describeFailure } from "@/lib/copy/errors";
// Type-only: the composer never calls the client, and a value import here
// would put `lib/api` into the Storybook project's graph for nothing.
import type { ApiFailure } from "@/lib/api";

// ---------------------------------------------------------------------------
// Props.
// ---------------------------------------------------------------------------

/** 03 §4.3's two variants. */
export type QueryComposerVariant = "landing" | "follow-up";

/**
 * The fraction of `MAX_QUERY_LEN` at which the counter starts warning.
 *
 * Same default as `Textarea`'s `nearLimitRatio`, restated here because the
 * composer owns its own counter (see the header) and the two must not
 * drift.
 */
export const NEAR_LIMIT_RATIO = 0.9;

export interface QueryComposerProps {
  /** Defaults to the landing surface. */
  variant?: QueryComposerVariant;
  /** Controlled value. Omit for an uncontrolled field. */
  value?: string;
  /** Initial value of an uncontrolled field. */
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  /**
   * The ONLY way a question leaves this component.
   *
   * Called with the trimmed question. A returned promise is what the
   * duplicate-submit guard waits on, so an async caller — every real one —
   * gets the guard for the whole flight rather than for one tick.
   */
  onSubmit: (query: string) => void | Promise<void>;
  /** A submission is in flight. Renders 03 §1.4's pending label. */
  pending?: boolean;
  /**
   * The research service is known to be unreachable (03 §2.2 row 4).
   * Refuses submit and attaches `describeFailure()`'s sentence as the
   * reason. Note this is NOT the same thing as `failure`: this one became
   * true on its own and is ordinary content, that one is something the
   * user just did and is announced.
   */
  unreachable?: ApiFailure | null;
  /** The submission that failed (03 §2.2 row 17). The question is kept. */
  failure?: ApiFailure | null;
  /**
   * H7: where the thread that was created before the submission failed
   * lives. `null` when no thread was created, which is the ordinary case
   * for a follow-up.
   */
  orphanThreadHref?: string | null;
  autoFocus?: boolean;
  className?: string;
}

// ---------------------------------------------------------------------------
// The component.
// ---------------------------------------------------------------------------

export function QueryComposer({
  variant = "landing",
  value,
  defaultValue = "",
  onValueChange,
  onSubmit,
  pending = false,
  unreachable = null,
  failure = null,
  orphanThreadHref = null,
  autoFocus = false,
  className,
}: QueryComposerProps) {
  const base = useId();
  const disclosureId = `${base}-disclosure`;
  const reasonId = `${base}-reason`;

  // Mirrors an uncontrolled value. When the caller controls `value` that
  // wins on every render and the mirror is never read — no second source
  // of truth, the same rule `Textarea` follows.
  const [mirrored, setMirrored] = useState(defaultValue);
  const text = value === undefined ? mirrored : value;

  const length = text.length;
  const over = length > MAX_QUERY_LEN;
  const near = !over && length >= Math.floor(MAX_QUERY_LEN * NEAR_LIMIT_RATIO);
  const blank = text.trim() === "";
  const landing = variant === "landing";

  /**
   * Why submit is refused, or `null` when it is not.
   *
   * Ordered by what a reader can act on: an unreachable service is not
   * something shortening the question fixes, and a too-long question is
   * not something typing more fixes.
   */
  const reason =
    unreachable !== null
      ? describeFailure(unreachable).sentence
      : over
        ? queryOverLimit(length)
        : blank
          ? COMPOSER.emptyQuestion
          : null;
  // Only the unreachable reason is put on screen, and the other two are
  // clipped into the accessible description instead. Both would otherwise
  // be said twice: the over-limit sentence is already `Textarea`'s visible
  // `error`, and the empty-field one is true from the first paint, so
  // printing it would be scolding somebody for not having typed yet. The
  // description still carries them, because a control that refuses has to
  // say why wherever it is met.
  const reasonOnScreen = unreachable !== null;
  const refuses = pending || reason !== null;

  const inFlight = useRef(false);

  const trySubmit = useCallback((): void => {
    // The synchronous half of criterion 5. Two clicks in one tick both run
    // before React has re-rendered, so a guard that read `pending` would
    // let the second one buy a second run.
    if (inFlight.current) return;
    if (pending || unreachable !== null) return;
    const question = text.trim();
    if (question === "" || question.length > MAX_QUERY_LEN) return;
    inFlight.current = true;
    void Promise.resolve(onSubmit(question)).finally(() => {
      inFlight.current = false;
    });
  }, [onSubmit, pending, text, unreachable]);

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>): void => {
      event.preventDefault();
      trySubmit();
    },
    [trySubmit],
  );

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>): void => {
      // The shortcut `QueryForm.tsx:26-32` shipped untested (criterion 4).
      // `Cmd` on macOS, `Ctrl` everywhere else; a bare Enter still inserts
      // a newline, because a research question is often more than a line.
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        trySubmit();
      }
    },
    [trySubmit],
  );

  const described = failure === null ? null : describeFailure(failure);

  return (
    <form
      noValidate
      onSubmit={handleSubmit}
      aria-label={COMPOSER.regionLabel}
      data-variant={variant}
      className={[
        "flex w-full max-w-content flex-col",
        landing ? "gap-6" : "gap-4",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {landing ? (
        <header className="flex flex-col gap-2">
          <p className="text-ui-xs font-medium uppercase tracking-wide text-ink-muted">
            {LANDING.eyebrow}
          </p>
          {/*
            The h1 is the first heading in the document and the first thing
            with a size on the page — 03 §2.2 row 1 measured the baseline's
            at roughly 440 px down a 1200 px viewport and says "the new
            prompt is the first thing on screen" (criterion 3). Nothing but
            the eyebrow precedes it inside the composer, and the composer is
            the first thing in `<main>`.
          */}
          <h1 className="text-balance text-display text-ink">{LANDING.heading}</h1>
        </header>
      ) : null}

      <Textarea
        label={landing ? LANDING.questionLabel : COMPOSER.followUpLabel}
        placeholder={
          landing ? LANDING.questionPlaceholder : COMPOSER.followUpPlaceholder
        }
        rows={landing ? 4 : 3}
        value={text}
        autoFocus={autoFocus}
        onChange={(event) => {
          if (value === undefined) setMirrored(event.target.value);
          onValueChange?.(event.target.value);
        }}
        onKeyDown={handleKeyDown}
        // No `limit` and no `maxLength`: see the header. The counter below
        // is 03 §1.4's, and refusing beats truncating.
        error={over ? queryOverLimit(length) : undefined}
        hint={
          <>
            <VisuallyHidden>{COMPOSER.counterLabel}</VisuallyHidden>
            <span
              data-counter={over ? "over" : near ? "near" : "within"}
              className={
                over
                  ? "tabular-nums text-critical-text"
                  : near
                    ? "tabular-nums text-review-text"
                    : "tabular-nums"
              }
            >
              {queryCounter(length)}
            </span>
          </>
        }
      />

      <div className="flex flex-col gap-3">
        {/*
          Criterion 1: persistent body copy, and the button's immediately
          preceding sibling. Nothing may be inserted between these two —
          the refusal reason below the button is where a new line goes.
        */}
        <p id={disclosureId} className="text-balance text-ui-sm text-ink-muted">
          {LANDING.disclosure}
        </p>
        <Button
          type="submit"
          variant="primary"
          size="lg"
          busy={pending}
          aria-disabled={refuses ? true : undefined}
          aria-describedby={
            reason === null ? disclosureId : `${disclosureId} ${reasonId}`
          }
          className="self-start"
        >
          {pending ? LANDING.submitPending : LANDING.submit}
        </Button>
        {reason === null ? null : (
          <p
            id={reasonId}
            className={
              reasonOnScreen
                ? "text-ui-sm text-critical-text"
                : VISUALLY_HIDDEN_CLASS
            }
          >
            {reason}
          </p>
        )}
      </div>

      {described === null ? null : (
        <StatusBanner
          severity={described.severity}
          word={described.word}
          sentence={described.sentence}
          recovery={described.recovery}
          // 03 §7.3: `role="alert"` is for a failure the user just caused,
          // and `StatusBanner` refuses the role for a severity that is not
          // worth interrupting for. A submission failure is always the
          // former; the severity decides whether it is announced.
          userTriggered={ALERT_SEVERITIES.includes(described.severity)}
          actions={
            orphanThreadHref === null ? undefined : (
              <a
                href={orphanThreadHref}
                className="text-ui-sm font-medium text-ink underline underline-offset-4"
              >
                {COMPOSER.orphanAction}
              </a>
            )
          }
        >
          <p className="text-ui-sm text-ink-muted">{COMPOSER.retained}</p>
          <p className="text-ui-sm text-ink-muted">{COMPOSER.noAutoRetry}</p>
          {orphanThreadHref === null ? null : (
            <p className="text-ui-sm text-ink-muted">{COMPOSER.orphanSentence}</p>
          )}
        </StatusBanner>
      )}

      {landing ? (
        <ol
          aria-label={COMPOSER.processLabel}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-ui-xs text-ink-muted"
        >
          {/*
            The separator is decorative and hidden from the accessibility
            tree, so the strip reads as four items rather than seven.
          */}
          {LANDING.process.map((phrase, index) => (
            <li key={phrase} className="flex items-center gap-3">
              {index === 0 ? null : (
                <span aria-hidden="true" className="text-ink-faint">
                  {"·"}
                </span>
              )}
              {phrase}
            </li>
          ))}
        </ol>
      ) : null}
    </form>
  );
}
