"use client";
import { useRef, useState } from "react";
import {
  displayDate,
  errorMessage,
  requestId,
  workspaceRequest,
  type ScheduleData,
  type WorkspaceState,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { LoadingState, Message, ServiceNotice } from "./Common";

export function LiveOperations() {
  const { state, setState, error, reload } = useWorkspace();
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<ScheduleData | null>(null);
  const attempts = useRef(new Map<string, string>());
  if (!state) return <LoadingState error={error} retry={() => void reload()} />;
  const schedule = draft ?? state.schedule;
  async function check(sourceId: string) {
    setBusy(true);
    setNotice("Checking only this approved source. No model is running.");
    try {
      setState(
        await workspaceRequest<WorkspaceState>("refresh", {
          source_ids: [sourceId],
        }),
      );
      setNotice(
        "Source check finished. Inspect its receipt for coverage, limits and any failure.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!state) return;
    const input = {
      revision: state.schedule.revision,
      data: {
        enabled: false,
        timezone: schedule.timezone,
        local_time: schedule.local_time,
      },
    };
    const fingerprint = JSON.stringify(input),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    setBusy(true);
    try {
      await workspaceRequest("schedule", { ...input, request_id: id });
      await reload();
      setDraft(null);
      setNotice(
        "Schedule preferences saved. Recurring checks remain disabled until you confirm the time.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">
          Sources & checks · local operations
        </span>
        <span className="daily-muted">No external delivery</span>
      </div>
      <div className="daily-intro">
        <div>
          <h1>
            Know what was checked.
            <br />
            <em>And what wasn’t.</em>
          </h1>
          <p>
            Actual source receipts, durable task state and local schedule
            preferences.
          </p>
        </div>
      </div>
      <ServiceNotice error={error} />
      <Message>{notice}</Message>
      <section aria-labelledby="source-health">
        <div className="daily-section-heading">
          <h2 id="source-health">Source health and coverage</h2>
          <span>{state.sources.length} configured sources</span>
        </div>
        <div className="workspace-source-list">
          {state.sources.map((source) => (
            <article className="workspace-source" key={source.source_id}>
              <header>
                <h2>{source.name}</h2>
                <span className="daily-eyebrow">
                  {source.status.replaceAll("_", " ")}
                </span>
              </header>
              <dl>
                <dt>Last success</dt>
                <dd>
                  {source.last_success_at
                    ? displayDate(source.last_success_at)
                    : "No successful check recorded"}
                </dd>
                <dt>Scope</dt>
                <dd>
                  Bounded public metadata; at most 25 items per check, with a
                  seven-day default candidate window.
                </dd>
              </dl>
              <details>
                <summary className="daily-link">
                  Inspect this check’s receipt
                </summary>
                <pre
                  className="workspace-receipt"
                  tabIndex={0}
                  role="region"
                  aria-label={`${source.name} check receipt`}
                >
                  {JSON.stringify(source.receipt, null, 2)}
                </pre>
              </details>
              <button
                className="daily-secondary"
                disabled={busy}
                onClick={() => void check(source.source_id)}
              >
                Check {source.name} now
              </button>
            </article>
          ))}
        </div>
      </section>
      <section
        className="workspace-form-stack workspace-import"
        aria-labelledby="schedule-title"
      >
        <span className="daily-eyebrow">
          Local schedule · awaiting your time
        </span>
        <h2 id="schedule-title">A regular check, when you choose.</h2>
        <p className="daily-muted">
          Your computer must be running. After a missed window, the worker
          prepares one bounded catch-up edition rather than claiming delivery
          while it was asleep. No email, push, SMS or chat destination is
          enabled.
        </p>
        <div className="workspace-alert">
          <strong>
            {state.schedule.enabled
              ? "A recurring schedule is enabled"
              : "Recurring schedule disabled"}
          </strong>
          <p>
            Next check:{" "}
            {state.schedule.next_check
              ? displayDate(state.schedule.next_check)
              : "None scheduled"}
          </p>
        </div>
        <form onSubmit={(event) => void save(event)}>
          <label>
            IANA timezone
            <input
              value={schedule.timezone}
              onChange={(event) =>
                setDraft({
                  enabled: false,
                  local_time: schedule.local_time,
                  timezone: event.target.value,
                })
              }
              placeholder="America/Los_Angeles"
              required
            />
          </label>
          <label>
            Proposed local check time
            <input
              type="time"
              value={schedule.local_time}
              onChange={(event) =>
                setDraft({
                  enabled: false,
                  timezone: schedule.timezone,
                  local_time: event.target.value,
                })
              }
              required
            />
          </label>
          <button className="daily-secondary" disabled={busy}>
            {state.schedule.enabled
              ? "Pause schedule and save preferences"
              : "Save preferences · keep schedule disabled"}
          </button>
        </form>
      </section>
      <section className="workspace-import" aria-labelledby="queued-work">
        <div className="daily-section-heading">
          <h2 id="queued-work">Durable local work</h2>
          <span>{state.tasks.length} recorded tasks</span>
        </div>
        {state.tasks.length === 0 ? (
          <p className="daily-muted">
            No queued or recorded scheduled tasks. Manual source checks remain
            available.
          </p>
        ) : (
          state.tasks.map((task, index) => (
            <article
              className="workspace-inline-note"
              key={String(task.id ?? index)}
            >
              <span className="daily-eyebrow">
                {String(task.kind ?? "metadata check")} ·{" "}
                {String(task.status ?? task.state ?? "unknown")}
              </span>
              <p>
                Due:{" "}
                {displayDate(
                  typeof task.due_at === "string" ? task.due_at : null,
                )}
              </p>
              {task.reason != null && <p>{String(task.reason)}</p>}
              <p className="workspace-note-context">
                Attempt{" "}
                {String(task.attempts ?? task.attempt ?? "not recorded")}
              </p>
            </article>
          ))
        )}
      </section>
      <div className="daily-generation">
        <h3>Generation stays separate.</h3>
        <p>
          Metadata checks do not construct model clients. Grounded summaries and
          deep dives remain blocked until a separate source-and-budget approval
          is recorded.
        </p>
      </div>
    </>
  );
}
