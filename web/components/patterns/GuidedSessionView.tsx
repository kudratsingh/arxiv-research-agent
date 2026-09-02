"use client";

import Link from "next/link";
import type { FormEvent } from "react";

import { Button } from "@/components/primitives/Button";
import { Textarea } from "@/components/primitives/Textarea";
import type { LearnEntry, SessionDetail } from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";
import type { ConnectionPhase, JobPhase } from "@/lib/job/types";
import type { ReportRenderer } from "@/lib/report/renderer";

import { ReportReader } from "./ReportReader";
import "./guided-session.css";

export interface SessionTurnView {
  turnNumber: number;
  kind: string;
  prompt: string;
  feedback: string;
}

export function readSessionTurn(
  value: SessionDetail["turn"]
): SessionTurnView | null {
  if (value === null) return null;
  const turnNumber = value.turn_number;
  const kind = value.kind;
  const prompt = value.prompt;
  const feedback = value.feedback;
  if (
    typeof turnNumber !== "number" ||
    typeof kind !== "string" ||
    typeof prompt !== "string"
  ) {
    return null;
  }
  return {
    turnNumber,
    kind,
    prompt,
    feedback: typeof feedback === "string" ? feedback : "",
  };
}

export interface GuidedSessionViewProps {
  session: SessionDetail;
  entry: LearnEntry | null;
  renderer: ReportRenderer | null;
  machinePhase: JobPhase;
  connection: ConnectionPhase;
  response: string;
  submitting?: boolean;
  restored?: boolean;
  submitError?: string | null;
  onResponseChange: (value: string) => void;
  onSubmit: (endSession: boolean) => void;
}

function CostCap({ session }: { session: SessionDetail }) {
  if (session.cost_cap_status === "") return null;
  return (
    <aside className="session-fact session-fact--review" data-session-cap="">
      <h2>{LEARN.costCapHeading}</h2>
      <p>
        {session.cost_cap_status === "refused"
          ? LEARN.costCapRefused
          : LEARN.costCapDegraded}
      </p>
      {session.cost_cap_message ? <p>{session.cost_cap_message}</p> : null}
    </aside>
  );
}

function AssessmentFact({ session }: { session: SessionDetail }) {
  if (session.assessment_status === "unassessed") {
    return (
      <aside className="session-fact" data-session-unassessed="">
        <h2>{LEARN.unassessedHeading}</h2>
        <p>{LEARN.unassessedBody}</p>
      </aside>
    );
  }
  if (session.assessment_status === "recorded_ungraded") {
    return <p className="session-evidence-line">{LEARN.recordedUngraded}</p>;
  }
  return null;
}

export function GuidedSessionView({
  session,
  entry,
  renderer,
  machinePhase,
  connection,
  response,
  submitting = false,
  restored = false,
  submitError = null,
  onResponseChange,
  onSubmit,
}: GuidedSessionViewProps) {
  const turn = readSessionTurn(session.turn);
  const awaiting =
    session.status === "awaiting_learner" && machinePhase === "awaiting_learner";
  const settled = ["succeeded", "failed", "cancelled"].includes(session.status);
  const working = !settled && !awaiting;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const endSession =
      submitter instanceof HTMLButtonElement && submitter.value === "end";
    onSubmit(endSession);
  }

  return (
    <article className="session-page" data-session-state={session.status}>
      <header className="session-header">
        <Link href={`/learn/paths/${encodeURIComponent(session.path_id)}`}>
          {LEARN.backToPath}
        </Link>
        <p className="font-mono">{LEARN.sessionEyebrow}</p>
        <h1 className="font-report">{session.title}</h1>
        {entry ? (
          <a href={entry.canonical_url} target="_blank" rel="noreferrer">
            {LEARN.openPaper}
          </a>
        ) : null}
      </header>

      {connection === "reconnecting" ? (
        <p className="session-connection">
          {LEARN.reconnecting}
        </p>
      ) : null}
      {restored ? <p className="session-restored">{LEARN.resumed}</p> : null}
      {session.transcript_status === "unavailable" ? (
        <p className="session-fact" data-transcript-unavailable="">
          {LEARN.transcriptUnavailable}
        </p>
      ) : null}

      <CostCap session={session} />

      <div className="session-workbench">
        <section className="session-document" aria-labelledby="session-passage-title">
          <div className="session-section-label">
            <span className="font-mono">{LEARN.sourceLabel}</span>
            <h2 id="session-passage-title" className="font-report">
              {LEARN.passageLabel}
            </h2>
          </div>
          {entry?.briefing_markdown ? (
            <ReportReader markdown={entry.briefing_markdown} renderer={renderer} />
          ) : (
            <p className="session-empty">{LEARN.passageEmpty}</p>
          )}
        </section>

        <section className="session-margin" aria-labelledby="session-margin-title">
          <div className="session-section-label">
            <span className="font-mono">{LEARN.conversationLabel}</span>
            <h2 id="session-margin-title" className="font-report">
              {LEARN.conversationLabel}
            </h2>
          </div>

          <ol className="session-annotations">
            {session.transcript.map((item, index) => (
              <li key={`${item.role}-${index}`} data-role={item.role}>
                <span className="font-mono">
                  {item.role === "tutor" ? LEARN.tutorLabel : LEARN.learnerLabel}
                </span>
                <p>{item.text}</p>
              </li>
            ))}
          </ol>

          {awaiting && turn ? (
            <div className="session-current-turn" data-current-turn={turn.kind}>
              <p className="font-mono">{LEARN.currentTurnLabel}</p>
              {turn.feedback ? <p>{turn.feedback}</p> : null}
              <h3 className="font-report">{turn.prompt}</h3>
              <form onSubmit={submit}>
                <Textarea
                  label={LEARN.replyLabel}
                  hint={LEARN.replyHint}
                  value={response}
                  limit={2_000}
                  rows={6}
                  required
                  disabled={submitting}
                  error={submitError}
                  onChange={(event) => onResponseChange(event.target.value)}
                />
                <div className="session-actions">
                  <Button
                    type="submit"
                    variant="primary"
                    busy={submitting}
                    disabled={response.trim() === "" || response.length > 2_000}
                  >
                    {submitting ? LEARN.submittingTurn : LEARN.submitTurn}
                  </Button>
                  <Button
                    type="submit"
                    value="end"
                    busy={submitting}
                    disabled={response.trim() === "" || response.length > 2_000}
                  >
                    {LEARN.endSession}
                  </Button>
                </div>
              </form>
            </div>
          ) : awaiting ? (
            <p className="session-fact">{LEARN.emptyTurn}</p>
          ) : null}

          {working ? (
            <div className="session-working" aria-live="polite">
              <h3 className="font-report">{LEARN.workingHeading}</h3>
              <p>{LEARN.workingBody}</p>
            </div>
          ) : null}

          {session.status === "succeeded" ? (
            <div className="session-close" data-session-complete="">
              <h2 className="font-report">{LEARN.completeHeading}</h2>
              <p>{LEARN.completeAdvance}</p>
              {session.result ? <p>{session.result}</p> : null}
              <AssessmentFact session={session} />
            </div>
          ) : null}

          {session.status === "failed" || session.status === "cancelled" ? (
            <div className="session-close session-close--failed">
              <h2 className="font-report">{LEARN.failedHeading}</h2>
              <p>{LEARN.failedBody}</p>
            </div>
          ) : null}
        </section>
      </div>
    </article>
  );
}

export function GuidedSessionUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="session-unavailable">
      <h1 className="font-report">{LEARN.sessionUnavailableHeading}</h1>
      <p>{LEARN.sessionUnavailableBody}</p>
      <Button onClick={onRetry}>{LEARN.retrySession}</Button>
    </section>
  );
}
