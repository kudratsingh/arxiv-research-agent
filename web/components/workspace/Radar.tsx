"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  errorMessage,
  readerHref,
  workspaceRequest,
  type WorkItem,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { useReadingActions } from "@/lib/workspace/useReadingActions";
import { LoadingState, Message, ServiceNotice } from "./Common";
import { neighbours, readerTarget, resolveFocus } from "@/lib/workspace/queue";
import { setQueryParam, useQueryParam } from "@/lib/workspace/urlState";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";
import { FocusPaper } from "./FocusPaper";
import { PlayerBar } from "./PlayerBar";
import { QueueList } from "./Queue";
import { ControlBar, SidebarSection, StageHeaderSlot } from "./Slots";
import { Mascot } from "./Mascot";
import { useSyntheticPreview } from "./PreviewContext";

interface WorkPage {
  items: WorkItem[];
  next_cursor: string | null;
  as_of: string;
}
interface Filters {
  q: string;
  source_id: string;
  access_state: string;
  status: string;
  days: string;
}
const EMPTY_FILTERS: Filters = {
  q: "",
  source_id: "",
  access_state: "",
  status: "",
  days: "7",
};
function fromURL() {
  const params = new URLSearchParams(window.location.search);
  return {
    filters: Object.fromEntries(
      Object.entries(EMPTY_FILTERS).map(([key, value]) => [
        key,
        params.get(key) ?? value,
      ]),
    ) as unknown as Filters,
    cursor: params.get("cursor"),
    asOf: params.get("as_of"),
  };
}

export function LiveRadar() {
  const { state, setState, error, reload } = useWorkspace();
  const synthetic = useSyntheticPreview();
  const focusId = useQueryParam("focus");
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState<ReturnType<typeof fromURL> | null>(null);
  const appliedKey = useRef("");
  const [page, setPage] = useState<WorkPage | null>(null);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  // Items may observe a work added after the initial workspace snapshot.
  const actionState = state && page ? { ...state, works: [...state.works,
    ...page.items.filter((item) => !state.works.some((work) => work.work_id === item.work_id))] } : state;
  const actions = useReadingActions(actionState, setState, setNotice);
  useEffect(() => {
    const loadURL = () => {
      const value = fromURL();
      const key = JSON.stringify(value);
      // Browser history may change only focus: the stored page remains valid.
      if (key === appliedKey.current) return;
      appliedKey.current = key;
      setFilters(value.filters);
      setApplied(value);
      setPage(null);
      setNotice("");
      setLoading(true);
    };
    loadURL();
    window.addEventListener("popstate", loadURL);
    return () => window.removeEventListener("popstate", loadURL);
  }, []);
  useEffect(() => {
    if (!applied) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ ...applied.filters, limit: "20" });
    if (applied.cursor) params.set("cursor", applied.cursor);
    if (applied.asOf) params.set("as_of", applied.asOf);
    workspaceRequest<WorkPage>(`items?${params}`, undefined, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        // Pin the server snapshot for Reader return and pagination without refetching.
        setQueryParam("as_of", result.as_of);
        appliedKey.current = JSON.stringify({ ...applied, asOf: result.as_of });
        setPage(result);
        setNotice("");
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) { setPage(null); setNotice(errorMessage(failure)); }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [applied]);
  if (!state) return <LoadingState error={error} retry={() => void reload()} />;
  const items = page?.items.map((item) => {
    const current = state.works.find((work) => work.work_id === item.work_id);
    return current ? { ...item, reading: current.reading, entries: current.entries } : item;
  }) ?? [];
  const focused = resolveFocus(items, items.map((item) => item.work_id), focusId);
  const position = neighbours(items, focused?.work_id ?? null);
  const target = focused ? readerTarget(focused) : null;
  const retained = focused && target && (focused.versions.length
    ? focused.versions.some((version) => version.version_id === target.version)
    : focused.version_id === target.version);
  const returnTo = typeof window === "undefined" ? "/workspace/radar" : `${window.location.pathname}${window.location.search}`;
  const href = focused && target ? readerHref(focused, target.version, target.anchor, undefined, returnTo) : "";
  function closeDrawer() {
    if (document.querySelector('.workspace-app [role="dialog"][aria-modal="true"]')) dispatchWorkspaceCommand("escape");
  }
  function choose(id: string) {
    if (actions.busy) return;
    setQueryParam("focus", id);
    Array.from(document.querySelectorAll<HTMLElement>(".ws-queue-row")).find((row) => row.dataset.workId === id)?.scrollIntoView?.({ block: "nearest" });
    document.querySelector(".ws-stage-scroll")?.scrollTo?.({ top: 0 });
    closeDrawer();
  }
  function navigate(next: ReturnType<typeof fromURL>) {
    const params = new URLSearchParams(next.filters as unknown as Record<string, string>);
    if (next.cursor) params.set("cursor", next.cursor);
    if (next.asOf) params.set("as_of", next.asOf);
    window.history.pushState(null, "", `/workspace/radar?${params}`);
    setQueryParam("focus", null);
    appliedKey.current = JSON.stringify(next);
    setFilters(next.filters);
    setPage(null);
    setNotice("");
    setLoading(true);
    setApplied({ ...next });
    closeDrawer();
  }
  async function undo() {
    const id = actions.undoWorkId;
    if (await actions.undo() && id && items.some((item) => item.work_id === id)) choose(id);
  }
  const undoButton = actions.hasUndo && <button type="button" className="ws-player-action" data-command="undo" aria-keyshortcuts="U" disabled={actions.busy || loading} onClick={() => void undo()}>Undo last change</button>;
  return <div className="ws-radar">
    <StageHeaderSlot position={focused ? { n: position.index + 1, N: position.count } : undefined} />
    <div className="daily-page-meta"><span className="daily-eyebrow">{synthetic ? "Radar · synthetic sample metadata" : "Radar · actual stored metadata"}</span><span className="daily-muted">No generated summaries</span></div>
    <div className="daily-intro ws-radar-intro"><div><h1>A wider view.<br /><em>Your terms, your pace.</em></h1><p>{synthetic ? "Explore synthetic sample source records, including items outside today’s sample shortlist." : "Search the sources you actually checked, including items outside today’s shortlist."}</p></div></div>
    <ServiceNotice error={error} />
    <SidebarSection label="Radar filters"><h2>Filters</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (loading || actions.busy) return;
          navigate({ filters, cursor: null, asOf: null });
        }}
      >
        <div className="workspace-controls">
          <label>
            Search titles and abstracts
            <input
              type="search"
              value={filters.q}
              maxLength={200}
              onChange={(event) =>
                setFilters({ ...filters, q: event.target.value })
              }
            />
          </label>
          <label>
            Source
            <select
              value={filters.source_id}
              onChange={(event) =>
                setFilters({ ...filters, source_id: event.target.value })
              }
            >
              <option value="">All checked sources</option>
              {state.sources.map((source) => (
                <option key={source.source_id} value={source.source_id}>
                  {source.name}
                </option>
              ))}
              <option value="manual">Manually saved</option>
            </select>
          </label>
          <label>
            Date window
            <select
              value={filters.days}
              onChange={(event) =>
                setFilters({ ...filters, days: event.target.value })
              }
            >
              <option value="1">Past day</option>
              <option value="7">Past seven days</option>
              <option value="30">Past thirty days</option>
              <option value="0">All stored dates</option>
            </select>
          </label>
          <label>
            Available material
            <select
              value={filters.access_state}
              onChange={(event) =>
                setFilters({ ...filters, access_state: event.target.value })
              }
            >
              <option value="">Any access state</option>
              <option value="abstract">Abstract</option>
              <option value="metadata">Metadata/link</option>
              <option value="excerpt">Excerpt</option>
              <option value="full_text">Full text</option>
            </select>
          </label>
          <label>
            Reading state
            <select
              value={filters.status}
              onChange={(event) =>
                setFilters({ ...filters, status: event.target.value })
              }
            >
              <option value="">Any reading state</option>
              {[
                "unread",
                "saved",
                "read",
                "archived",
                "dismissed",
                "snoozed",
              ].map((status) => (
                <option value={status} key={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="daily-secondary" disabled={loading || actions.busy}>
          Apply filters
        </button>
      </form>

      <p className="workspace-review-link"><Link href="/workspace/review" className="daily-link" prefetch={false}>Review a finite candidate set →</Link></p>
    </SidebarSection>
    <SidebarSection label="Radar results"><h2>Results</h2>
      <QueueList items={items} focusId={focused?.work_id ?? null} onSelect={choose} label="Radar results" />
      <div className="workspace-list-pagination">
        <button className="daily-secondary" disabled={!applied?.cursor || loading || actions.busy} onClick={() => navigate({ filters: applied!.filters, cursor: null, asOf: page?.as_of ?? applied?.asOf ?? null })}>First page</button>
      </div>
    </SidebarSection>
    <div className="daily-section-heading ws-focus-section-heading"><h2>Stored source records</h2><span>{loading ? "Loading stored result window…" : page ? `${items.length} on this page · stable observation cutoff` : "No successful result window loaded"}</span></div>
    {loading && <div className="ws-radar-state" aria-busy="true"><Mascot mood="busy" /><p>Loading this stored result window…</p></div>}
    {!loading && !page && <div className="ws-radar-state"><Mascot mood="alert" /><h2>This stored result window could not be loaded.</h2><button type="button" className="daily-secondary" onClick={() => navigate(applied ?? fromURL())}>Retry stored results</button></div>}
    {focused && retained && <FocusPaper item={focused} href={href} />}
    {focused && !retained && <section className="daily-empty ws-radar-state">
      <h2>This retained source version is unavailable.</h2>
      <p>Your saved reading position remains attached to {target?.version}. A newer version has not been substituted.</p>
    </section>}
    {page && !items.length && <div className="daily-empty ws-radar-state"><Mascot mood="sleepy" /><h2>No stored items match these filters.</h2><p>This search does not check the network. Use Today or Sources &amp; checks for a fresh, bounded source check.</p></div>}
    <ControlBar>
      {focused && retained && <PlayerBar item={focused} href={href} index={position.index} count={position.count} busy={actions.busy}
        onPrevious={position.previous ? () => choose(position.previous!.work_id) : undefined}
        onNext={position.next ? () => choose(position.next!.work_id) : undefined}>
        <div className="ws-player-actions" role="group" aria-label="Paper actions">
          <button type="button" className="ws-player-action" data-command="save" aria-keyshortcuts="S" disabled={actions.busy} aria-label={`${focused.reading.status === "saved" ? "Unsave" : "Save"} ${focused.title}`} aria-pressed={focused.reading.status === "saved"} onClick={() => void actions.status(focused, focused.reading.status === "saved" ? "unread" : "saved")}>{focused.reading.status === "saved" ? "Unsave" : "Save"}</button>
          <button type="button" className="ws-player-action" data-command="dismiss" aria-keyshortcuts="D" disabled={actions.busy} aria-label={`Dismiss ${focused.title}`} onClick={() => void actions.status(focused, "dismissed")}>Dismiss</button>
          <button type="button" className="ws-player-action" data-command="snooze" aria-keyshortcuts="Z" disabled={actions.busy} aria-label={`Snooze one day ${focused.title}`} onClick={() => void actions.status(focused, "snoozed")}>Snooze one day</button>
          {undoButton}
        </div>
      </PlayerBar>}
        {page?.next_cursor && position.index === items.length - 1 && <button className="daily-secondary" data-command="next-page" disabled={loading || actions.busy} onClick={() => navigate({ filters: applied?.filters ?? filters, cursor: page.next_cursor, asOf: page.as_of })}>Next page →</button>}
      {focused && !retained && <Link href={href} prefetch={false} className="ws-player-open" aria-label="Open in reader" data-command="open" aria-keyshortcuts="O Enter">Read</Link>}
      {(!focused || !retained) && undoButton}
      <Message>{notice}</Message>
    </ControlBar>
  </div>;
}
