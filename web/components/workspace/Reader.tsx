"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import {
  displayDate,
  errorMessage,
  readerHref,
  requestId,
  workspaceRequest,
  type EntryRevision,
  type ReadingRevision,
  type WorkItem,
  type WorkspaceState,
} from "@/lib/workspace/api";
import {
  loadDraft,
  storeDraft,
  type ReaderDraft,
} from "@/lib/workspace/drafts";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import {
  GenerationBoundary,
  LoadingState,
  Message,
  ServiceNotice,
} from "./Common";

export function LiveReader({ id }: { id: string }) {
  const { state, setState, error, reload } = useWorkspace();
  if (!state) return <LoadingState error={error} retry={() => void reload()} />;
  const item = state.works.find((work) => work.work_id === id);
  if (!item)
    return (
      <div className="daily-empty">
        <h1>This source is not in the loaded workspace.</h1>
        <p>
          No fictional source was substituted. Save the source URL in Library or
          return to Radar.
        </p>
        <Link href="/workspace/library" className="daily-link" prefetch={false}>
          Open Library →
        </Link>
      </div>
    );
  return (
    <ReaderContent
      key={`${state.principal_key_id}:${item.work_id}`}
      item={item}
      state={state}
      setState={setState}
      error={error}
    />
  );
}

const emptyDraft = (scope = "abstract"): ReaderDraft => ({
  id: requestId(),
  revision: 0,
  body: "",
  kind: "question",
  anchor: `${scope}:0`,
});

function scopeOf(material: { access_state: string; source_scope?: string }) {
  return ["abstract", "excerpt", "metadata"].includes(material.access_state)
    ? material.access_state
    : material.source_scope || material.access_state;
}

function ReaderContent({
  item,
  state,
  setState,
  error,
}: {
  item: WorkItem;
  state: WorkspaceState;
  setState: (state: WorkspaceState) => void;
  error: string;
}) {
  const owner = state.principal_key_id;
  const [initial] = useState(() => {
    const desired =
      typeof window === "undefined"
        ? null
        : new URLSearchParams(window.location.search).get("version");
    const version = desired || item.reading.version_id || item.version_id;
    const scope = scopeOf(
      item.versions.find((candidate) => candidate.version_id === version) ??
        item,
    );
    let fragment =
      typeof window === "undefined" ? "" : window.location.hash.slice(1);
    try {
      fragment = decodeURIComponent(fragment);
    } catch {
      fragment = "";
    }
    try {
      const recovered = loadDraft(owner, item.work_id, version);
      return {
        version,
        fragment,
        draft: recovered ?? emptyDraft(scope),
        recovery: true,
        notice: recovered
          ? "Recovered your unsaved draft for this account and source version. It has not been saved to the server."
          : "",
      };
    } catch {
      return {
        version,
        fragment,
        draft: emptyDraft(scope),
        recovery: false,
        notice:
          "Browser draft recovery is unavailable. Keep this tab open or copy your unsaved text before leaving.",
      };
    }
  });
  const [versionId, setVersionId] = useState(initial.version);
  const [active, setActive] = useState(
    initial.fragment === "notes" || initial.fragment === "understand"
      ? initial.fragment
      : "source",
  );
  const [draft, setDraft] = useState<ReaderDraft>(initial.draft);
  const [notice, setNotice] = useState(initial.notice);
  const [busy, setBusy] = useState(false);
  const [draftStorage, setDraftStorage] = useState(initial.recovery);
  const [selection, setSelection] = useState("");
  const [sourceAnchor, setSourceAnchor] = useState(
    /^(abstract|excerpt|full_text):/.test(initial.fragment)
      ? initial.fragment
      : item.reading.anchor,
  );
  const source = useRef<HTMLParagraphElement>(null);
  const attempts = useRef(new Map<string, string>());
  const versions = item.versions.length
    ? item.versions
    : [
        {
          version_id: item.version_id,
          version_label: item.version_label,
          abstract: item.abstract,
          access_state: item.access_state,
          fetched_at: item.fetched_at,
          content_hash: item.content_hash,
          source_scope: item.access_state,
          title: item.title,
          url: item.url,
          authors: item.authors,
        },
      ];
  const material =
    versions.find((version) => version.version_id === versionId) ??
    versions[0]!;
  const sourceScope = scopeOf(material);
  const entries = item.entries.filter(
    (entry) => entry.version_id === material.version_id,
  );
  const otherEntries = item.entries.filter(
    (entry) => entry.version_id !== material.version_id,
  );

  function edit(change: Partial<ReaderDraft>) {
    const next = { ...draft, ...change };
    setDraft(next);
    try {
      storeDraft(
        owner,
        item.work_id,
        material.version_id,
        next.body ? next : null,
      );
      setDraftStorage(true);
    } catch {
      setDraftStorage(false);
    }
    setNotice("Unsaved draft. Your text is not a durable server save yet.");
  }
  function selectPassage() {
    if (!material.abstract) return;
    const selection = window.getSelection();
    if (!selection?.rangeCount || !source.current) return;
    const range = selection.getRangeAt(0);
    if (
      !source.current.contains(range.startContainer) ||
      !source.current.contains(range.endContainer) ||
      !selection.toString().trim()
    )
      return;
    const before = range.cloneRange();
    before.selectNodeContents(source.current);
    before.setEnd(range.startContainer, range.startOffset);
    // Stored source spans count Unicode code points, as Python does. DOM
    // ranges expose UTF-16 offsets, so count their extracted text explicitly.
    const start = Array.from(before.toString()).length,
      selected = Array.from(range.toString()),
      end = start + selected.length;
    setSelection(selected.slice(0, 400).join(""));
    setSourceAnchor(`${sourceScope}:${start}:${end}`);
    edit({ anchor: `${sourceScope}:${start}:${end}` });
  }
  async function reading(
    status: ReadingRevision["status"],
    anchor = item.reading.anchor,
  ) {
    const input = {
      work_id: item.work_id,
      revision: item.reading.revision,
      data: {
        status,
        anchor,
        version_id: material.version_id,
        snoozed_until: null,
      },
    };
    const fingerprint = JSON.stringify(input),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    setBusy(true);
    try {
      const next = await workspaceRequest<ReadingRevision>("reading", {
        ...input,
        request_id: id,
      });
      setState({
        ...state,
        works: state.works.map((work) =>
          work.work_id === item.work_id ? { ...work, reading: next } : work,
        ),
      });
      setNotice(
        `Reading state saved on the server for ${material.version_label}.`,
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    const input = {
      id: draft.id,
      revision: draft.revision,
      data: {
        work_id: item.work_id,
        version_id: material.version_id,
        kind: draft.kind,
        body: draft.body.trim(),
        anchor: draft.anchor,
      },
    };
    const fingerprint = JSON.stringify(input),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    setBusy(true);
    try {
      const entry = await workspaceRequest<EntryRevision>("entries", {
        ...input,
        request_id: id,
      });
      const nextItem = {
        ...item,
        entries: [
          ...item.entries.filter((previous) => previous.id !== entry.id),
          entry,
        ],
      };
      setState({
        ...state,
        works: state.works.map((work) =>
          work.work_id === item.work_id ? nextItem : work,
        ),
      });
      try {
        storeDraft(owner, item.work_id, material.version_id, null);
      } catch {
        /* Authored server record is already confirmed; the old draft remains recoverable. */
      }
      setDraft(emptyDraft(sourceScope));
      setSelection("");
      setNotice(
        `Your ${entry.kind.replaceAll("-", " ")} is saved on the server against ${material.version_label}, ${entry.anchor}.`,
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  function tab(value: string) {
    setActive(value);
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}#${value}`,
    );
    void reading(
      item.reading.status,
      value === "source" ? draft.anchor : value,
    );
  }
  function viewVersion(value: string) {
    setVersionId(value);
    try {
      const recovered = loadDraft(owner, item.work_id, value);
      setDraft(
        recovered ??
          emptyDraft(
            scopeOf(
              versions.find((candidate) => candidate.version_id === value) ??
                material,
            ),
          ),
      );
      setDraftStorage(true);
      setNotice(
        recovered
          ? "Recovered your unsaved draft for this source version. It is not a server save."
          : "Reading a separate source version. Its notes remain separate.",
      );
    } catch {
      setDraft(emptyDraft(sourceScope));
      setDraftStorage(false);
    }
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}?version=${encodeURIComponent(value)}#${active}`,
    );
    setSelection("");
    setSourceAnchor(
      `${scopeOf(versions.find((candidate) => candidate.version_id === value) ?? material)}:0`,
    );
  }
  const anchorMatch = /^(?:abstract|excerpt|full_text):(\d+):(\d+)$/.exec(
    sourceAnchor,
  );
  const start = anchorMatch ? Number(anchorMatch[1]) : 0;
  const end = anchorMatch ? Number(anchorMatch[2]) : 0;
  const sourceCharacters = Array.from(material.abstract);
  const hasPassage = end > start && end <= sourceCharacters.length;
  if (!versions.some((version) => version.version_id === versionId)) {
    return (
      <section className="daily-empty">
        <h1>This retained source version is unavailable.</h1>
        <p>
          Your saved notes remain attached to {versionId}. A newer version has
          not been substituted.
        </p>
        {item.entries
          .filter((entry) => entry.version_id === versionId)
          .map((entry) => (
            <article key={entry.id} className="daily-notebook-entry">
              <span className="daily-eyebrow">Your {entry.kind}</span>
              <p>{entry.body}</p>
              <p className="workspace-note-context">{entry.anchor}</p>
            </article>
          ))}
        <Link
          href={readerHref(item, item.version_id)}
          className="daily-link"
          prefetch={false}
        >
          Choose the latest observed version →
        </Link>
      </section>
    );
  }
  return (
    <>
      <div className="daily-page-meta">
        <Link href="/workspace/today" prefetch={false} className="daily-link">
          ← Today
        </Link>
        <span className="daily-eyebrow">
          Source reader · retained {sourceScope}
        </span>
      </div>
      <ServiceNotice error={error} />
      <header className="daily-reader-header">
        <div className="daily-item-meta">
          <span>{item.kind}</span>
          <span>{material.version_label}</span>
          <span>{material.access_state.replaceAll("_", " ")}</span>
        </div>
        <h1 className="workspace-reader-title">
          {material.title || item.title}
        </h1>
        <p>
          {(material.authors.length ? material.authors : item.authors).join(
            ", ",
          ) || item.source_id}{" "}
          ·{" "}
          {item.published_at
            ? `Published ${displayDate(item.published_at)}`
            : "Publication date unknown"}
        </p>
        <div className="workspace-card-actions">
          <a
            href={material.url || item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="daily-link"
          >
            Open original source ↗
          </a>
          <button
            className="daily-secondary"
            disabled={busy}
            aria-pressed={item.reading.status === "saved"}
            onClick={() =>
              void reading(item.reading.status === "saved" ? "unread" : "saved")
            }
          >
            {item.reading.status === "saved"
              ? "Remove from saved items"
              : "Save to Library"}
          </button>
          <button
            className="daily-text-button"
            disabled={busy}
            onClick={() => void reading("read")}
          >
            Mark read
          </button>
          <button
            className="daily-text-button"
            disabled={busy}
            onClick={() => void reading("archived")}
          >
            Archive
          </button>
        </div>
      </header>
      {versions.length > 1 && (
        <label className="workspace-form-stack">
          Source version
          <select
            value={material.version_id}
            onChange={(event) => viewVersion(event.target.value)}
          >
            {versions.map((version) => (
              <option key={version.version_id} value={version.version_id}>
                {version.version_label} ·{" "}
                {version.version_id === item.version_id
                  ? "latest observed"
                  : "earlier retained version"}
              </option>
            ))}
          </select>
        </label>
      )}
      {material.version_id !== item.version_id && (
        <div className="workspace-version-notice">
          You are reading an earlier retained version. Its notes remain attached
          here.{" "}
          <button
            className="daily-text-button"
            onClick={() => viewVersion(item.version_id)}
          >
            View latest source version
          </button>
        </div>
      )}
      <nav className="daily-reader-tabs" aria-label="Reading sections">
        {[
          ["source", "Source"],
          ["understand", "Understand"],
          ["notes", "Your notes"],
        ].map(([id, label]) => (
          <a
            href={`#${id}`}
            key={id}
            aria-current={active === id ? "location" : undefined}
            onClick={(event) => {
              event.preventDefault();
              tab(id!);
            }}
          >
            {label}
          </a>
        ))}
      </nav>
      <div className="daily-reader-grid">
        <section
          id="source"
          className="daily-source-panel"
          data-active={active === "source"}
          aria-labelledby="retained-source-title"
        >
          <div className="daily-section-heading">
            <h2 id="retained-source-title">
              {material.abstract
                ? sourceScope === "excerpt"
                  ? "Retained feed excerpt"
                  : "Retained source abstract"
                : "Source metadata"}
            </h2>
            <span>{material.version_label}</span>
          </div>
          <p className="daily-source-attribution">
            Source text, not a generated summary. Retained{" "}
            {displayDate(material.fetched_at)}. Select a passage to anchor your
            next note.
          </p>
          <div className="daily-source-text">
            <p ref={source} onMouseUp={selectPassage} onKeyUp={selectPassage}>
              {hasPassage ? (
                <>
                  {sourceCharacters.slice(0, start).join("")}
                  <mark id="source-anchor">
                    {sourceCharacters.slice(start, end).join("")}
                  </mark>
                  {sourceCharacters.slice(end).join("")}
                </>
              ) : (
                material.abstract ||
                "No abstract or full text was acquired. Use the original-source link for reading. Your questions and notes can still be kept against this metadata version."
              )}
            </p>
          </div>
          {hasPassage && (
            <p className="workspace-note-context">
              Resumed source passage at character offsets {start}–{end} of this
              retained version.
            </p>
          )}
          <div className="daily-source-boundary">
            <span className="daily-eyebrow">Evidence boundary</span>
            <p>
              Available scope: {sourceScope}. The full methods, experiments,
              appendices and result tables have not been acquired unless
              explicitly shown.
            </p>
            <p className="workspace-origin">
              {item.work_id}
              <br />
              {material.version_id}
              <br />
              Material digest {material.content_hash || "not available"}
            </p>
          </div>
        </section>
        <aside
          id="understand"
          className="daily-understand-panel"
          data-active={active === "understand"}
          aria-labelledby="understand-live-title"
        >
          <span className="daily-eyebrow">Understand this work</span>
          <h2 id="understand-live-title">
            Start with what
            <br />
            the source supports.
          </h2>
          <p>
            Your current question:{" "}
            {state.profile.data.research_question ||
              "Add a research question in Interests."}
          </p>
          <div className="daily-thread">
            <div>
              <span>Inspect the evidence</span>
              <p>
                What do the authors claim, which baseline was used, and what
                conditions would have to hold for your project?
              </p>
            </div>
            <div>
              <span>Keep your interpretation separate</span>
              <p>
                Save an observation, an open question or a proposed next action.
                These are your words and are not verified findings.
              </p>
            </div>
          </div>
          <GenerationBoundary />
        </aside>
        <section
          id="notes"
          className="daily-notes-panel"
          data-active={active === "notes"}
          aria-labelledby="your-live-notes"
        >
          <div>
            <span className="daily-eyebrow">Your own thinking</span>
            <h2 id="your-live-notes">Keep a question open.</h2>
            <p>
              Your text stays attached to {material.version_label}. New source
              versions never silently move a note.
            </p>
            {selection && (
              <blockquote className="workspace-version-notice">
                Selected source passage: “{selection}”
              </blockquote>
            )}
            <p className="workspace-note-context">Anchor: {draft.anchor}</p>
            <p className="daily-muted">
              {draftStorage
                ? "Unsaved draft recovery is limited to this browser session and account. Only a successful server response confirms a durable save."
                : "Draft recovery is unavailable. Copy your text before closing this tab."}
            </p>
          </div>
          <form onSubmit={(event) => void save(event)}>
            <label>
              Save as
              <select
                value={draft.kind}
                onChange={(event) =>
                  edit({ kind: event.target.value as ReaderDraft["kind"] })
                }
              >
                <option value="question">Question</option>
                <option value="note">Note</option>
                <option value="next-action">Next action · proposal</option>
              </select>
            </label>
            <label>
              Your {draft.kind.replaceAll("-", " ")}
              <textarea
                required
                rows={6}
                maxLength={10000}
                value={draft.body}
                onChange={(event) => edit({ body: event.target.value })}
              />
            </label>
            <div className="daily-form-footer">
              <button
                className="daily-button"
                disabled={busy || !draft.body.trim()}
              >
                {busy ? "Saving…" : `Save ${draft.kind.replaceAll("-", " ")}`}
              </button>
              {draft.revision > 0 && (
                <button
                  type="button"
                  className="daily-text-button"
                  onClick={() => {
                    setDraft(emptyDraft(sourceScope));
                    setNotice(
                      "Editing stopped. The saved note was not changed.",
                    );
                  }}
                >
                  Cancel edit
                </button>
              )}
            </div>
            <Message>{notice}</Message>
          </form>
          <div className="daily-saved-entries">
            <h3>Saved against this version</h3>
            {entries.length === 0 && (
              <p>No server-saved notes for this version yet.</p>
            )}
            {entries.map((entry) => (
              <article key={entry.id}>
                <span className="daily-eyebrow">
                  Your {entry.kind.replaceAll("-", " ")}
                </span>
                <p>{entry.body}</p>
                <p className="workspace-note-context">
                  {entry.version_id} · {entry.anchor} · revision{" "}
                  {entry.revision}
                </p>
                <button
                  className="daily-text-button"
                  onClick={() =>
                    edit({
                      id: entry.id,
                      revision: entry.revision,
                      body: entry.body,
                      kind: entry.kind,
                      anchor: entry.anchor,
                    })
                  }
                >
                  Edit {entry.kind.replaceAll("-", " ")}
                </button>
                <a
                  href={readerHref(item, entry.version_id, entry.anchor)}
                  className="daily-link"
                >
                  Source context →
                </a>
              </article>
            ))}
            {otherEntries.length > 0 && (
              <div className="workspace-version-notice">
                <h3>Notes on other source versions</h3>
                {otherEntries.map((entry) => (
                  <p key={entry.id}>
                    <a
                      className="daily-link"
                      href={readerHref(item, entry.version_id, "notes")}
                    >
                      {entry.body.slice(0, 100)} · {entry.version_id} →
                    </a>
                  </p>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
