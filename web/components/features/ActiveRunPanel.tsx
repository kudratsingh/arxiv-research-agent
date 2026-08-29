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
 * editor at the review pause, one banner for the two states the spine cannot
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
import { PlanEditor, type PlanEditorStatus } from "@/components/patterns/PlanEditor";
import { StatusBanner } from "@/components/patterns/StatusBanner";
import { TraceSpine } from "@/components/patterns/TraceSpine";
import type { ReviewRequest } from "@/lib/api";
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

  const reviewing = state.phase === "awaiting_review" || state.phase === "resolving";
  const plan = state.plan;

  /**
   * The two states the spine cannot carry on its own.
   *
   * `unavailable` is H8's 404 — the sentence is the dictionary's and the
   * recovery is the composer that is already on screen, named rather than
   * offered as a button that would start a billable run on one click.
   * A failed submission is the other: it is something the user just did, so
   * it is announced; everything else that merely became true is not.
   */
  const failed = state.phase === "submit_failed" && state.failure !== null;
  const described = failed && state.failure !== null ? describeFailure(state.failure) : null;

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
          userTriggered
        />
      )}

      {reviewing && plan !== null ? (
        <PlanEditor
          plan={plan}
          status={planStatusOf(state)}
          onReview={onReview}
          onRefetch={onRefetch}
        />
      ) : null}

      {/*
        The disclosure is collapsed by default (04 §9.2), so it costs one row
        — and it is where the frame log lives, which is where the "updated
        41 s ago" figure this panel does not print can still be read.
      */}
      {idle ? null : <Diagnostics records={records} showVitals={perf} />}
    </section>
  );
}
