"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import {
  errorMessage,
  readerHref,
  workspaceRequest,
  type WorkItem,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { useReadingActions } from "@/lib/workspace/useReadingActions";
import { LoadingState, Message, ServiceNotice } from "./Common";
import { PreviewImport } from "./Import";
import { WorkCard } from "./WorkCard";

export function LiveLibrary() {
  const { state, setState, error, reload } = useWorkspace();
  const [notice, setNotice] = useState("");
  const [manual, setManual] = useState("");
  const [busy, setBusy] = useState(false);
  const view = useSearchParams().get("view");
  // Derive the view from the router on every render, including client returns.
  const filter =
    view && ["saved", "notes", "read", "archived", "all"].includes(view)
      ? view
      : "saved";
  const actions = useReadingActions(state, setState, setNotice);
  if (!state) return <LoadingState error={error} retry={() => void reload()} />;
  const works = state.works.filter((item) =>
    filter === "all"
      ? item.entries.length > 0 || item.reading.status !== "unread"
      : filter === "notes"
        ? item.entries.length > 0
        : item.reading.status === filter,
  );
  async function saveManual(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const work = await workspaceRequest<WorkItem>("manual", {
        value: manual.trim(),
      });
      await reload();
      setManual("");
      setNotice(
        `Saved ${work.title}. Access remains ${work.access_state}; an original link is available in the reader.`,
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
        <span className="daily-eyebrow">Your library · server-backed</span>
        <a
          className="daily-link"
          href="/api/workspace/export"
          download="research-notes.md"
        >
          Export notes as Markdown ↗
        </a>
      </div>
      <div className="daily-intro">
        <div>
          <h1>
            Keep the source.
            <br />
            <em>Keep your thinking.</em>
          </h1>
          <p>
            Saved reading, questions and next steps retain their source version.
          </p>
        </div>
      </div>
      <ServiceNotice error={error} />
      <form
        className="workspace-form-stack"
        onSubmit={(event) => void saveManual(event)}
      >
        <label>
          Save an arXiv ID, DOI or source URL
          <input
            value={manual}
            maxLength={2048}
            required
            onChange={(event) => setManual(event.target.value)}
            placeholder="arXiv:2601.01234 · 10.1234/example · https://…"
          />
        </label>
        <button className="daily-secondary" disabled={busy}>
          {busy ? "Saving source…" : "Save source link"}
        </button>
        <p className="daily-muted">
          Unsupported or inaccessible sources stay link/metadata items. Saving
          does not crawl the page or run a model.
        </p>
      </form>
      <div className="workspace-toolbar">
        <label>
          Library view
          <select
            value={filter}
            onChange={(event) => {
              window.history.replaceState(
                null,
                "",
                `/workspace/library?view=${encodeURIComponent(event.target.value)}`,
              );
            }}
          >
            <option value="saved">Saved</option>
            <option value="notes">With notes or questions</option>
            <option value="read">Read</option>
            <option value="archived">Archived</option>
            <option value="all">All personal state</option>
          </select>
        </label>
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
      {works.length ? (
        works.map((item) => (
          <section key={item.work_id}>
            <WorkCard
              item={item}
              returnTo={`/workspace/library?view=${filter}`}
              busy={actions.busy}
              status={(work, status) => void actions.status(work, status)}
            />
            {item.entries.map((entry) => (
              <article key={entry.id} className="daily-notebook-entry">
                <span className="daily-eyebrow">
                  Your {entry.kind.replaceAll("-", " ")}
                </span>
                <p>{entry.body}</p>
                <p className="workspace-note-context">
                  Source {entry.version_id} · {entry.anchor}
                </p>
                <Link
                  href={readerHref(
                    item,
                    entry.version_id,
                    entry.anchor,
                    entry.id,
                    `/workspace/library?view=${filter}`,
                  )}
                  prefetch={false}
                  className="daily-link"
                >
                  Resume this question →
                </Link>
              </article>
            ))}
          </section>
        ))
      ) : (
        <section className="daily-empty">
          <h2>
            {filter === "saved"
              ? "Save something worth returning to."
              : "No items in this view."}
          </h2>
          <p>
            Your notes and reading state will appear here after a successful
            server save.
          </p>
          <Link href="/workspace/today" className="daily-link" prefetch={false}>
            Back to Today →
          </Link>
        </section>
      )}
      <PreviewImport
        revision={state.profile.revision}
        reload={reload}
        announce={setNotice}
      />
    </>
  );
}
