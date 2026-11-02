"use client";
import { useEffect, useState } from "react";
import {
  errorMessage,
  workspaceRequest,
  type WorkItem,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { useReadingActions } from "@/lib/workspace/useReadingActions";
import { LoadingState, Message, ServiceNotice } from "./Common";
import { WorkCard } from "./WorkCard";

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
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState<ReturnType<typeof fromURL> | null>(
    null,
  );
  const [page, setPage] = useState<WorkPage | null>(null);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const actions = useReadingActions(state, setState, setNotice);
  useEffect(() => {
    const loadURL = () => {
      const value = fromURL();
      setFilters(value.filters);
      setApplied(value);
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
        setPage(result);
        setNotice("");
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setNotice(errorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [applied]);
  if (!state) return <LoadingState error={error} retry={() => void reload()} />;
  function navigate(next: ReturnType<typeof fromURL>) {
    const params = new URLSearchParams(
      next.filters as unknown as Record<string, string>,
    );
    if (next.cursor) params.set("cursor", next.cursor);
    if (next.asOf) params.set("as_of", next.asOf);
    window.history.pushState(null, "", `/workspace/radar?${params}`);
    setLoading(true);
    setApplied(next);
  }
  return (
    <>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">Radar · actual stored metadata</span>
        <span className="daily-muted">No generated summaries</span>
      </div>
      <div className="daily-intro">
        <div>
          <h1>
            A wider view.
            <br />
            <em>Your terms, your pace.</em>
          </h1>
          <p>
            Search the sources you actually checked, including items outside
            today’s shortlist.
          </p>
        </div>
      </div>
      <ServiceNotice error={error} />
      <form
        onSubmit={(event) => {
          event.preventDefault();
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
        <button className="daily-secondary" disabled={loading}>
          Apply filters
        </button>
      </form>
      <div className="workspace-toolbar">
        {actions.hasUndo && (
          <button
            className="daily-secondary"
            disabled={actions.busy}
            onClick={() => void actions.undo()}
          >
            Undo last change
          </button>
        )}
        <Message>
          {loading ? "Loading this stored result window…" : notice}
        </Message>
      </div>
      <div className="daily-section-heading">
        <h2>Stored source records</h2>
        <span>
          {page?.items.length ?? 0} on this page · stable observation cutoff
        </span>
      </div>
      {page?.items.map((item) => {
        const current = state.works.find(
          (work) => work.work_id === item.work_id,
        );
        return (
          <WorkCard
            key={item.work_id}
            item={
              current
                ? {
                    ...item,
                    reading: current.reading,
                    entries: current.entries,
                  }
                : item
            }
            busy={actions.busy}
            status={(work, status) => void actions.status(work, status)}
          />
        );
      })}
      {page && page.items.length === 0 && (
        <div className="daily-empty">
          <h2>No stored items match these filters.</h2>
          <p>
            This search does not check the network. Use Today or Sources &
            checks for a fresh, bounded source check.
          </p>
        </div>
      )}
      <div className="workspace-list-pagination">
        <button
          className="daily-secondary"
          disabled={!applied?.cursor || loading}
          onClick={() =>
            navigate({
              filters: applied!.filters,
              cursor: null,
              asOf: page?.as_of ?? null,
            })
          }
        >
          First page
        </button>
        {page?.next_cursor && (
          <button
            className="daily-secondary"
            disabled={loading}
            onClick={() =>
              navigate({
                filters: applied?.filters ?? filters,
                cursor: page.next_cursor,
                asOf: page.as_of,
              })
            }
          >
            Next page →
          </button>
        )}
      </div>
    </>
  );
}
