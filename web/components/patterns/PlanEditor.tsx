"use client";

/**
 * PlanEditor — the product's control surface (03 §1.3 P3, §4.6; WO-17).
 *
 * This is the one place a user changes what the run will do, and it is the
 * state the Gate 1 audit scored worst: five axe violations, tied with
 * `failed-partial` and `cancelled` (`docs/revamp/baseline/axe/plan-review.json`).
 * Three of those five are this surface's own — `listitem` (the baseline puts
 * `role="log"` semantics over list rows), `aria-allowed-role`, and
 * `color-contrast` on amber-on-amber chrome — and all three are gone by
 * construction here: real `ul`/`li`, no role overrides, token colours only.
 * The other two, `region` and `landmark-one-main`, are page-level rules that
 * only a document can satisfy; the surface's contribution is to be a NAMED
 * region (`section` + `aria-labelledby`) so that content sits inside a
 * landmark the moment the shell provides `main` (WO-08). The stories render
 * it inside a `main` for exactly that reason.
 *
 * THE FILE IS SPLIT IN TWO, AND THE SPLIT IS A BUDGET DECISION (04 §8.1,
 * R-11). `/`'s first-load JS has 10.9 KB of headroom and `/c/[id]` has
 * 14.6 KB; React Hook Form (~9 KB gzip) plus Zod (~14 KB gzip) do not fit in
 * either. So everything that needs them lives in `PlanEditorFields`, reached
 * only through `React.lazy(() => import("./PlanEditorFields"))`, and this
 * module — which a route renders eagerly — imports neither. `React.lazy`
 * rather than `next/dynamic`: the boundary has to behave identically in
 * Next, in Storybook and under Vitest, and `lazy` + `Suspense` is the same
 * three lines in all three. `web/tests/plan/bundle.test.ts` proves the
 * boundary from the static import graph, and again from the route manifests
 * when a production build is present.
 *
 * NO STRING IS WRITTEN HERE. Every sentence comes from `@/lib/copy/plan` or
 * `@/lib/copy/errors`; `copy/no-inline-text` in `web/eslint.config.mjs`
 * makes that structural for `components/patterns/**`.
 *
 * NO COUNTDOWN (D-010 ruling 13). The status line states the two facts the
 * contract supports — the run is paused and not spending, and it stops on
 * its own if it is not reviewed — and nothing about when. There is no
 * deadline field in the API; `api_hitl_timeout_sec` is server configuration.
 */

import { Suspense, lazy, useEffect, useId, useRef } from "react";

import { Button } from "@/components/primitives/Button";
import { Skeleton } from "@/components/primitives/Skeleton";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { VisuallyHidden } from "@/components/primitives/VisuallyHidden";
import type { ApiFailure, FieldIssue, Plan, ReviewRequest } from "@/lib/api";
import { describeErrorType, describeFailure } from "@/lib/copy/errors";
import { ADD_ARXIV_QUERY, ADD_SUB_QUESTION, PLAN } from "@/lib/copy/plan";
import type { PlanDraft } from "@/lib/plan/schema";

import { ALERT_SEVERITIES, StatusBanner } from "./StatusBanner";

// ---------------------------------------------------------------------------
// Props. Every state in 03 §4.6 is reachable by passing props and nothing
// else (04 §5.1), which is what lets the ten stories exist without MSW.
// ---------------------------------------------------------------------------

/**
 * The surface's states, as the machine's phases reach it.
 *
 * `resolving` is 04 §4.5's async-settle contract: `POST /research/{id}/review`
 * answered 200, which does NOT mean the run resumed
 * (`ReviewResponse.status` is always `pending_review`, `schemas.py:141-160`),
 * so the surface waits for an SSE frame or a poll and says so.
 *
 * `stale` is the 409 (`job_not_awaiting_review`, `routes.py:261-264`). It is
 * not an error to shout about — WO-11's mutation resolves it to
 * `{ kind: "stale" }` rather than throwing — and the surface's response is
 * to refetch and re-render.
 *
 * `resolved` is not in this union on purpose: when the review is over the
 * machine leaves `awaiting_review` and the surface is unmounted by its
 * caller. A component that rendered its own absence would be a tenth state
 * nobody can reach.
 */
export type PlanEditorStatus =
  | "editing"
  | "submitting"
  | "cancelling"
  | "resolving"
  | "stale";

/** Why the review is no longer pending. Both refetch; the words differ. */
export type PlanStaleCause = "resolved_elsewhere" | "hitl_timeout";

export interface PlanEditorProps {
  /** The server's plan — `JobDetail.plan` or a `plan_ready` frame. */
  plan: Plan;
  status?: PlanEditorStatus;
  /**
   * The working copy to open with. Defaults to `plan`. Exists so the
   * `Edited` state is reachable by props rather than by a scripted
   * interaction, and so a caller can restore a draft.
   */
  initialDraft?: PlanDraft;
  /** A 422 that still arrived. Mapped onto rows, never a page-level banner. */
  issues?: readonly FieldIssue[];
  staleCause?: PlanStaleCause;
  /**
   * How `POST /research/{job_id}/review` failed, normalized (WO-S3).
   *
   * **This is the moment the user commits money, and until this prop existed
   * a failure at it rendered NOTHING.** The machine records a failed review
   * without moving its phase — correctly: the server never heard the
   * decision, so the run really is still `pending_review` — and the only
   * banner in the composition above was gated on `phase === "submit_failed"`,
   * a phase a review failure never produces. So a 429, a 500 and a 422 all
   * looked exactly like a missed click.
   *
   * BRANCH ON `kind`, NEVER ON THE SENTENCE. The codes are the stable half
   * of the envelope (`lib/api/errors.ts`, ADR 0064); the wording is not.
   * `describeFailure` is the one accessor that turns a kind into the four
   * strings a banner needs, so a thirteenth variant is a compile error there
   * rather than a blank banner here.
   *
   * THE 409 IS NOT RENDERED FROM HERE. It arrives as `status="stale"`, which
   * already has its own sentence and its own recovery control below; two
   * banners for one click would be the same words twice.
   */
  failure?: ApiFailure | null;
  /**
   * Send the decision. Called with `approve`, `revise` (always with a plan)
   * or `cancel`, and never called at all when the client bounds refuse.
   */
  onReview: (request: ReviewRequest) => void;
  /** Read the run again. Called on entering `stale`, and by the control. */
  onRefetch?: () => void;
  className?: string;
}

/**
 * The half that needs React Hook Form and Zod.
 *
 * This `import()` is the only reference to `PlanEditorFields` anywhere in
 * the product, which is what puts that module — and the two packages it
 * imports — in a chunk of their own rather than in a route's first load.
 */
const PlanEditorFields = lazy(() => import("./PlanEditorFields"));

/**
 * What the lazy half receives.
 *
 * Declared HERE rather than there so that `PlanEditorFields` can import it
 * with `import type` (erased) and neither half has to reach into the other
 * at runtime.
 */
export interface PlanEditorFieldsProps {
  plan: Plan;
  status: PlanEditorStatus;
  initialDraft: PlanDraft | undefined;
  issues: readonly FieldIssue[];
  onReview: (request: ReviewRequest) => void;
  /** Id of the element every arXiv row points `aria-describedby` at. */
  arxivHintId: string;
}

// ---------------------------------------------------------------------------

export function PlanEditor({
  plan,
  status = "editing",
  initialDraft,
  issues = [],
  staleCause = "resolved_elsewhere",
  failure = null,
  onReview,
  onRefetch,
  className,
}: PlanEditorProps) {
  const generated = useId();
  const headingId = `${generated}-heading`;
  const arxivHintId = `${generated}-arxiv-hint`;

  const stale = status === "stale";
  // `JSON.stringify` rather than a join: two lists joined by any separator
  // can collide on a plan that contains that separator, and a colliding key
  // is a working copy that silently fails to reset.
  const planKey = JSON.stringify([plan.sub_questions, plan.search_queries]);

  /**
   * How many rows the form will open with — the fallback's whole input
   * (WO-S2b).
   *
   * `initialDraft` FIRST, because that is what `PlanEditorFields` opens with:
   * `draftToValues(initialDraft ?? planToDraft(plan))`. Reading the plan
   * instead would reserve the server's row count for a restored draft that
   * has a different one, which is the same shift wearing a different coat.
   */
  const fallbackRows: readonly [number, number] = [
    (initialDraft?.subQuestions ?? plan.sub_questions ?? []).length,
    (initialDraft?.searchQueries ?? plan.search_queries ?? []).length,
  ];

  // Criterion 5: a 409 refetches and re-renders rather than dead-ending.
  // Once per entry into the state — `GET /research/{id}` is free and
  // read-only (`routes.py:215-232`), but a loop is still a loop.
  const refetched = useRef(false);
  useEffect(() => {
    if (!stale) {
      refetched.current = false;
      return;
    }
    if (refetched.current) return;
    refetched.current = true;
    onRefetch?.();
  }, [stale, onRefetch]);

  const reviewFailure = failure ?? null;
  /**
   * The review call's own failure, as the four strings a banner renders.
   *
   * TWO KINDS ARE DELIBERATELY NOT HERE. The 409 is `stale`, which has its
   * own sentence and its own recovery control below. And WO-17 criterion 4
   * stands: a 422 that NAMES FIELDS lands on the rows those fields belong to
   * and never in a page-level banner — the baseline mapped nothing and
   * shouted instead. A 422 that names none has no row to land on, and going
   * silent there is the very defect this prop exists to close, so that one
   * is stated here.
   */
  const failed =
    reviewFailure === null ||
    stale ||
    (reviewFailure.kind === "validation" && reviewFailure.fields.length > 0)
      ? null
      : describeFailure(reviewFailure);

  const timedOut = staleCause === "hitl_timeout";
  // The `hitl_timeout` sentence is the dictionary's own mapped copy, not a
  // second wording of it: `api_hitl_timeout_sec` firing is exactly the
  // `error_type` the run ends with (`runner.py:1053-1057`).
  const timeout = describeErrorType("hitl_timeout");

  // The banner carries the sentence in the `stale` state, so the status line
  // steps aside rather than saying the same thing twice.
  const statusLine = stale
    ? null
    : status === "resolving"
      ? PLAN.resolving
      : status === "submitting" || status === "cancelling"
        ? PLAN.sending
        : PLAN.status;

  return (
    <section
      aria-labelledby={headingId}
      data-surface="plan-editor"
      data-status={status}
      // The kind, not the sentence — the same discriminator the banner
      // branches on, so the browser sweep and the axe gate can name the
      // state they are looking at without reading copy. Present for a
      // row-mapped 422 too, which renders no banner by design.
      data-review-failure={reviewFailure === null ? undefined : reviewFailure.kind}
      className={[
        "flex flex-col gap-4 rounded-lg border border-review bg-review-surface p-5",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className="text-ui-lg font-semibold text-ink">
          {PLAN.heading}
        </h2>
        <StatusBadge severity="review" emphasis="surface">
          {PLAN.statusWord}
        </StatusBadge>
      </div>

      <p className="text-ui-sm text-ink">{PLAN.intro}</p>

      {/* Criterion 8. Two true facts, no countdown, and NOT a live region:
          03 §7.3 allows exactly two product-wide and the spine owns the
          `role="status"` one. */}
      {statusLine === null ? null : (
        <p data-testid="plan-status-line" className="text-ui-sm text-ink-muted">
          {statusLine}
        </p>
      )}

      {/* WO-S3 — the failed decision, said out loud.
          `userTriggered` is guarded rather than passed: `role="alert"` is
          reserved for the two failure severities (03 §7.3) and `StatusBanner`
          throws otherwise, and a review that 404s or is aborted describes
          itself as `info`. The guard is the difference between a banner and
          a thrown render. */}
      {failed === null ? null : (
        <StatusBanner
          severity={failed.severity}
          word={failed.word}
          sentence={failed.sentence}
          recovery={failed.recovery}
          userTriggered={ALERT_SEVERITIES.includes(failed.severity)}
        />
      )}

      {stale ? (
        <StatusBanner
          severity="warning"
          userTriggered
          sentence={timedOut ? timeout.sentence : PLAN.conflict}
          recovery={timedOut ? timeout.recovery : PLAN.conflictRecovery}
          actions={
            <Button
              variant="primary"
              size="md"
              data-primary="true"
              onClick={() => onRefetch?.()}
            >
              {PLAN.refresh}
            </Button>
          }
        />
      ) : (
        <Suspense fallback={<PlanEditorFallback rows={fallbackRows} />}>
          {/* Keyed by the plan itself: a `plan_ready` frame can legitimately
              repeat with the SAME plan (`routes.py:456-462`), which must not
              throw away a working copy, but a genuinely different plan is a
              different thing to review and gets a fresh one. */}
          <PlanEditorFields
            key={planKey}
            plan={plan}
            status={status}
            initialDraft={initialDraft}
            issues={issues}
            onReview={onReview}
            arxivHintId={arxivHintId}
          />
        </Suspense>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// The Suspense fallback (WO-S2b).
// ---------------------------------------------------------------------------

/**
 * The chrome of one column, in the order `PlanEditorFields` renders the two.
 *
 * A SECOND COPY OF `PLAN_LIST_SPECS`' COPY, AND THAT IS THE WHOLE POINT OF
 * THE TABLE. `PLAN_LIST_SPECS` lives in `lib/plan/schema.ts`, which is a
 * VALUE import away from `react-hook-form`'s types, 460 lines of resolver and
 * mapping, and — decisively — the module the lazy chunk already pulls. An
 * eager import of it from here would move the whole module into `/c/[id]`'s
 * chunk union to read four strings, and that route had 4,126 B of headroom
 * when this was written. So the strings are taken from the dictionary they
 * both come from, `lib/copy/plan`, which this file already imports; the
 * PAIRING (which sentence belongs to which column) is the only thing stated
 * twice, and `web/tests/plan/fallback.test.tsx` pins it against
 * `PLAN_LIST_SPECS` field by field so the two cannot drift.
 */
const FALLBACK_COLUMNS = [
  {
    key: "subQuestions",
    label: PLAN.subQuestionsLabel,
    hint: PLAN.subQuestionsHint,
    emptyNote: PLAN.noSubQuestions,
    addLabel: ADD_SUB_QUESTION,
  },
  {
    key: "searchQueries",
    label: PLAN.arxivQueriesLabel,
    hint: PLAN.arxivQueriesHint,
    emptyNote: PLAN.noArxivQueries,
    addLabel: ADD_ARXIV_QUERY,
  },
] as const;

/**
 * One row's field box, derived rather than guessed.
 *
 * `Textarea` renders `rows={2}` of `text-ui-base` inside `p-3` with a 1px
 * border on each edge, so the box is two line boxes plus two paddings plus
 * two hairlines — 74px at the current token values, and still right if any
 * of the three tokens moves. The 2px is the two borders and is the only bare
 * number here: it is structural, the way `primitives.css`'s 1px clip rect is,
 * and there is no border-width token to spend instead.
 */
const FALLBACK_FIELD_HEIGHT =
  "calc(2 * var(--text-ui-base-line) + 2 * var(--space-3) + 2px)";

/**
 * What is on screen while the form's chunk arrives — AT THE HEIGHT THE FORM
 * IS ABOUT TO TAKE.
 *
 * WHY THIS IS NOT A SPINNER AND NOT A FOUR-BAR SKELETON. WO-S2 made the plan
 * editor reachable by taking the 14rem cap off the run row at the review
 * pause, and the cap was the thing that had been absorbing this component's
 * arrival: a cold load at 1280x900 mounted a 200px fallback at t≈203ms and
 * replaced it with a 586px form at t≈231ms, pushing the 161px of reading
 * column still visible below it off screen for a cold-load CLS of 0.05113
 * against 04 §8.2's 0.02. Nothing was slow and nothing was wrong with the
 * fallback's looks — it was 386px too short.
 *
 * SO THE SPACE IS RESERVED FROM THE PLAN, WHICH IS ALREADY IN HAND. The row
 * count is `plan.sub_questions.length` and `plan.search_queries.length` (or
 * the restored draft's, which is what `PlanEditorFields` opens with), and
 * every other box is the form's OWN markup with the form's OWN copy —
 * the same `fieldset`/`legend`, the same hint paragraph, the same add
 * control, the same actions row. That is deliberate and it is the only way
 * to be exact: the hint wraps to two lines at one width and one at another,
 * and the actions row wraps onto a second line below `md`, so a reservation
 * computed from token arithmetic would be right at one viewport and wrong at
 * the next. Only the two things whose height is CONSTANT — the row's
 * label/field/counter stack and the remove control — are placeholders, and
 * their heights are token expressions rather than pixel guesses.
 *
 * OVER-RESERVING IS THE SAME DEFECT WITH THE SIGN FLIPPED, which is why the
 * add and action controls are real `Button`s rather than blocks sized by
 * eye: a `Button`'s width is its label plus `CONTROL_PADDING`, and its
 * height follows `--ew-target-size`, which `@media (pointer: coarse)` raises
 * from 40px to 44px. A hardcoded 40px block would under-reserve by 4px per
 * control on every phone.
 *
 * IT IS `aria-hidden`, for the same reason `Skeleton`'s bars are: a
 * placeholder read aloud is a stutter of nothing, and the real controls
 * arrive named a frame later. Every `Button` in here carries `disabled`
 * rather than `aria-disabled`, so nothing inside the hidden subtree is
 * focusable and `aria-hidden-focus` stays clean — and a `getByRole` query
 * for `Approve plan` cannot match two elements while the chunk is in flight.
 */
function PlanEditorFallback({ rows }: { rows: readonly [number, number] }) {
  // Zipped rather than indexed inside the map: `rows[index]` on a tuple is
  // `number | undefined` under `noUncheckedIndexedAccess`, and a `?? 0` there
  // would be a silent zero-row reservation if the pairing ever slipped.
  const columns = FALLBACK_COLUMNS.map((column, index) => ({
    ...column,
    count: index === 0 ? rows[0] : rows[1],
  }));

  return (
    <div data-testid="plan-editor-loading" aria-busy="true">
      <VisuallyHidden>{PLAN.heading}</VisuallyHidden>

      <div aria-hidden="true" className="flex flex-col gap-6">
        <div className="grid gap-6 md:grid-cols-2">
          {columns.map((column) => (
            <fieldset
              key={column.key}
              data-fallback-list={column.key}
              className="flex min-w-0 flex-col gap-3"
            >
              {/* `legend` and not a heading, because a `legend` is laid out
                  OUTSIDE the fieldset's anonymous flex box — it takes its
                  line height and none of the `gap-3`. Reserving it as a
                  flex item instead would over-reserve by exactly one gap. */}
              <legend className="text-ui-sm font-semibold text-ink">
                {column.label}
              </legend>

              <p className="text-ui-xs text-ink-muted">{column.hint}</p>

              {column.count === 0 ? (
                <p className="text-ui-sm text-ink-muted">{column.emptyNote}</p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {Array.from({ length: column.count }, (_, row) => (
                    <li key={row} className="flex items-end gap-2">
                      <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <Skeleton width="12ch" height="var(--text-ui-sm-line)" />
                        <Skeleton height={FALLBACK_FIELD_HEIGHT} />
                        <Skeleton
                          width="6ch"
                          height="var(--text-ui-xs-line)"
                          className="self-end"
                        />
                      </div>
                      {/* The remove control. `ew-target--md` rather than a
                          fixed height so a coarse pointer raises it the same
                          40→44px the real control is raised. */}
                      <div className="ew-skeleton ew-target ew-target--md mb-6 shrink-0" />
                    </li>
                  ))}
                </ul>
              )}

              <div className="flex flex-col gap-1">
                <Button
                  size="md"
                  variant="secondary"
                  className="self-start"
                  disabled
                >
                  {column.addLabel}
                </Button>
              </div>
            </fieldset>
          ))}
        </div>

        <div className="flex flex-col gap-3">
          <p className="text-ui-xs text-ink-muted">{PLAN.cancelHint}</p>

          <div className="flex flex-wrap items-center gap-3">
            {/* `PLAN.approve` and never `PLAN.revise`: the form opens with a
                working copy equal to the plan, so `isEdited` is false on the
                frame the chunk lands and the label the user sees does not
                change under them. The two words are different widths, and at
                412px that difference decides where the row wraps. */}
            <Button variant="primary" size="md" disabled>
              {PLAN.approve}
            </Button>
            <span className="flex-1" />
            <span className="text-ui-xs text-ink-muted">
              {PLAN.cancelConsequence}
            </span>
            <Button
              variant="secondary"
              size="md"
              className="border-critical text-critical-text hover:bg-critical-surface"
              disabled
            >
              {PLAN.cancel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
