"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
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

export function CandidateReview() {
  const { state, error: stateError, reload } = useWorkspace();
  const selectedPacket = useSearchParams().get("packet");
  const [index, setIndex] = useState<ReviewIndex | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preparing, setPreparing] = useState(false);
  const attempts = useRef(new Map<string, string>());
  useEffect(() => {
    const controller = new AbortController();
    workspaceRequest<ReviewIndex>(
      `review${selectedPacket ? `?packet_id=${encodeURIComponent(selectedPacket)}` : ""}`,
      undefined,
      controller.signal,
    )
      .then((value) => {
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
    return () => controller.abort();
  }, [selectedPacket]);
  if (!state)
    return <LoadingState error={stateError} retry={() => void reload()} />;
  const packet = index?.packet;
  const wrongPacket = Boolean(selectedPacket && packet?.id !== selectedPacket);
  async function prepare() {
    if (!state) return;
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
        `/workspace/review?packet=${encodeURIComponent(packet.id)}`,
      );
      setError("");
      setNotice(
        "Candidate set prepared from stored metadata. Preparing a set supplies no usefulness judgments.",
      );
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
    try {
      const value = await workspaceRequest<ReviewIndex>(
        `review${selectedPacket ? `?packet_id=${encodeURIComponent(selectedPacket)}` : ""}`,
      );
      setIndex(value);
      setError("");
      await reload();
      setNotice(
        "Saved review reloaded. Unsaved judgments in this tab have been kept for reconciliation.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    }
  }
  return (
    <>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">
          Your usefulness judgments · no automatic labels
        </span>
        <Link className="daily-link" href="/workspace/today" prefetch={false}>
          Back to Today →
        </Link>
      </div>
      <div className="daily-intro">
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
      <div className="workspace-toolbar">
        <button
          className="daily-secondary"
          disabled={preparing || (!index && !error) || (wrongPacket && !error)}
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
          disabled={preparing}
          onClick={() => void reloadSaved()}
        >
          Reload saved review
        </button>
        {index && index.packet_ids.length > 1 && (
          <label>
            Saved candidate set
            <select
              value={selectedPacket ?? packet?.id ?? ""}
              onChange={(event) => {
                setIndex(null);
                setError("");
                window.history.pushState(
                  null,
                  "",
                  `/workspace/review?packet=${encodeURIComponent(event.target.value)}`,
                );
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
        <Message>{notice}</Message>
      </div>
      {error ? (
        <div className="workspace-alert">
          <p>{error}</p>
        </div>
      ) : !index || wrongPacket ? (
        <p className="daily-muted" aria-busy="true">
          Opening the saved candidate set…
        </p>
      ) : !packet ? (
        <section className="daily-empty">
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
          <details className="workspace-review-method">
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
          <Coverage sources={packet.coverage} />
          {packet.items.length === 0 ? (
            <section className="daily-empty">
              <h2>No eligible stored candidates.</h2>
              <p>
                The set contains no fictional filler. Check your source coverage
                and saved interests before preparing another review.
              </p>
            </section>
          ) : (
            packet.items.map((candidate, position) => (
              <CandidateFeedback
                key={`${packet.id}:${candidate.work.work_id}`}
                candidate={candidate}
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
    </>
  );
}

function CandidateFeedback({
  candidate,
  position,
  packetId,
  onSaved,
  announce,
}: {
  candidate: ReviewCandidate;
  position: number;
  packetId: string;
  onSaved: (value: UsefulnessFeedback) => void;
  announce: (message: string) => void;
}) {
  const [saved, setSaved] = useState(candidate.feedback);
  const [label, setLabel] = useState(candidate.feedback.label);
  const [reason, setReason] = useState(candidate.feedback.reason);
  const [busy, setBusy] = useState(false);
  const attempts = useRef(new Map<string, string>());
  const changed = label !== saved.label || reason !== saved.reason;
  const canSave = changed && (label !== null || saved.label !== null);
  const remoteChanged = candidate.feedback.revision > saved.revision;
  const item = candidate.work;
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!canSave) return;
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
          href={readerHref(
            item,
            item.version_id,
            `${candidate.evidence_scope}:0`,
            undefined,
            `/workspace/review?packet=${packetId}`,
          )}
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
        href={readerHref(
          item,
          item.version_id,
          `${candidate.evidence_scope}:0`,
          undefined,
          `/workspace/review?packet=${packetId}`,
        )}
        prefetch={false}
      >
        Inspect retained source →
      </Link>
      <form
        className="workspace-feedback"
        onSubmit={(event) => void save(event)}
      >
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
      </form>
    </article>
  );
}
