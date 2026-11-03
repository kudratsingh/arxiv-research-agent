"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import {
  displayDate,
  errorMessage,
  requestId,
  workspaceRequest,
  type WorkspaceState,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { useReadingActions } from "@/lib/workspace/useReadingActions";
import {
  Coverage,
  GenerationBoundary,
  LoadingState,
  Message,
  ServiceNotice,
  sourceAvailable,
} from "./Common";
import { WorkCard } from "./WorkCard";
import { ActivityCard } from "./ActivityCard";
import { AllocationReceipt } from "./AllocationReceipt";

export function LiveToday() {
  const { state, setState, error, reload } = useWorkspace();
  const [notice, setNotice] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const pending = useRef(new Map<string, string>());
  const actions = useReadingActions(state, setState, setNotice);
  if (!state) return <LoadingState error={error} retry={() => void reload()} />;
  const latest = state.editions[0];
  const ordered = latest
    ? latest.work_ids.flatMap((id) => {
        const work = state.works.find((item) => item.work_id === id);
        if (!work) return [];
        const version = latest.work_versions[id];
        if (!version) return [work];
        const retained = work.versions.find(
          (material) => material.version_id === version,
        );
        if (!retained) return [];
        return [
          {
            ...work,
            version_id: version,
            version_label: retained.version_label,
            title: retained.title || work.title,
            url: retained.url || work.url,
            authors: retained.authors.length ? retained.authors : work.authors,
            abstract: retained.abstract,
            access_state: retained.access_state,
            content_hash: retained.content_hash,
          },
        ];
      })
    : [];
  const visible = ordered.filter(
    (item) =>
      !["dismissed", "archived"].includes(item.reading.status) &&
      (item.reading.status !== "snoozed" ||
        !item.reading.snoozed_until ||
        new Date(item.reading.snoozed_until) <= new Date()),
  );
  const activity = state.latest_activity;
  const activityWork = activity
    ? state.works.find((item) => item.work_id === activity.work_id)
    : undefined;
  async function pin(entryId: string | null) {
    if (!state) return;
    const input = {
      revision: state.profile.revision,
      data: { ...state.profile.data, pinned_entry_id: entryId },
    };
    const fingerprint = JSON.stringify(input),
      id = pending.current.get(fingerprint) ?? requestId();
    pending.current.set(fingerprint, id);
    setSavingProfile(true);
    try {
      await workspaceRequest("profile", { ...input, request_id: id });
      await reload();
      setNotice(
        entryId
          ? "Saved item pinned. Its source version and passage stay attached."
          : "Saved item unpinned. The latest activity is shown again.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setSavingProfile(false);
    }
  }
  async function refresh() {
    setRefreshing(true);
    setNotice(
      "Checking a bounded set of public source metadata. No model is running.",
    );
    try {
      setState(
        await workspaceRequest<WorkspaceState>("refresh", { source_ids: [] }),
      );
      setNotice(
        "Source check completed. Inspect coverage for unavailable or limited sources.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setRefreshing(false);
    }
  }
  async function minutes(value: 5 | 15 | 45) {
    if (!state) return;
    const input = {
      revision: state.profile.revision,
      data: { ...state.profile.data, minutes: value },
    };
    const fingerprint = JSON.stringify(input),
      id = pending.current.get(fingerprint) ?? requestId();
    pending.current.set(fingerprint, id);
    setSavingProfile(true);
    try {
      await workspaceRequest("profile", { ...input, request_id: id });
      await workspaceRequest("edition", {});
      await reload();
      setNotice(
        `${value}-minute preference saved; a new bounded edition was prepared from stored metadata.`,
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setSavingProfile(false);
    }
  }
  return (
    <>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">
          {latest
            ? `Edition ${displayDate(latest.created_at)}`
            : "Your first local briefing"}
        </span>
        <Link
          href="/workspace/interests"
          prefetch={false}
          className="daily-link"
        >
          Edit your interests ↗
        </Link>
      </div>
      <div className="daily-intro">
        <div>
          <h1>
            What changed.
            <br />
            <em>What to investigate.</em>
          </h1>
          <p>
            A finite briefing from real source metadata, with room to follow a
            question.
          </p>
        </div>
        <fieldset className="daily-time">
          <legend>Time for reading</legend>
          {([5, 15, 45] as const).map((value) => (
            <button
              key={value}
              disabled={savingProfile}
              aria-pressed={state.profile.data.minutes === value}
              onClick={() => void minutes(value)}
            >
              {value} min
            </button>
          ))}
        </fieldset>
      </div>
      <ServiceNotice error={error} />
      <div className="workspace-toolbar">
        <button
          className="daily-button"
          disabled={refreshing}
          onClick={() => void refresh()}
        >
          {refreshing ? "Checking sources…" : "Check sources now"}
        </button>
        <Link className="daily-link" href="/workspace/radar" prefetch={false}>
          Search all stored items →
        </Link>
        {actions.hasUndo && (
          <button
            className="daily-secondary"
            disabled={actions.busy}
            onClick={() => void actions.undo()}
          >
            Undo last change
          </button>
        )}
        <Message>{notice}</Message>
      </div>
      <div className="daily-columns">
        <div>
          <Coverage sources={latest?.coverage ?? state.sources} />
          {latest && (
            <AllocationReceipt
              allocation={latest.allocation}
              minutes={latest.minutes}
            />
          )}
          <section aria-labelledby="live-changes">
            <div className="daily-section-heading">
              <h2 id="live-changes">Changes to consider</h2>
              <span>
                {visible.length} items ·{" "}
                {latest?.status.replaceAll("_", " ") ?? "No edition yet"}
              </span>
            </div>
            {latest && ordered.length < latest.work_ids.length && (
              <p className="workspace-version-notice">
                Some source versions retained by this edition are unavailable in
                the loaded view. Their newer versions have not been substituted.
              </p>
            )}
            {!latest ? (
              <div className="daily-empty">
                <h2>Make your first bounded check.</h2>
                <p>
                  Check sources to prepare a real edition. Fictional preview
                  items stay in their own preview.
                </p>
              </div>
            ) : visible.length === 0 ? (
              <div className="daily-empty">
                <h2>
                  {state.sources.some((source) => !sourceAvailable(source))
                    ? "No matching items in the available checks."
                    : "Nothing new matched this reading window."}
                </h2>
                <p>
                  Review the source coverage above, adjust your interests, or
                  inspect all stored metadata in Radar.
                </p>
              </div>
            ) : (
              visible.map((item, index) => (
                <WorkCard
                  key={item.work_id}
                  item={item}
                  versionId={latest?.work_versions[item.work_id]}
                  returnTo="/workspace/today"
                  lead={index === 0}
                  busy={actions.busy}
                  status={(work, status) => void actions.status(work, status)}
                />
              ))
            )}
            {latest && (
              <p className="daily-muted workspace-toolbar">
                That’s this edition’s shortlist. Its source check, profile
                revision {latest.profile_revision}, and cutoff are retained.
              </p>
            )}
          </section>
        </div>
        <aside className="daily-context" aria-label="Continue your research">
          <span className="daily-eyebrow">Keep the thread</span>
          <h2>
            A question worth
            <br />
            coming back to.
          </h2>
          <div className="daily-thread">
            <div>
              <span>Your current question</span>
              <p>
                {state.profile.data.research_question ||
                  "Add your current research question in Interests."}
              </p>
            </div>
          </div>
          <ActivityCard
            activity={activity}
            work={activityWork}
            pinned={Boolean(
              activity?.entry_id &&
              state.profile.data.pinned_entry_id === activity.entry_id,
            )}
            busy={savingProfile}
            onPin={(entryId) => void pin(entryId)}
          />
          <GenerationBoundary />
          <Link
            href="/workspace/library"
            className="daily-link"
            prefetch={false}
          >
            Your saved work →
          </Link>
          <p className="workspace-review-link">
            <Link
              href="/workspace/review"
              className="daily-link"
              prefetch={false}
            >
              Review candidate usefulness →
            </Link>
          </p>
        </aside>
      </div>
    </>
  );
}
