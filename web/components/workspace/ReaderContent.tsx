"use client";
import Link from "next/link";
import { settleReaderTarget } from "@/lib/workspace/navigation";
import { blockWorkspaceNavigation } from "@/lib/workspace/navigationGuard";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  displayDate, errorMessage, readerHref, requestId, readingMaterial, workspaceRequest,
  type EntryRevision, type ReadingRevision, type WorkItem, type WorkspaceState,
} from "@/lib/workspace/api";
import { DRAFT_NAVIGATION_NOTICE, loadDraft, storeDraft, type ReaderDraft } from "@/lib/workspace/drafts";
import { libraryQueue, neighbours, readerTarget, todayQueue } from "@/lib/workspace/queue";
import { ControlBar, SidebarSection, StageHeaderSlot } from "./Slots";
import ReaderControls from "./ReaderControls";
import { parseMaterialAnchor, RetainedSourceReader } from "./RetainedSource";
import { Message, ServiceNotice } from "./Common";
import GenerationBoundary from "./GenerationBoundary";

const ReaderQueue = lazy(() => import("./ReaderQueue"));
const SyntheticWorkbench = lazy(() => import("./SyntheticWorkbench").then(workbench => ({ default: workbench.SyntheticWorkbench })));

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

export default function ReaderContent({
  item,
  state,
  setState,
  error,
  requestedVersion,
  requestedEntry,
  returnTo,
  reviewWorks,
}: {
  item: WorkItem;
  state: WorkspaceState;
  setState: (state: WorkspaceState) => void;
  error: string;
  requestedVersion: string | null;
  requestedEntry: string | null;
  returnTo: string;
  reviewWorks: WorkItem[];
}) {
  const owner = state.principal_key_id;
  const [initial] = useState(() => {
    const entry = requestedEntry
      ? item.entries.find((candidate) => candidate.id === requestedEntry)
      : undefined;
    const version =
      entry?.version_id ||
      requestedVersion ||
      item.reading.version_id ||
      item.version_id;
    const selected = item.versions.find((candidate) => candidate.version_id === version) ?? item;
    const scope = scopeOf(selected);
    let fragment =
      typeof window === "undefined" ? "" : window.location.hash.slice(1);
    try {
      fragment = decodeURIComponent(fragment);
    } catch {
      fragment = "";
    }
    const preferredAnchor = !entry &&
      !/^(abstract|excerpt|full_text|material):/.test(fragment) &&
      !(item.reading.revision > 0 && item.reading.version_id === version)
        ? selected.retained_materials?.find((value) => value.format === "pdf")?.first_anchor ?? undefined
        : undefined;
    try {
      const recovered = loadDraft(owner, item.work_id, version);
      return {
        version,
        fragment,
        scope,
        entryId: entry?.id,
        sourceAnchor:
          entry?.anchor || (/^(abstract|excerpt|full_text|material):/.test(fragment) ? fragment : recovered?.body ? recovered.anchor : preferredAnchor),
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
        scope,
        entryId: entry?.id,
        sourceAnchor: entry?.anchor || (/^(abstract|excerpt|full_text|material):/.test(fragment) ? fragment : preferredAnchor),
        draft: emptyDraft(scope),
        recovery: false,
        notice:
          "Browser draft recovery is unavailable. Keep this tab open or copy your unsaved text before leaving.",
      };
    }
  });
  const [versionId, setVersionId] = useState(initial.version);
  const [active, setActive] = useState(
    initial.entryId
      ? "notes"
      : initial.fragment === "notes" || initial.fragment === "understand"
        ? initial.fragment
        : "source",
  );
  const [workbenchOpened, setWorkbenchOpened] = useState(initial.fragment === "understand");
  const [draft, setDraft] = useState<ReaderDraft>(initial.draft);
  const [notice, setNotice] = useState(initial.notice);
  const [busy, setBusy] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [draftStorage, setDraftStorage] = useState(initial.recovery);
  const [selection, setSelection] = useState("");
  const [pdfActive, setPdfActive] = useState(false);
  const [sourceAnchor, setSourceAnchor] = useState(
    initial.sourceAnchor ||
      (/^(abstract|excerpt|full_text|material):/.test(initial.fragment)
        ? initial.fragment
        : item.reading.version_id === initial.version
          ? item.reading.anchor
          : `${initial.scope}:0`),
  );
  const source = useRef<HTMLParagraphElement>(null);
  const jumpToSource = useRef(false);
  const attempts = useRef(new Map<string, string>());
  const tabFocus = useRef(false);
  useEffect(() => {
    if (!tabFocus.current) return;
    tabFocus.current = false;
    const panel = document.getElementById(active);
    if (panel) settleReaderTarget(panel, true, true);
  }, [active]);
  const unsafeDraft = Boolean(draft.body && !draftStorage);
  const navigationBlocked = busy || unsafeDraft;
  useEffect(() => {
    if (!navigationBlocked) return;
    const refuse = () => setNotice(unsafeDraft ? DRAFT_NAVIGATION_NOTICE : "Wait for the current save to finish before leaving this source version.");
    const release = blockWorkspaceNavigation(refuse);
    function guardLink(event: MouseEvent) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(target instanceof HTMLAnchorElement) || target.hasAttribute("download")) return;
      const destination = target.getAttribute("href");
      if (!destination || destination.startsWith("#") || target.target.toLowerCase() === "_blank") return;
      event.preventDefault();
      event.stopPropagation();
      refuse();
    }
    function warnBeforeUnload(event: BeforeUnloadEvent) {
      if (!unsafeDraft) return;
      event.preventDefault();
      event.returnValue = "";
    }
    document.addEventListener("click", guardLink, true);
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => {
      release();
      document.removeEventListener("click", guardLink, true);
      window.removeEventListener("beforeunload", warnBeforeUnload);
    };
  }, [navigationBlocked, unsafeDraft]);
  const isToday = returnTo.startsWith("/workspace/today");
  const queue = isToday ? todayQueue(state)
    : returnTo.startsWith("/workspace/library") ? libraryQueue(state, new URLSearchParams(returnTo.split("?")[1]).get("view") || "saved")
    : returnTo.startsWith("/workspace/review") ? reviewWorks : [];
  const position = neighbours(queue, item.work_id);
  const targets = queue.map((work) => {
    const target = readerTarget(work, isToday ? state.editions[0]?.work_versions[work.work_id] : returnTo.startsWith("/workspace/review") ? work.version_id : undefined);
    const version = readingMaterial(work, target.version).version;
    return { workId: work.work_id, title: version.title || work.title,
      href: readerHref(work, target.version, target.anchor, undefined, isToday ? `/workspace/today?focus=${encodeURIComponent(work.work_id)}` : returnTo) };
  });
  function guardNavigation() {
    if (!navigationBlocked) return false;
    if (unsafeDraft) setNotice(DRAFT_NAVIGATION_NOTICE);
    return true;
  }

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
          reading_access_state: item.reading_access_state,
          available_scopes: item.available_scopes,
          retained_materials: item.retained_materials,
        },
      ];
  const material =
    versions.find((version) => version.version_id === versionId) ??
    versions[0]!;
  const sourceScope = scopeOf(material);
  useEffect(() => {
    let observedFragment: string | undefined;
    const synchronizeFragment = (event?: Event) => {
      let fragment: string;
      try {
        if (decodeURIComponent(location.pathname.split("/workspace/items/")[1] ?? "") !== item.work_id) return;
        fragment = decodeURIComponent(location.hash.slice(1));
      } catch { return; }
      if (fragment === observedFragment && !event) return;
      const requested = new URLSearchParams(location.search).get("version");
      if (requested && requested !== versionId) return;
      const entryPriority = !event && observedFragment === undefined && initial.entryId && fragment === initial.fragment;
      observedFragment = fragment;
      if (entryPriority) return;
      if (["source", "notes", "understand"].includes(fragment)) {
        setActive(fragment);
        if (fragment === "understand") setWorkbenchOpened(true);
      } else if (/^(abstract|excerpt|full_text):\d+(?::\d+)?$/.test(fragment) || parseMaterialAnchor(fragment)) {
        setSourceAnchor(fragment);
        setActive("source");
      }
    };
    const initialFrame = requestAnimationFrame(() => synchronizeFragment());
    window.addEventListener("hashchange", synchronizeFragment);
    window.addEventListener("popstate", synchronizeFragment);
    return () => {
      cancelAnimationFrame(initialFrame);
      window.removeEventListener("hashchange", synchronizeFragment);
      window.removeEventListener("popstate", synchronizeFragment);
    };
  }, [initial.entryId, initial.fragment, item.work_id, versionId]);
  const knownPDF = material.retained_materials?.find((value) => value.format === "pdf");
  const entries = item.entries.filter(
    (entry) => entry.version_id === material.version_id,
  );
  const otherEntries = item.entries.filter(
    (entry) => entry.version_id !== material.version_id,
  );
  useEffect(() => {
    if (!initial.entryId) return;
    const target = document.getElementById(
      `workspace-entry-${initial.entryId}`,
    );
    if (target) settleReaderTarget(target);
  }, [initial.entryId]);
  useEffect(() => {
    if (initial.entryId || initial.fragment.startsWith("material:")) return;
    const section = ["source", "understand", "notes"].includes(initial.fragment) ? initial.fragment
      : /^(abstract|excerpt|full_text):/.test(initial.fragment) ? "source" : null;
    if (!section) return;
    const target = (section === "source" ? document.getElementById("source-anchor") : null) ?? document.getElementById(section);
    if (target) settleReaderTarget(target);
  }, [initial.entryId, initial.fragment]);
  useEffect(() => {
    if (!jumpToSource.current || active !== "source") return;
    jumpToSource.current = false;
    const panel = document.getElementById("source");
    const passage = panel?.querySelector<HTMLElement>("mark") ?? panel;
    panel?.focus({ preventScroll: true });
    if (passage) settleReaderTarget(passage, false, true);
  }, [active, sourceAnchor]);
  async function pin(entryId: string | null) {
    const input = {
      revision: state.profile.revision,
      data: { ...state.profile.data, pinned_entry_id: entryId },
    };
    const fingerprint = JSON.stringify(input),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    setBusy(true);
    try {
      const profile = await workspaceRequest<WorkspaceState["profile"]>(
        "profile",
        { ...input, request_id: id },
      );
      setState({ ...state, profile });
      setNotice(
        entryId
          ? "Saved item pinned for your return to Today. Its retained source version stays attached."
          : "Saved item unpinned. Your saved text is unchanged.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  function editEntry(entry: EntryRevision) {
    if (savingDraft) return;
    if (draft.body.trim() && draft.id !== entry.id) {
      setNotice(
        "You have an unsaved draft. Save or explicitly discard it before editing a different saved item.",
      );
      return;
    }
    edit({
      id: entry.id,
      revision: entry.revision,
      body: entry.body,
      kind: entry.kind,
      anchor: entry.anchor,
    });
    setSourceAnchor(entry.anchor);
    document.getElementById("workspace-note-body")?.focus();
  }

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
    if (savingDraft || !material.abstract) return;
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
    anchor = sourceAnchor,
  ) {
    if (busy) return;
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
    if (busy) return;
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
    setSavingDraft(true);
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
      setSavingDraft(false);
      setBusy(false);
    }
  }
  function tab(value: string) {
    if (value === "understand") setWorkbenchOpened(true);
    tabFocus.current = true;
    setActive(value);
    if (value === active) {
      const panel = document.getElementById(value);
      if (panel) settleReaderTarget(panel, true, true);
      tabFocus.current = false;
    }
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}#${value}`,
    );
    if (!busy) void reading(
      item.reading.status,
      sourceAnchor.startsWith("material:")
        ? sourceAnchor
        : value === "source"
          ? draft.anchor
          : value,
    );
  }
  function viewVersion(value: string) {
    if (guardNavigation()) return;
    setVersionId(value);
    setPdfActive(false);
    const selected = versions.find((candidate) => candidate.version_id === value) ?? material;
    let nextAnchor = readingMaterial(item, value).pdf?.first_anchor ?? `${scopeOf(selected)}:0`;
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
      if (recovered?.body) nextAnchor = recovered.anchor;
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
      window.history.state,
      "",
      `${window.location.pathname}?version=${encodeURIComponent(value)}&return_to=${encodeURIComponent(returnTo)}#${active}`,
    );
    setSelection("");
    setSourceAnchor(nextAnchor);
  }
  const anchorMatch = /^(?:abstract|excerpt|full_text):(\d+)(?::(\d+))?$/.exec(
    sourceAnchor,
  );
  const start = anchorMatch ? Number(anchorMatch[1]) : 0;
  const end = anchorMatch?.[2] !== undefined ? Number(anchorMatch[2]) : start;
  const sourceCharacters = Array.from(material.abstract);
  const validAnchor = sourceAnchor.startsWith(`${sourceScope}:`) && Number.isSafeInteger(start) && Number.isSafeInteger(end) && end >= start && end <= sourceCharacters.length;
  const hasPassage = validAnchor && end > start;
  if (!versions.some((version) => version.version_id === versionId)) {
    return (
      <section className="daily-empty" data-reader-unavailable="">
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
          href={readerHref(
            item,
            item.version_id,
            undefined,
            undefined,
            returnTo,
          )}
          className="daily-link"
          prefetch={false} scroll={false}
        >
          Choose the latest observed version →
        </Link>
      </section>
    );
  }
  return (
    <div className="ws-reader">
      <StageHeaderSlot position={position.index >= 0 ? { n: position.index + 1, N: position.count } : undefined} />
      <SidebarSection label="Reader queue">
        <h2>Reading queue</h2>
        {targets.length ? <Suspense fallback={<p className="daily-muted" aria-busy="true">Opening queued papers…</p>}><ReaderQueue targets={targets} currentId={item.work_id} blocked={navigationBlocked} /></Suspense> : <p className="daily-muted">Return to the originating page to choose another source.</p>}
      </SidebarSection>
      <SidebarSection label="Retained version details">
        <h2>Retained version</h2><p>{material.version_label} · {material.access_state.replaceAll("_", " ")}</p>
        <p className="ws-reader-digest">{material.content_hash || "No retained content hash available."}</p>
      </SidebarSection>
      <ControlBar><ReaderControls saved={item.reading.status === "saved"} busy={busy}
        onReading={(status) => void reading(status)} navigationBlocked={navigationBlocked}
        previousHref={position.index > 0 ? targets[position.index - 1]?.href : undefined}
        nextHref={position.index >= 0 ? targets[position.index + 1]?.href : undefined}
        index={position.index} count={position.count} /><Message>{notice}</Message></ControlBar>
      <div className="daily-page-meta">
        <Link href={returnTo} prefetch={false} scroll={false} className="daily-link" aria-disabled={navigationBlocked || undefined} onClick={(event) => { if (guardNavigation()) event.preventDefault(); }}>
          ←{" "}
          {returnTo.startsWith("/workspace/review")
            ? "Candidate review"
            : returnTo.startsWith("/workspace/radar")
              ? "Radar"
              : returnTo.startsWith("/workspace/library")
                ? "Library"
                : "Today"}
        </Link>
        <span className="daily-eyebrow">
          Source reader ·{" "}
          {pdfActive ? "retained document text" : `retained ${sourceScope}`}
        </span>
      </div>
      <ServiceNotice error={error} />
      {requestedEntry && !initial.entryId && (
        <p className="workspace-version-notice">
          That saved item is unavailable in this account. No different question
          has been substituted.
        </p>
      )}
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
          {material.authors.join(", ") || "Authors not retained for this version"}{" "}
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
        </div>
      </header>
      {unsafeDraft && <p className="workspace-version-notice">{DRAFT_NAVIGATION_NOTICE}</p>}
      {versions.length > 1 && (
        <label className="workspace-form-stack">
          Source version
          <select
            value={material.version_id}
            disabled={navigationBlocked}
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
            disabled={navigationBlocked}
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
          data-source-request={sourceAnchor}
          data-source-valid={hasPassage}
          tabIndex={-1}
          className="daily-source-panel"
          data-active={active === "source"}
          aria-labelledby="retained-source-title"
        >
          <div className="daily-section-heading">
            <h2 id="retained-source-title">
              {pdfActive
                ? "Retained document excerpts"
                : material.abstract
                  ? sourceScope === "excerpt"
                    ? "Retained feed excerpt"
                    : "Retained source abstract"
                  : knownPDF ? "Retained PDF excerpts" : "Source metadata"}
            </h2>
            <span>{material.version_label}</span>
          </div>
          {anchorMatch && !validAnchor && <p className="workspace-version-notice">This passage is unavailable in this retained version. Your draft and saved anchor have not changed.</p>}
          {!pdfActive && (
            <>
              <p className="daily-source-attribution">
                Source text, not a generated summary. Retained{" "}
                {displayDate(material.fetched_at)}. Select a passage to anchor
                your next note.
              </p>
              <div className="daily-source-text">
                <p
                  ref={source}
                  onMouseUp={selectPassage}
                  onKeyUp={selectPassage}
                >
                  {hasPassage ? (
                    <>
                      {sourceCharacters.slice(0, start).join("")}
                      <mark id="source-anchor" data-source-anchor={sourceAnchor}>
                        {sourceCharacters.slice(start, end).join("")}
                      </mark>
                      {sourceCharacters.slice(end).join("")}
                    </>
                  ) : (
                    material.abstract ||
                    (knownPDF
                      ? "Retained PDF excerpts are available for this exact source version. Open their selected original pages below; omitted pages and unreliable structures remain outside the acquired reading scope."
                      : "No abstract or full text was acquired. Use the original-source link for reading. Your questions and notes can still be kept against this metadata version.")
                  )}
                </p>
              </div>
              {hasPassage && (
                <p className="workspace-note-context">
                  Resumed source passage at character offsets {start}–{end} of
                  this retained version.
                </p>
              )}
              <div className="daily-source-boundary">
                <span className="daily-eyebrow">Evidence boundary</span>
                <p>
                  Available scope: {knownPDF && !material.abstract ? knownPDF.scope : sourceScope}. The full methods, experiments,
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
            </>
          )}
          <RetainedSourceReader
            key={material.version_id}
            workId={item.work_id}
            versionId={material.version_id}
            anchor={sourceAnchor}
            onNavigate={setSourceAnchor}
            onSelect={(anchor, quote) => {
              if (savingDraft) return;
              setSourceAnchor(anchor);
              setSelection(quote);
              edit({ anchor });
            }}
            onActive={setPdfActive}
            announce={setNotice}
          />
        </section>
        <aside
          id="understand"
          tabIndex={-1}
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
          {workbenchOpened ? <Suspense fallback={<p className="daily-muted" aria-busy="true">Opening synthetic workbench…</p>}><SyntheticWorkbench
            key={material.version_id}
            workId={item.work_id}
            versionId={material.version_id}
            announce={setNotice}
            onSource={(anchor) => {
              jumpToSource.current = true;
              setSourceAnchor(anchor);
              setActive("source");
              window.history.replaceState(
                null,
                "",
                `${window.location.pathname}${window.location.search}#${encodeURIComponent(anchor)}`,
              );
              void reading(item.reading.status, anchor);
            }}
          /></Suspense> : <button type="button" className="daily-secondary" onClick={() => tab("understand")}>Open synthetic workbench · $0</button>}
          <GenerationBoundary />
        </aside>
        <section
          id="notes"
          tabIndex={-1}
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
                disabled={savingDraft}
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
                id="workspace-note-body"
                required
                rows={6}
                maxLength={10000}
                value={draft.body}
                readOnly={savingDraft}
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
              {draft.body && (
                <button
                  type="button"
                  className="daily-text-button"
                  disabled={savingDraft}
                  onClick={() => {
                    try {
                      storeDraft(
                        owner,
                        item.work_id,
                        material.version_id,
                        null,
                      );
                    } catch {
                      setDraftStorage(false);
                    }
                    setDraft(emptyDraft(sourceScope));
                    setNotice(
                      "Editing stopped. The saved note was not changed.",
                    );
                  }}
                >
                  {draft.revision > 0 ? "Cancel edit" : "Discard unsaved draft"}
                </button>
              )}
            </div>
          </form>
          <div className="daily-saved-entries">
            <h3>Saved against this version</h3>
            {entries.length === 0 && (
              <p>No server-saved notes for this version yet.</p>
            )}
            {entries.map((entry) => (
              <article
                key={entry.id}
                id={`workspace-entry-${entry.id}`}
                tabIndex={-1}
                className={
                  initial.entryId === entry.id
                    ? "workspace-focused-entry"
                    : undefined
                }
                aria-label={`Saved ${entry.kind.replaceAll("-", " ")}`}
              >
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
                  disabled={savingDraft}
                  onClick={() => editEntry(entry)}
                >
                  Edit {entry.kind.replaceAll("-", " ")}
                </button>
                <a
                  href={readerHref(
                    item,
                    entry.version_id,
                    entry.anchor,
                    undefined,
                    returnTo,
                  )}
                  className="daily-link"
                >
                  Source context →
                </a>
                <button
                  className="daily-text-button"
                  disabled={busy}
                  onClick={() =>
                    void pin(
                      state.profile.data.pinned_entry_id === entry.id
                        ? null
                        : entry.id,
                    )
                  }
                >
                  {state.profile.data.pinned_entry_id === entry.id
                    ? "Unpin saved item"
                    : `Pin ${entry.kind.replaceAll("-", " ")}`}
                </button>
              </article>
            ))}
            {otherEntries.length > 0 && (
              <div className="workspace-version-notice">
                <h3>Notes on other source versions</h3>
                {otherEntries.map((entry) => (
                  <p key={entry.id}>
                    <a
                      className="daily-link"
                      href={readerHref(
                        item,
                        entry.version_id,
                        entry.anchor,
                        entry.id,
                        returnTo,
                      )}
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
    </div>
  );
}
