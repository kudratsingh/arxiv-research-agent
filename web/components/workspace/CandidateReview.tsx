"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { blockWorkspaceNavigation } from "@/lib/workspace/navigationGuard";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  displayDate,
  errorMessage,
  readerHref,
  requestId,
  workspaceRequest,
  WorkspaceError,
  type ReviewCandidate,
  type ReviewIndex,
  type ReviewPacket,
  type UsefulnessFeedback,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { Coverage, LoadingState, Message, ServiceNotice } from "./Common";
import { ControlBar, SidebarSection, StageHeaderSlot } from "./Slots";
import { Mascot } from "./Mascot";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";
import { contextHref, useProductContext } from "@/lib/workspace/productContext";

type DraftReport = { changed: boolean; busy: boolean };
const DRAFT_WARNING = "Save or explicitly discard your unsaved judgments before changing candidate sets.";

export function CandidateReview() {
  const context = useProductContext();
  const { state, error: stateError, reload } = useWorkspace();
  const selectedPacket = useSearchParams().get("packet");
  const [index, setIndex] = useState<ReviewIndex | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preparing, setPreparing] = useState(false);
  const attempts = useRef(new Map<string, string>());
  const packetRead = useRef<AbortController | null>(null);
  const [current, setCurrent] = useState<{ packet: string; work: string } | null>(null);
  const [reports, setReports] = useState<Record<string, DraftReport>>({});
  const reportRef = useRef<Record<string, DraftReport>>({});
  const packetRef = useRef<string | null>(null);
  const [discardRevision, setDiscardRevision] = useState(0);
  const [reloading, setReloading] = useState(false);
  const reportDraft = useCallback((key: string, report: DraftReport | null) => {
    const previous = reportRef.current[key];
    if (report && previous?.changed === report.changed && previous?.busy === report.busy) return;
    if (!report && !previous) return;
    const next = { ...reportRef.current };
    if (report) next[key] = report; else delete next[key];
    reportRef.current = next;
    setReports(next);
  }, []);
  const dirtyCount = Object.values(reports).filter((report) => report.changed).length;
  const saving = Object.values(reports).some((report) => report.busy);
  const locked = preparing || reloading || saving;
  useEffect(() => {
    if (!dirtyCount && !locked) return;
    const refuse = () => setNotice(dirtyCount ? "Save or discard your unsaved judgments before leaving this review. You can open sources in a new tab to keep this review open." : "Wait for the current review request to finish before leaving.");
    const release = blockWorkspaceNavigation(refuse);
    const click = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.hasAttribute("download") || link.target === "_blank" || link.getAttribute("href")?.startsWith("#")) return;
      event.preventDefault(); event.stopPropagation();
      refuse();
    };
    const unload = (event: BeforeUnloadEvent) => { if (dirtyCount) { event.preventDefault(); event.returnValue = ""; } };
    document.addEventListener("click", click, true); window.addEventListener("beforeunload", unload);
    return () => { release(); document.removeEventListener("click", click, true); window.removeEventListener("beforeunload", unload); };
  }, [dirtyCount, locked]);

  useEffect(() => {
    if (packetRef.current && selectedPacket !== packetRef.current && Object.values(reportRef.current).some((report) => report.changed || report.busy)) {
      window.history.replaceState(window.history.state, "", contextHref(`/workspace/review?packet=${encodeURIComponent(packetRef.current)}`, context));
      setNotice(DRAFT_WARNING);
      return;
    }
    packetRead.current?.abort();
    const controller = new AbortController();
    packetRead.current = controller;
    workspaceRequest<ReviewIndex>(
      `review${selectedPacket ? `?packet_id=${encodeURIComponent(selectedPacket)}` : ""}`,
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (controller.signal.aborted) return;
        packetRef.current = value.packet?.id ?? null;
        setIndex(value);
        setError("");
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof WorkspaceError && failure.status === 404
              ? "This candidate review is unavailable in this account. No different packet has been substituted."
              : errorMessage(failure),
          );
      });
    return () => { controller.abort(); if (packetRead.current === controller) packetRead.current = null; };
  }, [selectedPacket, context]);
  if (!state)
    return <div className="ws-review-state"><Mascot mood={stateError ? "alert" : "busy"} size={72} /><LoadingState error={stateError} retry={() => void reload()} /></div>;
  const packet = index?.packet;
  const wrongPacket = Boolean(selectedPacket && packet?.id !== selectedPacket && !dirtyCount && !saving);
  const currentIndex = Math.max(0, packet?.items.findIndex((candidate) => current?.packet === packet.id && candidate.work.work_id === current.work) ?? 0);
  function closeDrawer() {
    if (document.querySelector('.workspace-app [role="dialog"][aria-modal="true"]')) dispatchWorkspaceCommand("escape");
  }
  function choose(position: number) {
    if (!packet || locked) return;
    const candidate = packet.items[position];
    if (!candidate) return;
    setCurrent({ packet: packet.id, work: candidate.work.work_id });
    document.getElementById(`review-candidate-${position + 1}`)?.scrollIntoView?.({ block: "nearest" });
    closeDrawer();
  }
  async function prepare() {
    if (!state || locked) return;
    if (dirtyCount) { setNotice(DRAFT_WARNING); return; }
    const input = { profile_revision: state.profile.revision };
    const fingerprint = JSON.stringify(input),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    setPreparing(true);
    try {
      const packet = await workspaceRequest<ReviewPacket>("review/prepare", {
        ...input,
        request_id: id,
      });
      attempts.current.delete(fingerprint);
      packetRef.current = packet.id;
      setIndex((previous) => ({
        packet,
        packet_ids: [
          packet.id,
          ...(previous?.packet_ids ?? []).filter(
            (existing) => existing !== packet.id,
          ),
        ],
      }));
      window.history.replaceState(
        null,
        "",
        contextHref(`/workspace/review?packet=${encodeURIComponent(packet.id)}`, context),
      );
      setError("");
      setNotice(
        "Candidate set prepared from stored metadata. Preparing a set supplies no usefulness judgments.",
      );
      closeDrawer();
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setPreparing(false);
    }
  }
  function saveAcknowledged(workId: string, feedback: UsefulnessFeedback) {
    setIndex((previous) => {
      if (!previous?.packet) return previous;
      const items = previous.packet.items.map((candidate) =>
        candidate.work.work_id === workId
          ? { ...candidate, feedback }
          : candidate,
      );
      return {
        ...previous,
        packet: {
          ...previous.packet,
          items,
          labelled_count: items.filter(
            (candidate) => candidate.feedback.label !== null,
          ).length,
        },
      };
    });
  }
  async function reloadSaved() {
    if (locked) return;
    packetRead.current?.abort();
    const controller = new AbortController();
    packetRead.current = controller;
    setReloading(true);
    try {
      const value = await workspaceRequest<ReviewIndex>(
        `review${packet?.id || selectedPacket ? `?packet_id=${encodeURIComponent(packet?.id || selectedPacket!)}` : ""}`,
        undefined, controller.signal,
      );
      if (controller.signal.aborted) return;
      if (packet && value.packet?.id !== packet.id) {
        setNotice("The requested candidate set was not returned. Your current review and unsaved judgments have been kept.");
        return;
      }
      packetRef.current = value.packet?.id ?? null;
      setIndex(value);
      setError("");
      await reload();
      setNotice(
        "Saved review reloaded. Unsaved judgments in this tab have been kept for reconciliation.",
      );
    } catch (failure) {
      if (!controller.signal.aborted) setNotice(errorMessage(failure));
    } finally { setReloading(false); }
  }
  return (
    <div className="ws-review">
      <StageHeaderSlot position={packet?.items.length ? { n: currentIndex + 1, N: packet.items.length } : undefined} />
      <div className="daily-page-meta">
        <span className="daily-eyebrow">
          Your usefulness judgments · no automatic labels
        </span>
        <Link className="daily-link" href={contextHref("/workspace/today", context)} prefetch={false}>
          Back to Today →
        </Link>
      </div>
      <div className="daily-intro ws-review-intro">
        <div>
          <h1>
            What deserves
            <br />
            <em>your attention?</em>
          </h1>
          <p>
            A finite candidate review for your current question. Your daily
            reading shortlist stays separate.
          </p>
        </div>
      </div>
      <ServiceNotice error={stateError} />
      <SidebarSection label="Review controls"><h2>Candidate sets</h2><div className="workspace-toolbar">
        <button
          className="daily-secondary"
          disabled={locked || dirtyCount > 0 || (!index && !error) || (wrongPacket && !error)}
          onClick={() => void prepare()}
        >
          {preparing
            ? "Preparing candidates…"
            : packet
              ? "Prepare another candidate set"
              : "Prepare up to 10 candidates"}
        </button>
        <button
          className="daily-secondary"
          disabled={locked}
          onClick={() => void reloadSaved()}
        >
          Reload saved review
        </button>
        {index && index.packet_ids.length > 1 && (
          <label>
            Saved candidate set
            <select
              disabled={locked || dirtyCount > 0}
              value={packet?.id ?? selectedPacket ?? ""}
              onChange={(event) => {
                if (locked || dirtyCount) { setNotice(DRAFT_WARNING); return; }
                setIndex(null);
                setError("");
                window.history.pushState(
                  null,
                  "",
                  contextHref(`/workspace/review?packet=${encodeURIComponent(event.target.value)}`, context),
                );
                closeDrawer();
              }}
            >
              {index.packet_ids.map((id) => (
                <option key={id} value={id}>
                  {id === packet?.id
                    ? "Current review"
                    : `Review ${id.slice(-8)}`}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {dirtyCount > 0 && <div className="workspace-version-notice"><p>{DRAFT_WARNING}</p><button type="button" disabled={locked} onClick={() => {
        reportRef.current = {}; setReports({}); setDiscardRevision((value) => value + 1);
        setNotice("Unsaved judgments discarded. Server-saved labels are unchanged.");
      }}>Discard unsaved judgments</button></div>}
      </SidebarSection>
      {packet && !wrongPacket && !error && <SidebarSection label="Review queue"><h2>Candidates</h2>
        <ol className="ws-queue ws-review-queue" aria-label="Candidate queue">{packet.items.map((candidate, position) => <li key={candidate.work.work_id}>
          <button type="button" className="ws-queue-row" aria-current={position === currentIndex ? "true" : undefined} disabled={locked} onClick={() => choose(position)} aria-label={`Show candidate ${position + 1} of ${packet.items.length}: ${candidate.work.title}`}>
            <span className="ws-queue-position" aria-hidden="true"><span className="ws-queue-number">{String(position + 1).padStart(2, "0")}</span></span>
            <span className="ws-queue-text"><span className="ws-queue-title">{candidate.work.title}</span><span className="ws-queue-meta">{candidate.feedback.label === null ? "Not labelled" : `Your label: ${candidate.feedback.label}`}</span></span>
          </button></li>)}</ol>
      </SidebarSection>}
      <ControlBar><div className="ws-review-bar" role="group" aria-label="Review navigation">
        <button type="button" data-command="prev" aria-keyshortcuts="K ArrowLeft" disabled={locked || !packet?.items.length || currentIndex === 0} onClick={() => choose(currentIndex - 1)}>Previous candidate</button>
        <span>{packet?.items.length ? `Candidate ${currentIndex + 1} of ${packet.items.length}` : "No current candidate"}</span>
        <button type="button" data-command="next" aria-keyshortcuts="J ArrowRight" disabled={locked || !packet?.items.length || currentIndex === packet.items.length - 1} onClick={() => choose(currentIndex + 1)}>Next candidate</button>
        <span className="ws-review-dirty">{dirtyCount ? `${dirtyCount} unsaved judgment${dirtyCount === 1 ? "" : "s"}` : "No unsaved judgments"}</span>
      </div>{dirtyCount > 0 && <p className="workspace-note-context">Save or discard before leaving. Sources can open in a new tab. Copy drafts before browser history navigation.</p>}<Message>{notice}</Message></ControlBar>
      {error ? (
        <div className="workspace-alert ws-review-state">
          <Mascot mood="alert" size={72} /><p>{error}</p>
        </div>
      ) : !index || wrongPacket ? (
        <div className="ws-review-state"><Mascot mood="busy" size={72} /><p className="daily-muted" aria-busy="true">Opening the saved candidate set…</p></div>
      ) : !packet ? (
        <section className="daily-empty"><Mascot mood="sleepy" size={72} />
          <h2>Choose a small set to review.</h2>
          <p>
            Preparing a set freezes up to ten actual stored source versions and
            their matching reasons. Each usefulness label starts blank. No new
            source check or model call is needed.
          </p>
        </section>
      ) : (
        <>
          <div className="daily-section-heading">
            <h2>
              {packet.items.length} candidates · {packet.labelled_count}{" "}
              labelled
            </h2>
            <span>
              Frozen {displayDate(packet.as_of)} · interests revision{" "}
              {packet.profile_revision}
            </span>
          </div>
          <p className="daily-muted workspace-review-intro">
            Useful, maybe and irrelevant describe relevance to your own research
            question. They do not certify scientific validity, change your
            declared interests, or approve model spending.
          </p>
          <SidebarSection label="Review method and coverage"><details className="workspace-review-method">
            <summary className="daily-link">How this set was selected</summary>
            <p>{packet.selection}</p>
            {packet.limitations.map((limit) => (
              <p className="daily-muted" key={limit}>
                {limit}
              </p>
            ))}
            <p className="workspace-note-context">
              Ranking policy {packet.policy_version} · {packet.id}
            </p>
          </details>
          <Coverage sources={packet.coverage} /></SidebarSection>
          {packet.items.length === 0 ? (
            <section className="daily-empty">
              <Mascot mood="sleepy" size={72} /><h2>No eligible stored candidates.</h2>
              <p>
                The set contains no fictional filler. Check your source coverage
                and saved interests before preparing another review.
              </p>
            </section>
          ) : (
            packet.items.map((candidate, position) => (
              <CandidateFeedback
                key={`${packet.id}:${candidate.work.work_id}:${discardRevision}`}
                candidate={candidate}
                current={position === currentIndex}
                blocked={preparing || reloading}
                onActivate={() => { if (!locked) setCurrent({ packet: packet.id, work: candidate.work.work_id }); }}
                onReport={reportDraft}
                position={position + 1}
                packetId={packet.id}
                onSaved={(value) =>
                  saveAcknowledged(candidate.work.work_id, value)
                }
                announce={setNotice}
              />
            ))
          )}
        </>
      )}
    </div>
  );
}

function CandidateFeedback({
  candidate,
  position,
  packetId,
  onSaved,
  announce,
  current, blocked, onActivate, onReport,
}: {
  candidate: ReviewCandidate;
  position: number;
  packetId: string;
  onSaved: (value: UsefulnessFeedback) => void;
  announce: (message: string) => void;
  current: boolean; blocked: boolean; onActivate: () => void;
  onReport: (key: string, report: DraftReport | null) => void;
}) {
  const context = useProductContext();
  const [saved, setSaved] = useState(candidate.feedback);
  const [label, setLabel] = useState(candidate.feedback.label);
  const [reason, setReason] = useState(candidate.feedback.reason);
  const [busy, setBusy] = useState(false);
  const attempts = useRef(new Map<string, string>());
  const changed = label !== saved.label || reason !== saved.reason;
  const canSave = changed && (label !== null || saved.label !== null);
  const remoteChanged = candidate.feedback.revision > saved.revision;
  const item = candidate.work;
  const reportKey = `${packetId}:${item.work_id}`;
  useEffect(() => { onReport(reportKey, { changed, busy }); }, [reportKey, changed, busy, onReport]);
  useEffect(() => () => onReport(reportKey, null), [reportKey, onReport]);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!canSave || busy || blocked) return;
    const input = {
      packet_id: packetId,
      work_id: item.work_id,
      version_id: item.version_id,
      revision: saved.revision,
      label,
      reason,
    };
    const fingerprint = JSON.stringify(input),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    setBusy(true);
    try {
      const next = await workspaceRequest<UsefulnessFeedback>(
        "review/feedback",
        { ...input, request_id: id },
      );
      setSaved(next);
      setLabel(next.label);
      setReason(next.reason);
      onSaved(next);
      announce(
        next.label === null
          ? "Usefulness label cleared on the server. The source and candidate set are unchanged."
          : `Your ${next.label} label is saved on the server for candidate ${position}.`,
      );
    } catch (failure) {
      announce(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article
      className="workspace-review-candidate daily-item"
      id={`review-candidate-${position}`}
      data-current={current} aria-current={current ? "true" : undefined}
      onFocusCapture={onActivate}
      aria-labelledby={`candidate-title-${position}`}
    >
      <div className="daily-item-meta">
        <span>Candidate {position}</span>
        <span>{item.version_label}</span>
        <span>{candidate.evidence_scope}</span>
        <span>
          {saved.label === null ? "Not labelled" : `Your label: ${saved.label}`}
        </span>
      </div>
      <h2 id={`candidate-title-${position}`}>
        <Link
          href={contextHref(readerHref(
            item,
            item.version_id,
            `${candidate.evidence_scope}:0`,
            undefined,
            contextHref(`/workspace/review?packet=${packetId}`, context),
          ), context)}
          prefetch={false}
        >
          {item.title}
        </Link>
      </h2>
      <p className="daily-item-change">
        {item.abstract
          ? `${Array.from(item.abstract).slice(0, 600).join("")}${Array.from(item.abstract).length > 600 ? "…" : ""}`
          : "Only source metadata and the original link are available for this item."}
      </p>
      <details className="daily-reason">
        <summary>Why it is in this review</summary>
        {candidate.matching_reason.map((matching) => (
          <p key={matching}>{matching}</p>
        ))}
      </details>
      <p className="workspace-note-context">
        {item.source_id} · {item.version_id} · {candidate.estimated_minutes}
        -minute reading estimate
      </p>
      <Link
        className="daily-link"
        href={contextHref(readerHref(
          item,
          item.version_id,
          `${candidate.evidence_scope}:0`,
          undefined,
          contextHref(`/workspace/review?packet=${packetId}`, context),
        ), context)}
        prefetch={false}
      >
        Inspect retained source →
      </Link>
      <form
        className="workspace-feedback"
        onSubmit={(event) => void save(event)}
      >
        <fieldset className="ws-review-feedback-fields" disabled={busy || blocked}>
        <fieldset>
          <legend>Your usefulness judgment for candidate {position}</legend>
          {(
            [
              ["useful", "Useful"],
              ["maybe", "Maybe"],
              ["irrelevant", "Irrelevant"],
            ] as const
          ).map(([value, title]) => (
            <label className="workspace-check-label" key={value}>
              <input
                data-command={current ? `label-${value}` : undefined}
                aria-keyshortcuts={current ? value === "useful" ? "1" : value === "maybe" ? "2" : "3" : undefined}
                type="radio"
                name={`feedback-${position}`}
                value={value}
                checked={label === value}
                onChange={() => setLabel(value)}
              />
              {title}
            </label>
          ))}
        </fieldset>
        <label>
          Optional reason for candidate {position}
          <textarea
            rows={2}
            maxLength={2000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <div className="workspace-card-actions">
          <button className="daily-secondary" disabled={busy || !canSave}>
            {busy
              ? "Saving judgment…"
              : `Save judgment for candidate ${position}`}
          </button>
          {saved.label !== null && (
            <button
              type="button"
              className="daily-text-button"
              disabled={busy}
              onClick={() => {
                setLabel(null);
                setReason("");
              }}
            >
              Clear this label
            </button>
          )}
        </div>
        {changed && (
          <p className="daily-muted">
            Unsaved judgment. The labelled count changes only after a server
            acknowledgement. Keep this tab open until it is saved.
          </p>
        )}
        {remoteChanged && (
          <div className="workspace-version-notice">
            <p>
              The saved judgment changed elsewhere. Your draft has been kept.
            </p>
            <button
              type="button"
              className="daily-text-button"
              onClick={() => {
                setSaved(candidate.feedback);
                setLabel(candidate.feedback.label);
                setReason(candidate.feedback.reason);
              }}
            >
              Discard draft and load saved judgment
            </button>
          </div>
        )}
        </fieldset>
      </form>
    </article>
  );
}
