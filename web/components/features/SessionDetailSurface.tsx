"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  GuidedSessionUnavailable,
  GuidedSessionView,
  readSessionTurn,
} from "@/components/patterns/GuidedSessionView";
import {
  ApiError,
  getLearnSession,
  submitLearnSessionTurn,
  type JobDetail,
  type SessionDetail,
} from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";
import { sessionAsJobDetail } from "@/lib/job/session";
import { useJobStream } from "@/lib/job/useJobStream";
import { useLearnPath } from "@/lib/queries/learn";
import { useReportRenderer } from "@/lib/queries/conversations";

export function SessionDetailSurface({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [response, setResponse] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const firstRead = useRef(true);
  const [restored, setRestored] = useState(false);
  const pendingTurn = useRef<number | null>(null);
  const turnInFlight = useRef(false);

  const readSessionAsJob = useCallback(async (id: string): Promise<JobDetail> => {
    const detail = await getLearnSession(id);
    const turn = readSessionTurn(detail.turn);
    if (firstRead.current) {
      setRestored(detail.transcript.length > 0 || (turn?.turnNumber ?? 0) > 1);
      firstRead.current = false;
    }
    if (
      pendingTurn.current !== null &&
      (detail.status !== "awaiting_learner" ||
        turn === null ||
        turn.turnNumber !== pendingTurn.current)
    ) {
      pendingTurn.current = null;
      turnInFlight.current = false;
      setSubmitting(false);
    }
    setSession(detail);
    return sessionAsJobDetail(detail);
  }, []);

  const client = useMemo(() => ({ getJob: readSessionAsJob }), [readSessionAsJob]);
  const stream = useJobStream({ client });
  const { attach, refresh, reset, state } = stream;

  useEffect(() => {
    attach(sessionId);
  }, [attach, sessionId]);

  const newestFrame = state.frames.at(-1);
  useEffect(() => {
    if (newestFrame?.name === "turn_ready") void refresh("refresh");
  }, [newestFrame?.receivedAt, newestFrame?.name, refresh]);

  const path = useLearnPath(session?.path_id ?? null);
  const renderer = useReportRenderer(Boolean(session));
  const entry =
    path.data?.entries.find(
      (candidate) => candidate.resource_id === session?.resource_id
    ) ?? null;

  async function submitTurn(endSession: boolean) {
    if (
      session === null ||
      turnInFlight.current ||
      submitting ||
      response.trim() === ""
    )
      return;
    turnInFlight.current = true;
    setSubmitError(null);
    setSubmitting(true);
    pendingTurn.current = readSessionTurn(session.turn)?.turnNumber ?? null;
    try {
      await submitLearnSessionTurn(session.session_id, {
        message: response.trim(),
        end_session: endSession,
      });
      setResponse("");
    } catch (error) {
      pendingTurn.current = null;
      turnInFlight.current = false;
      setSubmitting(false);
      setSubmitError(
        error instanceof ApiError ? error.failure.message : LEARN.failedBody
      );
    }
  }

  if (state.phase === "unavailable") {
    return (
      <GuidedSessionUnavailable
        onRetry={() => {
          reset();
          firstRead.current = true;
          attach(sessionId);
        }}
      />
    );
  }

  if (session === null) {
    return (
      <div aria-busy="true" className="mx-auto w-full max-w-content px-6 py-10">
        {LEARN.sessionLoading}
      </div>
    );
  }

  return (
    <GuidedSessionView
      session={session}
      entry={entry}
      renderer={renderer}
      machinePhase={state.phase}
      connection={state.connection}
      response={response}
      submitting={submitting}
      restored={restored}
      submitError={submitError}
      onResponseChange={setResponse}
      onSubmit={(endSession) => void submitTurn(endSession)}
    />
  );
}
