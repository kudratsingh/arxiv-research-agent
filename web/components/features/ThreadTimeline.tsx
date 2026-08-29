"use client";

/**
 * ThreadTimeline — the thread, as turns (WO-20; 03 §2.2 rows 5, 6, 7, 21).
 *
 * ONE LOAD PATH (criterion 6). `ConversationThread.tsx` reads
 * `GET /conversations/{id}` twice — once in a `useCallback` at `:38-59` and
 * again, inline and duplicated, in the effect at `:61-93`. Its replacement is
 * `useConversationDetail`, WO-11's query, called exactly once here: the
 * refresh the old `onDone` needed is the same query's cache invalidation, and
 * there is nowhere else in this tree that can issue that read.
 *
 * ONE SOURCE OF TRUTH FOR WHICH RUN IS ON SCREEN (criterion 3, 03 §4.7).
 * The history comes from the query and the current run comes from the job
 * machine, and `selectBriefings` (`lib/report/briefings.ts`) merges them with
 * one rule: **a job id appears at most once**. That is the remedy for the
 * double-render defect WO-18 reproduced in a browser — after the terminal
 * frame the refetched thread contains the finished run AND the current-run
 * panel was still rendering the same job's detail. Here the current run
 * REPLACES the history's copy in place; it never adds one.
 *
 * TURNS COLLAPSE, AND A COLLAPSED TURN IS NOT PARSED (criterion 4). The
 * question row is a `<button aria-expanded>`; the briefing under it renders
 * only when it is open, through `useReportRenderer(expanded)` — which returns
 * `null` while collapsed and therefore never triggers the Markdown pipeline's
 * dynamic `import()`. That is not an optimisation dressed up as a rule: the
 * report bodies arrive in full with the thread (`schemas.py:184-191`), so a
 * ten-turn thread would otherwise parse ten documents to show one. The
 * newest turn opens on arrival, which is `ConversationThread.tsx:44-51`'s
 * behaviour kept.
 *
 * WHAT IT DOES NOT OWN. The run's own surfaces — spine, plan editor,
 * diagnostics — are `ActiveRunPanel`'s and arrive as the `runPanel` slot, so
 * this file has no opinion about the machine beyond "which job, and did it
 * fail". The rail is the layout's. The `?job=` write is the panel's.
 *
 * NO STRING IS TYPED IN THIS FILE — `copy/no-inline-text` covers
 * `components/features/**`.
 */

import { useCallback, useMemo, useState, type ReactNode } from "react";

import { hasActiveRun } from "@/components/features/ActiveRunPanel";
import { QueryComposer } from "@/components/features/QueryComposer";
import { EmptyState } from "@/components/patterns/EmptyState";
import { ExportDisclosure } from "@/components/patterns/ExportDisclosure";
import { MetricsStrip, readRunMetrics } from "@/components/patterns/MetricsStrip";
import { NotFound } from "@/components/patterns/NotFound";
import { ReportReader } from "@/components/patterns/ReportReader";
import { StatusBanner } from "@/components/patterns/StatusBanner";
import { ThreadSkeleton } from "@/components/patterns/ThreadSkeleton";
import { Button } from "@/components/primitives/Button";
import { ApiError, type JobDetail } from "@/lib/api";
import { THREAD, THREAD_RAIL, THREAD_ROW, turnCount, turnLabel } from "@/lib/copy/threads";
import { useJobRun } from "@/lib/job/provider";
import type { JobState } from "@/lib/job/types";
import { useConversationDetail, useReportRenderer } from "@/lib/queries/conversations";
import {
  selectBriefings,
  type Briefing,
  type CurrentRun,
  type HistoryTurn,
} from "@/lib/report/briefings";

import "./workspace.css";

/**
 * The run this browser is watching, in `selectBriefings`' vocabulary.
 *
 * H9: every displayed value comes from `GET /research/{id}` and never from a
 * terminal frame's payload, so an unread detail contributes empty strings and
 * the history copy stands. A failure is reported only when the server said
 * `failed`; `ConversationJobSummary` carries no status, so history can never
 * contribute one.
 */
export function currentRunOf(state: JobState): CurrentRun | null {
  const jobId = state.jobId;
  if (jobId === null) return null;
  const detail: JobDetail | null = state.detail;
  return {
    jobId,
    question: detail?.query ?? "",
    markdown: detail?.result ?? "",
    failure:
      detail !== null && detail.status === "failed"
        ? { errorType: detail.error_type ?? null, error: detail.error ?? null }
        : null,
  };
}

export interface ThreadTimelineProps {
  conversationId: string;
  /** WO-20's `ActiveRunPanel`, pinned under the header (03 §2.2 row 10). */
  runPanel?: ReactNode;
  /** The follow-up composer. Rendered by the route, into WO-08's slot. */
  composer?: ReactNode;
  className?: string;
}

export function ThreadTimeline({
  conversationId,
  runPanel,
  composer,
  className,
}: ThreadTimelineProps) {
  const { detail, turns, query } = useConversationDetail(conversationId);
  const { state } = useJobRun();

  // The newest turn is open; everything else is a question row. Held as the
  // set of ids the reader has TOGGLED, so an arriving turn can become the
  // newest without the reader's own choices being thrown away.
  const [toggled, setToggled] = useState<ReadonlySet<string>>(new Set());
  const toggle = useCallback((jobId: string) => {
    setToggled((previous) => {
      const next = new Set(previous);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }, []);

  const history: HistoryTurn[] = useMemo(
    () =>
      turns.map((turn) => ({
        jobId: turn.jobId,
        ordinal: turn.ordinal,
        question: turn.question,
        markdown: turn.report,
      })),
    [turns],
  );

  // `state` is produced only by the reducer and is a new object exactly when
  // the machine moved, so it is the honest dependency for both memos: they
  // recompute when the run changed and not when the composer below re-rendered.
  const current = useMemo(() => currentRunOf(state), [state]);
  const briefings = useMemo(
    () => selectBriefings(history, current),
    [history, current],
  );

  const newest = briefings.at(-1)?.jobId ?? null;
  const isOpen = useCallback(
    (jobId: string) => (toggled.has(jobId) ? jobId !== newest : jobId === newest),
    [newest, toggled],
  );

  const notFound = query.error instanceof ApiError && query.error.status === 404;

  if (notFound) {
    return (
      <NotFound
        heading={THREAD.notFoundHeading}
        body={THREAD.notFoundBody}
        actionLabel={THREAD.notFoundBackToStart}
        actionHref="/"
        secondaryLabel={THREAD.notFoundBackToList}
        secondaryHref="/"
        className={className}
      />
    );
  }

  // WO-09 criterion 4: `/c/[id]` is dynamic, so the server renders straight
  // through the route's Suspense boundary and THIS is the frame a cold load
  // paints. It reserves the loaded header's own geometry.
  if (detail === undefined) {
    if (query.isPending) return <ThreadSkeleton className={className} />;
    return (
      <div className={["ew-thread", className].filter(Boolean).join(" ")}>
        <header className="ew-thread__header">
          <h1 className="text-ui-xl font-semibold text-ink">
            {THREAD.loadErrorHeading}
          </h1>
        </header>
        <div />
        <div className="ew-thread__timeline">
          <StatusBanner
            severity="critical"
            sentence={THREAD.loadErrorBody}
            recovery={THREAD.loadErrorRecovery}
            actions={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  void query.refetch();
                }}
              >
                {THREAD_RAIL.retry}
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className={["ew-thread", className].filter(Boolean).join(" ")}>
      <header className="ew-thread__header">
        <h1 className="truncate text-ui-xl font-semibold text-ink" title={detail.title}>
          {detail.title}
        </h1>
        <p className="mt-05 text-ui-xs text-ink-muted">
          {turnCount(briefings.length)}
        </p>
      </header>

      {/*
        `data-run` IS THE CLS CONTRACT, NOT DECORATION (criterion 5). With a
        run attached this row is a FIXED box that scrolls inside itself, so a
        checkpoint landing in the spine — or the 3px a scrollbar adds to the
        ledger when the ticks stop fitting, which is what the browser actually
        caught — cannot move the reading column below it. With no run it is
        one sentence and takes one sentence's height, because a 224px empty
        box on the commonest page on this route is 224px the briefing does not
        get. `hasActiveRun` is the panel's own predicate so the two cannot
        disagree about which of those it is.
      */}
      <div
        className="ew-thread__run"
        data-run={hasActiveRun(state) ? "attached" : "none"}
      >
        {runPanel}
      </div>

      {/*
        WO-27 criterion 1/7: THE EMPTY TIMELINE IS FOCUSABLE, AND THE
        POPULATED ONE IS NOT.

        `.ew-thread__timeline` is `overflow-y: auto` (workspace.css), so it is
        a scroll container at every width. With turns in it that is fine — the
        turn buttons are focusable content, and a keyboard user reaches the
        scroll by reaching them. With NO turns its only child is an
        `EmptyState`, which has no focusable descendant, and at 320 CSS px the
        empty state is taller than the row: a region that scrolls and cannot
        be focused, which is SC 2.1.1 and axe's `scrollable-region-focusable`
        at `serious`.

        WO-27's full-matrix sweep is what caught it, and the width is the
        reason nothing else did: WO-22's sweep audits every state at 1440,
        where the empty state fits and the container does not scroll. It fails
        in both themes at 320 and passes at 412.

        The four attributes are `ScrollRegion`'s contract, applied here rather
        than by nesting one: the element that scrolls is this one, and a
        `ScrollRegion` INSIDE it would be a focusable box inside an
        unreachable scroller. `role="region"` rather than a bare `tabindex`
        because a `div[tabindex="0"]` with no role trips `focus-order-semantics`
        (best-practice, in this gate's tag set) and cannot carry `aria-label`
        without tripping `aria-prohibited-attr` either — the stop has to be
        named, and naming it requires the role.
      */}
      <div
        className={
          briefings.length === 0
            ? "ew-thread__timeline ew-focusable"
            : "ew-thread__timeline"
        }
        {...(briefings.length === 0
          ? { role: "region", "aria-label": THREAD.timelineLabel, tabIndex: 0 }
          : {})}
      >
        {briefings.length === 0 ? (
          // `h2`, not `EmptyState`'s default `h3`: the only heading above it
          // is the thread's own `h1`, and on a thread with no run there is no
          // spine to supply the level in between — axe's `heading-order`
          // caught the skip on this exact state.
          <EmptyState
            heading={THREAD.emptyHeading}
            headingLevel={2}
            body={THREAD.emptyBody}
          />
        ) : (
          <ol aria-label={THREAD.timelineLabel} className="list-none">
            {briefings.map((briefing) => (
              <li key={briefing.jobId} className="ew-thread__turn">
                <TimelineTurn
                  briefing={briefing}
                  expanded={isOpen(briefing.jobId)}
                  onToggle={() => toggle(briefing.jobId)}
                  detail={briefing.live ? state.detail : null}
                />
              </li>
            ))}
          </ol>
        )}
      </div>

      {composer}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The follow-up composer.
// ---------------------------------------------------------------------------

/**
 * `QueryComposer`'s follow-up variant, wired to the same machine.
 *
 * It lives here rather than beside `LandingComposer` because the two do
 * different things with the same field: the landing one creates a thread
 * first and hands off with `?job=` (MUST-KEEP 1), this one submits into a
 * thread that already exists and stays where it is. `useJobRun().submit` is
 * still the only path to `POST /research` (R-01, H6) — the machine's
 * submission token and its refusal while `submitting` are the guards, and
 * there is no automatic retry on any path here either.
 */
export function FollowUpComposer({
  conversationId,
  className,
}: {
  conversationId: string;
  className?: string;
}) {
  const { state, submit } = useJobRun();
  const [question, setQuestion] = useState("");

  const onSubmit = useCallback(
    async (query: string): Promise<void> => {
      await submit(query, { conversationId });
    },
    [conversationId, submit],
  );

  return (
    <div className="ew-thread__composer">
      <QueryComposer
        variant="follow-up"
        value={question}
        onValueChange={setQuestion}
        onSubmit={onSubmit}
        pending={state.phase === "submitting"}
        failure={state.phase === "submit_failed" ? state.failure : null}
        className={className}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// One turn.
// ---------------------------------------------------------------------------

interface TimelineTurnProps {
  briefing: Briefing;
  expanded: boolean;
  onToggle: () => void;
  /** `GET /research/{id}`, for the live turn only. The metrics' one source. */
  detail: JobDetail | null;
}

function TimelineTurn({ briefing, expanded, onToggle, detail }: TimelineTurnProps) {
  // The whole of criterion 4: `null` while collapsed, so the Markdown module
  // is never imported and the body is never parsed.
  const renderer = useReportRenderer(expanded);
  const hasBriefing = briefing.markdown.trim() !== "";

  return (
    <>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="ew-focusable ew-target flex w-full items-start gap-3 rounded-lg px-5 py-3 text-left hover:bg-sunken"
      >
        <span className="flex-1 min-w-0">
          <span className="flex items-center gap-2 text-ui-xs font-medium uppercase tracking-wide text-ink-muted">
            {turnLabel(briefing.ordinal)}
            {briefing.live ? (
              <span className="font-medium normal-case text-signature-text">
                {THREAD_ROW.live}
              </span>
            ) : null}
          </span>
          <span className="mt-05 block text-ui-base text-ink">{briefing.question}</span>
        </span>
      </button>

      {expanded ? (
        <div className="ew-thread__body">
          <ReportReader
            markdown={briefing.markdown}
            renderer={renderer}
            failure={briefing.failure}
            actions={
              <ExportDisclosure jobId={briefing.jobId} hasBriefing={hasBriefing} />
            }
            metrics={
              detail === null ? undefined : (
                <MetricsStrip metrics={readRunMetrics(detail)} />
              )
            }
          />
        </div>
      ) : null}
    </>
  );
}
