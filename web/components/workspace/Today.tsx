"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import {
  displayDate,
  errorMessage,
  requestId,
  readerHref,
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
import { neighbours, readerTarget, resolveFocus, todayEditionQueue, todayQueue } from "@/lib/workspace/queue";
import { setQueryParam, useQueryParam } from "@/lib/workspace/urlState";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";
import { FocusPaper } from "./FocusPaper";
import { QueueList } from "./Queue";
import { PlayerBar } from "./PlayerBar";
import { ControlBar, SidebarSection, StageHeaderSlot } from "./Slots";
import { Mascot } from "./Mascot";
import { Icon } from "./Icon";
import { useSyntheticPreview } from "./PreviewContext";
import { ActivityCard } from "./ActivityCard";
import { AllocationReceipt } from "./AllocationReceipt";

export function LiveToday() {
  const { state, setState, error, reload } = useWorkspace();
  const [notice, setNotice] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const pending = useRef(new Map<string, string>());
  const actions = useReadingActions(state, setState, setNotice);
  const focusId = useQueryParam("focus");
  const syntheticPreview = useSyntheticPreview();
  if (!state) return <div className="ws-today-state"><Mascot mood={error ? "alert" : "busy"} size={72} /><LoadingState error={error} retry={() => void reload()} /></div>;
  const actionBusy = actions.busy || savingProfile || refreshing;
  const latest = state.editions[0];
  const ordered = todayEditionQueue(state);
  const visible = todayQueue(state);
  const focused = resolveFocus(visible, latest?.work_ids ?? [], focusId);
  const position = neighbours(visible, focused?.work_id ?? null);
  const pinnedVersion = focused ? latest?.work_versions[focused.work_id] : undefined;
  const target = focused ? readerTarget(focused, pinnedVersion) : null;
  const href = focused && target
    ? readerHref(focused, target.version, target.anchor, undefined, `/workspace/today?focus=${encodeURIComponent(focused.work_id)}`)
    : "";
  const sources = latest?.coverage ?? state.sources;
  const available = sources.filter(sourceAvailable).length;
  const sourceState = available < sources.length
    ? sources.some((source) => source.status === "failed" || source.status === "error") ? "failed" : "limited"
    : sources.some((source) => source.status === "partial" || source.receipt.truncated === true) ? "limited" : "ok";

  function choose(id: string) {
    setQueryParam("focus", id);
    Array.from(document.querySelectorAll<HTMLElement>(".ws-queue-row[data-work-id]"))
      .find((row) => row.dataset.workId === id)?.scrollIntoView?.({ block: "nearest" });
    const stage = document.getElementById("main");
    if (stage) { stage.scrollTop = 0; stage.scrollIntoView?.({ block: "start" }); }
    if (document.querySelector('.workspace-app [role="dialog"][aria-modal="true"]')) dispatchWorkspaceCommand("escape");
  }
  async function undo() {
    const restoredId = actions.undoWorkId;
    if (await actions.undo()) {
      if (restoredId) choose(restoredId);
    }
  }
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
  const undoButton = actions.hasUndo && <button type="button" className="ws-player-action" data-command="undo" aria-keyshortcuts="U"
    disabled={actionBusy} onClick={() => void undo()}><Icon name="undo" />Undo last change<kbd aria-hidden="true">U</kbd></button>;
  return (
    <div className="workspace-today ws-today">
      <StageHeaderSlot position={focused ? { n: position.index + 1, N: position.count } : undefined}
        sources={sources.length ? { ok: available, total: sources.length, worst: sourceState } : undefined}
        action={focused && <Link href={href} prefetch={false} className="ws-read-action">
          <Icon name="open" />Read &amp; investigate<kbd aria-hidden="true">O</kbd>
        </Link>} />
      <div className="daily-page-meta"><span className="daily-eyebrow">{latest ? `Edition ${displayDate(latest.created_at)}` : "Your first local briefing"}</span></div>
      <div className="daily-intro ws-today-intro"><div><h1>What changed.</h1><p>A short reading list for your next question.</p></div></div>
      <ActivityCard compact activity={activity} work={activityWork}
        pinned={Boolean(activity?.entry_id && state.profile.data.pinned_entry_id === activity.entry_id)}
        busy={actionBusy} onPin={(entryId) => void pin(entryId)} />
      <ServiceNotice error={error} />
      <section aria-labelledby="live-changes" className="ws-focus-stage">
        <div className="daily-section-heading ws-focus-section-heading"><h2 id="live-changes">Changes to consider</h2>
          <span>{visible.length} items · {latest?.status.replaceAll("_", " ") ?? "No edition yet"}</span>
        </div>
        {latest && ordered.length < latest.work_ids.length && <p className="workspace-version-notice">
          Some source versions retained by this edition are unavailable in the loaded view. Their newer versions have not been substituted.
        </p>}
        {!latest ? <div className="daily-empty ws-empty"><Mascot mood="sleepy" size={72} /><div>
          <h2>Make your first bounded check.</h2><p>Check sources to prepare a real edition. Fictional preview items stay in their own preview.</p>
        </div></div> : !focused ? <div className="daily-empty ws-empty"><Mascot mood="sleepy" size={72} /><div>
          <h2>{state.sources.some((source) => !sourceAvailable(source)) ? "No matching items in the available checks." : "Nothing new matched this reading window."}</h2>
          <p>Review the source coverage above, adjust your interests, or inspect all stored metadata in Radar.</p>
        </div></div> : <FocusPaper key={`${focused.work_id}:${target?.version}`} item={focused} versionId={pinnedVersion} href={href} />}
        {latest && <p className="daily-muted ws-shortlist-end">That’s this edition’s shortlist. Its source check, profile revision {latest.profile_revision}, and cutoff are retained.</p>}
      </section>
      {latest && <details className="workspace-edition-details"><summary>Edition details · {latest.work_ids.length} items · about {latest.minutes} minutes</summary>
        <AllocationReceipt allocation={latest.allocation} minutes={latest.minutes} />
      </details>}
      <SidebarSection label="Up next"><div className="ws-side-heading"><h2>Up next</h2><span>{visible.length} items</span></div>
        <QueueList items={visible} focusId={focused?.work_id ?? null} versionIds={latest?.work_versions} onSelect={choose} />
      </SidebarSection>
      <SidebarSection label="Reading time"><fieldset className="daily-time ws-reading-time"><legend>Time for reading</legend>
        {([5, 15, 45] as const).map((value) => <button type="button" key={value} data-command={`time-${value}`} disabled={actionBusy}
          aria-pressed={state.profile.data.minutes === value} onClick={() => void minutes(value)}>{value} min</button>)}
      </fieldset></SidebarSection>
      <SidebarSection label="Source checks"><Coverage sources={sources}><div className="workspace-toolbar">
        <button type="button" className="daily-button" data-command="check-sources" disabled={actionBusy || syntheticPreview}
          aria-describedby={syntheticPreview ? "ws-preview-check-boundary" : undefined} onClick={() => void refresh()}>
          {refreshing ? "Checking sources…" : "Check sources now"}
        </button>
        {syntheticPreview && <p id="ws-preview-check-boundary" className="daily-muted">Live source checks are disabled in this synthetic design preview. These examples do not establish source freshness or coverage.</p>}
        <Link className="daily-link" href="/workspace/radar" prefetch={false}>Search all stored items →</Link>
      </div></Coverage></SidebarSection>
      <SidebarSection label="Your question"><div className="ws-side-heading"><h2>Your current question</h2></div>
        <p className="ws-question">{state.profile.data.research_question || "Add your current research question in Interests."}</p>
        <Link href="/workspace/interests" prefetch={false} className="daily-link">Edit your interests ↗</Link>
      </SidebarSection>
      <SidebarSection label="Generation and saved work"><GenerationBoundary />
        <div className="ws-sidebar-links"><Link href="/workspace/library" className="daily-link" prefetch={false}>Your saved work →</Link>
          <Link href="/workspace/review" className="daily-link" prefetch={false}>Review candidate usefulness →</Link>
        </div>
      </SidebarSection>
      <ControlBar>
        {focused && <PlayerBar item={focused} versionId={pinnedVersion} href={href} index={position.index} count={position.count} busy={actionBusy}
          onPrevious={position.previous ? () => choose(position.previous!.work_id) : undefined}
          onNext={position.next ? () => choose(position.next!.work_id) : undefined}>
          <div className="ws-player-actions" role="group" aria-label="Paper actions">
            <button type="button" className="ws-player-action" data-command="save" aria-keyshortcuts="S" disabled={actionBusy}
              aria-label={`${focused.reading.status === "saved" ? "Unsave" : "Save"} ${focused.title}`} aria-pressed={focused.reading.status === "saved"}
              onClick={() => void actions.status(focused, focused.reading.status === "saved" ? "unread" : "saved")}>
              <Icon name={focused.reading.status === "saved" ? "saved" : "save"} />{focused.reading.status === "saved" ? "Unsave" : "Save"}<kbd aria-hidden="true">S</kbd>
            </button>
            <button type="button" className="ws-player-action" data-command="dismiss" aria-keyshortcuts="D" disabled={actionBusy}
              aria-label={`Dismiss ${focused.title}`} onClick={() => void actions.status(focused, "dismissed")}><Icon name="dismiss" />Dismiss<kbd aria-hidden="true">D</kbd></button>
            <button type="button" className="ws-player-action" data-command="snooze" aria-keyshortcuts="Z" disabled={actionBusy}
              aria-label={`Snooze one day ${focused.title}`} onClick={() => void actions.status(focused, "snoozed")}><Icon name="snooze" />Snooze one day<kbd aria-hidden="true">Z</kbd></button>
            {undoButton}
          </div>
        </PlayerBar>}
        {!focused && undoButton}
        <Message>{notice}</Message>
      </ControlBar>
    </div>
  );
}
