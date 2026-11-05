"use client";
import { loadContextReadouts } from "./contextModules";

import Link from "next/link";
import { requestPaperNavigation } from "@/lib/workspace/navigation";
import { lazy, Suspense, useRef, useState } from "react";
import {
  displayDate,
  errorMessage,
  readerHref,
  type ProfileData,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { useReadingActions } from "@/lib/workspace/useReadingActions";
import {
  Coverage,
  LoadingState,
  Message,
  ServiceNotice,
  sourceAvailable,
} from "./Common";
import { activeEdition, neighbours, readerTarget, resolveFocus, todayEditionQueue, todayQueue } from "@/lib/workspace/queue";
import { contextHref, useProductContext } from "@/lib/workspace/productContext";
import { setQueryParam, useQueryParam } from "@/lib/workspace/urlState";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";
import { QueueList } from "./Queue";
import { PlayerBar } from "./PlayerBar";
import { ControlBar, SidebarSection, StageHeaderSlot } from "./Slots";

import { FocusPaper } from "./FocusPaper";
import GenerationBoundary from "./GenerationBoundary";
import { Mascot } from "./Mascot";
import { Icon } from "./Icon";
import { useSyntheticPreview } from "./PreviewContext";
import { CompactActivityCard } from "./CompactActivityCard";
import { ContextUnavailable } from "./ContextUnavailable";
const AllocationReceipt = lazy(() => loadContextReadouts().then((module) => ({ default: module.AllocationReceipt })));

export function LiveToday() {
  const [editionOpen, setEditionOpen] = useState(false);
  const { state, setState, error, reload } = useWorkspace();
  const [notice, setNotice] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const pending = useRef(new Map<string, string>());
  const actions = useReadingActions(state, setState, setNotice);
  const focusId = useQueryParam("focus");
  const context = useProductContext();
  const syntheticPreview = useSyntheticPreview();
  if (!state) return <div className="ws-today-state"><Mascot mood={error ? "alert" : "busy"} size={72} /><LoadingState error={error} retry={() => void reload()} /></div>;
  if (state.context?.unavailable_reason) return <div className="ws-today"><ContextUnavailable reason={state.context.unavailable_reason} context={context} /></div>;
  const actionBusy = actions.busy || savingProfile || refreshing;
  const latest = activeEdition(state);
  const ordered = todayEditionQueue(state);
  const visible = todayQueue(state);
  const focused = resolveFocus(visible, latest?.work_ids ?? [], focusId);
  const position = neighbours(visible, focused?.work_id ?? null);
  const pinnedVersion = focused ? latest?.work_versions[focused.work_id] : undefined;
  const target = focused ? readerTarget(focused, pinnedVersion) : null;
  const href = focused && target
    ? contextHref(readerHref(focused, target.version, target.anchor, undefined, contextHref(`/workspace/today?focus=${encodeURIComponent(focused.work_id)}`, context)), context)
    : "";
  const sources = latest?.coverage ?? state.sources;
  const available = sources.filter(sourceAvailable).length;
  const sourceState = available < sources.length
    ? sources.some((source) => source.status === "failed" || source.status === "error") ? "failed" : "limited"
    : sources.some((source) => source.status === "partial" || source.receipt.truncated === true) ? "limited" : "ok";

  function choose(id: string) {
    requestPaperNavigation();
    setQueryParam("focus", id);
    Array.from(document.querySelectorAll<HTMLElement>(".ws-queue-row[data-work-id]"))
      .find((row) => row.dataset.workId === id)?.scrollIntoView?.({ block: "nearest" });
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
  async function saveProfile(patch: Partial<Pick<ProfileData, "minutes" | "pinned_entry_id">>, message: string, edition = false) {
    if (!state) return;
    setSavingProfile(true);
    try {
      await (await loadContextReadouts()).saveTodayProfile(state, patch, pending.current, edition);
      await reload();
      setNotice(message);
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setSavingProfile(false);
    }
  }
  function pin(entryId: string | null) {
    return saveProfile({ pinned_entry_id: entryId }, entryId
      ? "Pinned with its source version and passage attached."
      : "Unpinned. Latest activity is shown again.");
  }
  async function refresh() {
    setRefreshing(true);
    setNotice(
      "Checking bounded public metadata. No model is running.",
    );
    try {
      await (await loadContextReadouts()).checkTodaySources();
      await reload();
      setNotice(
        "Source check completed. Coverage shows unavailable or limited sources.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setRefreshing(false);
    }
  }
  function minutes(value: 5 | 15 | 45) {
    return saveProfile({ minutes: value }, `${value}-minute preference saved; a new bounded edition was prepared from stored metadata.`, true);
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
      <div className="daily-intro ws-today-intro"><div><h1>What changed.</h1><p>{context.mode === "research" ? "Stored sources for this project's question." : "A finite reading window across your interests."}</p></div></div>
      {activity && <CompactActivityCard activity={activity} work={activityWork} context={context}
        pinned={!!activity.entry_id && state.profile.data.pinned_entry_id === activity.entry_id}
        busy={actionBusy} onPin={(entryId) => void pin(entryId)} />}
      <ServiceNotice error={error} />
      <section aria-labelledby="live-changes" className="ws-focus-stage">
        <div className="daily-section-heading ws-focus-section-heading"><h2 id="live-changes">Changes to consider</h2>
          <span>{visible.length} items · {latest?.status.replaceAll("_", " ") ?? "No edition yet"}</span>
        </div>
        {latest && ordered.length < latest.work_ids.length && <p className="workspace-version-notice">
          Some source versions retained by this edition are unavailable in the loaded view. Newer versions were not substituted.
        </p>}
        {!latest ? <div className="daily-empty ws-empty"><Mascot mood="sleepy" size={72} /><div>
          <h2>Make your first bounded check.</h2><p>Check sources to prepare an edition. Fictional items remain in preview.</p>
        </div></div> : !focused ? <div className="daily-empty ws-empty"><Mascot mood="sleepy" size={72} /><div>
          <h2>{state.sources.some((source) => !sourceAvailable(source)) ? "No matches in available checks." : "No matches in this reading window."}</h2>
          <p>Review coverage, adjust interests, or search stored metadata in Radar.</p>
        </div></div> : <FocusPaper position={{ index: position.index, count: position.count }} item={focused} versionId={pinnedVersion} href={href} />}
        {latest && <p className="daily-muted ws-shortlist-end">End of this shortlist. Source check, profile revision {latest.profile_revision}, and cutoff are retained.</p>}
      </section>
      {latest && <details className="workspace-edition-details" onToggle={(event) => setEditionOpen(event.currentTarget.open)}><summary>Edition details · {latest.work_ids.length} items · about {latest.minutes} minutes</summary>
        {editionOpen && <Suspense fallback={<p className="daily-muted">Opening the retained allocation receipt…</p>}><AllocationReceipt allocation={latest.allocation} minutes={latest.minutes} /></Suspense>}
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
        {syntheticPreview && <p id="ws-preview-check-boundary" className="daily-muted">Source checks are disabled in synthetic preview. Examples prove neither freshness nor coverage.</p>}
        <Link className="daily-link" href={contextHref("/workspace/radar", context)} prefetch={false}>Search all stored items →</Link>
      </div></Coverage></SidebarSection>
      {context.mode === "learn" && <SidebarSection label="Your question"><div className="ws-side-heading"><h2>Saved organizing question · optional</h2></div>
        <p className="ws-question">{state.profile.data.research_question || "Add an optional question in Interests."}</p>
        <Link href={contextHref("/workspace/interests", context)} prefetch={false} className="daily-link">Edit your interests ↗</Link>
      </SidebarSection>}
      <SidebarSection label="Generation and saved work"><GenerationBoundary />
        <div className="ws-sidebar-links"><Link href={contextHref("/workspace/library", context)} className="daily-link" prefetch={false}>Your saved work →</Link>
          <Link href={contextHref("/workspace/review", context)} className="daily-link" prefetch={false}>Review candidate usefulness →</Link>
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
