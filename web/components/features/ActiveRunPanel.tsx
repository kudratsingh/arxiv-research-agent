"use client";

/**
 * ActiveRunPanel — the run that is on screen, and the URL that names it
 * (WO-20; 03 §2.2 rows 10–16, 25; 04 §2.2's `/c/[id]` variant table).
 *
 * IT IS THE ONLY PLACE `?job=` IS WRITTEN, AND IT WRITES IT AT MOST ONCE PER
 * JOB ID (criterion 1). `ConversationThread.tsx:132-142` is reproduced here
 * ref for ref, because the ref is the whole behaviour: without it a URL that
 * *loses* `?job=` — the rail's own link back to this thread — would be
 * rewritten from stale machine state and the parameter could never be got rid
 * of. `router.replace`, not `push`: the pre-attach URL is not a back-button
 * stop. A job that is already the route's `adoptJobId` is never written back,
 * so a reload writes nothing at all.
 *
 * THE MACHINE IS THE SINGLE SOURCE OF TRUTH (criterion 3). This panel reads
 * `useJobRun()` and so does `ThreadTimeline`; there is one provider per route
 * instance and its `state.jobId` is the only answer either of them has to
 * "which run is on screen". Nothing here keeps a second copy, and
 * `web/tests/features/routeComposition.test.tsx` asserts the two surfaces
 * cannot name different runs.
 *
 * WHAT IT RENDERS, AND WHAT IT DELIBERATELY DOES NOT. The spine, the plan
 * editor at the review pause, one banner for the states the spine cannot
 * carry on its own, and the diagnostics disclosure. It does NOT render the
 * briefing: 03 §4.7's remedy for the double-render defect is that the current
 * run and the thread history share one source of truth, and that source is
 * `selectBriefings` inside `ThreadTimeline`. A report rendered here as well
 * would be the defect with a new file name.
 *
 * WHY THERE IS NO AGING CLOCK. 03 §5.4's status line ends "updated 41 s ago",
 * which needs a timer that re-renders this panel every second — in the grid
 * row directly above the reading column, whose text can rewrap as the number
 * grows. Criterion 5 is "incoming events never move the report column, CLS
 * 0.000 during a live run", and a clock that ticks during exactly that run is
 * the one thing that would break it. So `spineInputs` is called with
 * `now = null`, the sentence is absent rather than wrong, and the frame times
 * it was derived from are one disclosure away in `Diagnostics` — the same
 * RC-16 shape the raw error strings use.
 *
 * NO STRING IS TYPED IN THIS FILE. `copy/no-inline-text` covers
 * `components/features/**`; every word comes from `lib/copy/threads`,
 * `lib/copy/trace` or `lib/copy/errors`.
 */

import { useCallback, useEffect, useRef } from "react";

import { Diagnostics } from "@/components/patterns/Diagnostics";
import {
  PlanEditor,
  type PlanEditorStatus,
  type PlanStaleCause,
} from "@/components/patterns/PlanEditor";
import { ALERT_SEVERITIES, StatusBanner } from "@/components/patterns/StatusBanner";
import { TraceSpine } from "@/components/patterns/TraceSpine";
import type { ApiFailure, FieldIssue, ReviewRequest } from "@/lib/api";
import { describeFailure, rawErrorEvidence } from "@/lib/copy/errors";
import { THREAD } from "@/lib/copy/threads";
import {
  useDebugPerf,
  useDiagnosticsRecorder,
  useDiagnosticsRecords,
  useWebVitals,
} from "@/lib/diagnostics/useDiagnostics";
import { useJobRun } from "@/lib/job/provider";
import type { JobState } from "@/lib/job/types";
import { spineInputs } from "@/lib/spine/adapter";

/** The href `?job=` is written to. One definition, so it cannot drift. */
export function runHref(conversationId: string, jobId: string): string {
  return `/c/${encodeURIComponent(conversationId)}?job=${encodeURIComponent(jobId)}`;
}

/**
 * The plan editor's status, read off the machine.
 *
 * `resolving` is 04 §4.5's async settle: `POST /research/{id}/review`
 * answered, and a 200 does not mean the run resumed. `stale` is the 409 the
 * reducer turns back into an attach.
 */
export function planStatusOf(state: JobState): PlanEditorStatus {
  if (state.phase === "resolving") return "resolving";
  if (state.review?.inFlight === true) {
    return state.review.action === "cancel" ? "cancelling" : "submitting";
  }
  if (state.failureSource === "review" && state.failure?.kind === "conflict") {
    return "stale";
  }
  return "editing";
}

/**
 * The review call's own failure, or `null` when the last one was something
 * else (WO-S3).
 *
 * **`failureSource` is the question that has an answer; the phase is not.**
 * `POST /research/{job_id}/review` failing does not move the machine, and it
 * should not: the server never heard the decision, so the run really is
 * still parked at `pending_review` and the user's edits are still the thing
 * on screen. That is why `machine.ts`'s `review_rejected` cell writes
 * `failure` and leaves `phase` alone — and it is why a banner gated on
 * `phase === "submit_failed"` rendered NOTHING for a rate limit, a 500 or a
 * 422 on the one click that commits money. Pressing `Approve plan` and a
 * missed click looked identical.
 */
export function reviewFailureOf(state: JobState): ApiFailure | null {
  return state.failureSource === "review" ? state.failure : null;
}

/** A stable empty list, so an unchanged `issues` prop keeps its identity. */
const NO_ISSUES: readonly FieldIssue[] = [];

/**
 * The 422's fields, on their way to the editor's rows.
 *
 * A validation failure is the one review failure the user can repair in
 * place, so it reaches the rows that carry it (`PlanEditorFields` criterion
 * 4) rather than stopping at the banner. Every other kind maps to nothing
 * here: a rate limit belongs to no field.
 */
export function reviewIssuesOf(state: JobState): readonly FieldIssue[] {
  const failure = reviewFailureOf(state);
  return failure !== null && failure.kind === "validation"
    ? failure.fields
    : NO_ISSUES;
}

/**
 * Why the review is over, for the `stale` banner's two wordings.
 *
 * Derived from the REFETCHED run and never from the 409's own text:
 * `job_not_awaiting_review (status=failed)` says the review is over but not
 * why, and only `error_type` says that.
 */
export function staleCauseOf(state: JobState): PlanStaleCause {
  return state.detail?.error_type === "hitl_timeout"
    ? "hitl_timeout"
    : "resolved_elsewhere";
}

/**
 * Is there a run on this page at all? §4 row B is the `false` case.
 *
 * Exported because `ThreadTimeline` needs the same answer for the row it
 * gives this panel: with a run attached that row is a FIXED box, so nothing
 * inside it can move the reading column (criterion 5); with no run it is one
 * sentence and takes one sentence's height. Two files asking the question two
 * ways is how those two answers drift apart.
 */
export function hasActiveRun(state: JobState): boolean {
  return !(state.jobId === null && state.phase === "idle");
}

/**
 * Is the run PAUSED ON THE READER — the review pause, with an editor in the
 * row (WO-S2)?
 *
 * Exported for the same reason `hasActiveRun` is, and it answers a different
 * question the row above the reading column has to be able to ask. The
 * bounded-box contract that row carries exists for one thing: a checkpoint
 * arriving in the spine during a live run must not move the briefing
 * (criterion 5, `workspace.css`). At the review pause nothing is arriving —
 * the run is stopped and spending nothing until this reader answers — so the
 * bound buys no CLS there, and what it costs is the only control that can
 * restart the run. Measured on `17d2916`: 1,545px of the editor hidden inside
 * a 224px box at 412px wide, `Approve plan` at y=1785 on a 915px viewport, and
 * no scrollbar to say so.
 *
 * IT IS THE MOUNT CONDITION ITSELF, NOT A COPY OF IT. The panel below derives
 * its `plan` from this function, so "the editor is in the row" and "the row is
 * exempt from the bound" are one expression evaluated once. That matters most
 * for the third disjunct: WO-S3 added `planStatus === "stale"` — the 409,
 * where `machine.ts` sends the machine back through `attaching` and the phase
 * alone would take the editor away at exactly the moment the user needs it,
 * their edits still in it. A row that reported `attached` there would clip the
 * conflict banner and the approve control back out of reach, which is this
 * defect returning through the other lane's door.
 */
export function isReviewPause(state: JobState): boolean {
  const reviewing =
    state.phase === "awaiting_review" ||
    state.phase === "resolving" ||
    planStatusOf(state) === "stale";
  return reviewing && state.plan !== null;
}

export interface ActiveRunPanelProps {
  /** The thread this run belongs to. Half of the `?job=` href. */
  conversationId: string;
  /**
   * The route's own `?job=`, straight from `useSearchParams`. The panel
   * never writes a value back that the URL already carries.
   */
  adoptJobId: string | null;
  /**
   * 03 §5.3: the legend is shown once per session and lives behind a
   * disclosure thereafter. The composing route owns that decision.
   */
  legend?: "open" | "disclosure" | "none";
  /** Overrides `router.replace`. Present so criterion 1 is assertable. */
  onSyncUrl?: (href: string) => void;
  className?: string;
}

export function ActiveRunPanel({
  conversationId,
  adoptJobId,
  legend = "disclosure",
  onSyncUrl,
  className,
}: ActiveRunPanelProps) {
  const { state, review, refresh, subscribe, getSnapshot } = useJobRun();

  // -- The diagnostics ring (WO-16). Subscribed outside the render path. ----
  useDiagnosticsRecorder({ subscribe, getSnapshot });
  const records = useDiagnosticsRecords();
  const perf = useDebugPerf();
  useWebVitals(perf);

  // -- Criterion 1: `?job=`, at most once per job id. ----------------------
  const syncedJobRef = useRef<string | null>(null);
  const jobId = state.jobId;
  useEffect(() => {
    if (jobId === null || jobId === adoptJobId) return;
    if (syncedJobRef.current === jobId) return;
    syncedJobRef.current = jobId;
    onSyncUrl?.(runHref(conversationId, jobId));
  }, [adoptJobId, conversationId, jobId, onSyncUrl]);

  const onReview = useCallback(
    (request: ReviewRequest) => {
      void review(request.action, request.plan ?? undefined);
    },
    [review],
  );

  const onRefetch = useCallback(() => {
    void refresh();
  }, [refresh]);

  const planStatus = planStatusOf(state);
  /**
   * THE EDITOR STAYS ON SCREEN THROUGH A FAILED REVIEW (WO-S3).
   *
   * Two phases are obvious. The third is `planStatus === "stale"`, the 409:
   * `machine.ts` sends the machine back through `attaching` to re-read the
   * run, and reading the phase alone therefore took the editor away at
   * exactly the moment the user needed it — their edits are in it, and the
   * conflict banner it carries is the only answer to "why did my click do
   * nothing". `planStatusOf` was already computing `stale`; nothing rendered
   * it, because nothing kept the surface mounted long enough to.
   *
   * WO-S2 MOVED THE THREE DISJUNCTS INTO `isReviewPause`, unchanged, because
   * `ThreadTimeline` needs the same answer for the row's geometry: the row
   * that holds this editor is exempt from the 14rem CLS bound for exactly as
   * long as this editor is in it. Written twice, the two would drift — and
   * the state they would drift on is the 409 above, where the drift costs
   * the user the banner that explains their click.
   */
  const plan = isReviewPause(state) ? state.plan : null;
  const reviewFailure = reviewFailureOf(state);

  /**
   * The failures this panel announces ITSELF.
   *
   * `unavailable` is H8's 404 — the sentence is the dictionary's and the
   * recovery is the composer that is already on screen, named rather than
   * offered as a button that would start a billable run on one click.
   * A failed submission is the second: it is something the user just did, so
   * it is announced; everything else that merely became true is not.
   *
   * A failed REVIEW is the third, and only when the plan editor is not on
   * screen to state it — the editor takes `failure` and says it beside the
   * control that was pressed, and two banners for one click would be the
   * same words twice. This branch is the backstop for the case where the
   * plan is gone but the failure is not, so that no failed approval can
   * render nothing at all.
   */
  const announced =
    state.phase === "submit_failed"
      ? state.failure
      : plan === null
        ? reviewFailure
        : null;
  const described = announced === null ? null : describeFailure(announced);

  /**
   * §4 row B — `/c/[id]` with no `?job=`.
   *
   * ONE SENTENCE, NOT AN INERT SPINE, AND THAT IS A MEASUREMENT. `TraceSpine`
   * renders its four segment names with nothing observed when `inputs` is
   * `null`, on the reasonable ground that "the shape the user is about to
   * meet is already on screen". Composed into this row it costs 428px of a
   * 669px surface — measured in the browser on this branch — and squeezed the
   * reading column to ZERO on a thread that has briefings to read and no run
   * at all. The surface is a fixed-height box (`.ew-shell__surface`), so that
   * height comes out of the thing the user came for. So the absence of a run
   * is stated in the words the dictionary has for it and the column is given
   * back. The spine returns the moment there is a run to trace.
   */
  const idle = state.jobId === null && state.phase === "idle";

  return (
    <section
      aria-label={THREAD.runLabel}
      data-surface="active-run"
      data-run-phase={state.phase}
      data-run-job={state.jobId ?? ""}
      className={["flex flex-col gap-3", className].filter(Boolean).join(" ")}
    >
      {idle ? (
        <p className="text-ui-sm text-ink-muted">{THREAD.noRun}</p>
      ) : (
        <TraceSpine inputs={spineInputs(state)} legend={legend} />
      )}

      {/*
        THE RECOVERY ONLY, BECAUSE THE SPINE ALREADY SAID THE SENTENCE. 03
        §2.2 row 16 asks for `UNAVAILABLE_COPY` plus "ask the question again,
        explicitly labelled as starting a new billable run". The spine's own
        status line is that sentence (`lib/spine/state.ts`), and a banner
        repeating it puts the same words on screen twice — which the first
        browser run of this panel showed as a strict-mode locator violation
        before it showed as a design problem. So this is the half the spine
        does not carry, and the composer that does the asking is directly
        below it.
      */}
      {state.phase === "unavailable" ? (
        <p className="text-ui-sm text-ink-muted">{THREAD.askAgain}</p>
      ) : null}

      {described === null ? null : (
        <StatusBanner
          severity={described.severity}
          word={described.word}
          sentence={described.sentence}
          recovery={described.recovery}
          evidence={rawErrorEvidence(null, state.failureMessage)}
          // Guarded rather than passed: `role="alert"` is reserved for the
          // two failure severities (03 §7.3) and `StatusBanner` throws
          // otherwise. A cancelled submission and a 404 on a review both
          // describe themselves as `info`, so an unguarded `userTriggered`
          // is a thrown render rather than a banner.
          userTriggered={ALERT_SEVERITIES.includes(described.severity)}
        />
      )}

      {plan === null ? null : (
        <PlanEditor
          plan={plan}
          status={planStatus}
          failure={reviewFailure}
          issues={reviewIssuesOf(state)}
          staleCause={staleCauseOf(state)}
          onReview={onReview}
          onRefetch={onRefetch}
        />
      )}

      {/*
        The disclosure is collapsed by default (04 §9.2), so it costs one row
        — and it is where the frame log lives, which is where the "updated
        41 s ago" figure this panel does not print can still be read.
      */}
      {idle ? null : <Diagnostics records={records} showVitals={perf} />}
    </section>
  );
}
