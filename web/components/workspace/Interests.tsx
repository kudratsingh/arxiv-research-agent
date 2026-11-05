"use client";
import Link from "next/link";
import { lazy, Suspense, useEffect, useId, useRef, useState } from "react";
import { STREAMS } from "@/lib/daily/profile";
import {
  errorMessage,
  requestId,
  workspaceRequest,
  type ProfileData,
  type WorkspaceState,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { LoadingState, Message, ServiceNotice } from "./Common";
import { AllocationReceipt } from "./AllocationReceipt";
import { InterestCoverage } from "./InterestCoverage";
import { ControlBar, SidebarSection } from "./Slots";
import { Mascot } from "./Mascot";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";
import { loadInterestDraft, storeInterestDraft, discardInterestDraft, type InterestDraft } from "@/lib/workspace/interestDrafts";

const InterestTopics = lazy(() => import("./InterestTopics"));
function lines(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function LiveInterests() {
  const { state, setState, error, reload } = useWorkspace();
  if (!state) return <div className="ws-interests-state"><Mascot mood={error ? "alert" : "busy"} /><LoadingState error={error} retry={() => void reload()} /></div>;
  return <InterestsEditor key={state.principal_key_id} state={state} setState={setState} error={error} />;
}

function InterestsEditor({ state, setState, error }: { state: WorkspaceState; setState: (value: WorkspaceState) => void; error: string }) {
  const owner = state.principal_key_id;
  const [recovery] = useState(() => {
    try { const value = loadInterestDraft(owner); return { value, available: true }; }
    catch { return { value: null, available: false }; }
  });
  const [draft, setDraft] = useState<ProfileData | null>(recovery.value?.data ?? null);
  const [baseRevision, setBaseRevision] = useState<number | null>(recovery.value?.baseRevision ?? null);
  const [notice, setNotice] = useState(recovery.value
    ? "Recovered local interest edits for this account. Review before saving; opening this page has not changed your saved preferences."
    : recovery.available ? "" : "Browser interest-draft recovery is unavailable. Keep this tab open or copy your changes before leaving.");
  const [draftStorage, setDraftStorage] = useState(recovery.available);
  const formId = `workspace-interests-${useId()}`;
  const [busy, setBusy] = useState(false);
  const [customRaw, setCustomRaw] = useState<string | null>(recovery.value?.customRaw ?? null);
  const [exclusionsRaw, setExclusionsRaw] = useState<string | null>(recovery.value?.exclusionsRaw ?? null);
  const attempts = useRef(new Map<string, string>(recovery.value?.attempt ? [[recovery.value.attempt.fingerprint, recovery.value.attempt.id]] : []));
  const data = draft ?? state.profile.data;
  const unsafeDraft = draft !== null && !draftStorage;
  useEffect(() => {
    if (!unsafeDraft && !busy) return;
    const click = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.hasAttribute("download") || link.target === "_blank" || link.getAttribute("href")?.startsWith("#")) return;
      event.preventDefault(); event.stopPropagation();
      setNotice(unsafeDraft ? "Save or copy your interest changes before leaving. Browser draft recovery is unavailable." : "Wait for this preference save to finish before leaving.");
    };
    const unload = (event: BeforeUnloadEvent) => { if (unsafeDraft) { event.preventDefault(); event.returnValue = ""; } };
    document.addEventListener("click", click, true); window.addEventListener("beforeunload", unload);
    return () => { document.removeEventListener("click", click, true); window.removeEventListener("beforeunload", unload); };
  }, [unsafeDraft, busy]);
  function cache(value: InterestDraft | null) {
    try { storeInterestDraft(owner, value); setDraftStorage(true); return true; }
    catch { setDraftStorage(false); return false; }
  }
  function change(next: Partial<ProfileData>, raw: { customRaw?: string; exclusionsRaw?: string } = {}) {
    if (busy) return;
    const nextData = { ...(draft ?? state.profile.data), ...next };
    const revision = baseRevision ?? state.profile.revision;
    setBaseRevision(revision); setDraft(nextData);
    if (raw.customRaw !== undefined) setCustomRaw(raw.customRaw);
    if (raw.exclusionsRaw !== undefined) setExclusionsRaw(raw.exclusionsRaw);
    const nextCustomRaw = raw.customRaw ?? customRaw, nextExclusionsRaw = raw.exclusionsRaw ?? exclusionsRaw;
    const fingerprint = JSON.stringify({ revision, data: { ...nextData,
      custom_topics: nextCustomRaw === null ? nextData.custom_topics : lines(nextCustomRaw),
      exclusions: nextExclusionsRaw === null ? nextData.exclusions : lines(nextExclusionsRaw) } });
    const attemptId = attempts.current.get(fingerprint);
    const retained = cache({ version: 1, baseRevision: revision, data: nextData, customRaw: nextCustomRaw, exclusionsRaw: nextExclusionsRaw,
      ...(attemptId ? { attempt: { fingerprint, id: attemptId } } : {}) });
    setNotice(retained ? "You have unsaved interest changes." : "You have unsaved interest changes. Browser recovery is unavailable; keep this tab open or copy them before leaving.");
  }
  async function discard() {
    if (busy) return;
    setBusy(true);
    try {
      const fresh = await workspaceRequest<WorkspaceState>("state");
      discardInterestDraft(owner);
      setState(fresh); setDraft(null); setBaseRevision(null); setCustomRaw(null); setExclusionsRaw(null); setDraftStorage(true);
      setNotice("Draft discarded at your request. Loading the saved server profile.");
    } catch (failure) { setNotice(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  function jump(id: string) {
    if (document.querySelector('.workspace-app [role="dialog"][aria-modal="true"]')) dispatchWorkspaceCommand("escape");
    requestAnimationFrame(() => { const section = document.getElementById(id); section?.focus({ preventScroll: true }); section?.scrollIntoView?.({ block: "start" }); });
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const payload = {
      revision: baseRevision ?? state.profile.revision,
      data: {
        ...data,
        custom_topics:
          customRaw === null ? data.custom_topics : lines(customRaw),
        exclusions:
          exclusionsRaw === null ? data.exclusions : lines(exclusionsRaw),
      },
    };
    const fingerprint = JSON.stringify(payload),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    cache({ version: 1, baseRevision: payload.revision, data, customRaw, exclusionsRaw, attempt: { fingerprint, id } });
    setBusy(true);
    try {
      const acknowledged = await workspaceRequest<WorkspaceState["profile"]>("profile", { ...payload, request_id: id });
      await workspaceRequest("edition", {});
      const fresh = await workspaceRequest<WorkspaceState>("state");
      setState(fresh);
      if (fresh.profile.revision !== acknowledged.revision) {
        setNotice("A different profile revision is now saved. Your local draft has been kept for review; no saved preferences were overwritten by reloading.");
        return;
      }
      const cleared = cache(null);
      setDraft(null);
      setBaseRevision(null);
      setCustomRaw(null);
      setExclusionsRaw(null);
      setNotice(
        cleared ? "Interests and research question saved on the server. A new edition uses this revision; earlier editions remain unchanged."
          : "Interests and research question saved on the server. The local recovery copy could not be cleared; keep it for reconciliation.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="ws-interests">
      <SidebarSection label="Interest sections"><h2>Your research lens</h2><nav aria-label="Interest sections">
        {[["interest-question", "Question & window"], ["interest-streams", "Streams"], ["interest-topics", "Topics"], ["interest-terms", "Terms & boundaries"], ["interest-coverage", "Coverage"]].map(([id, title]) => <a key={id} href={`#${id}`} onClick={(event) => { event.preventDefault(); jump(id!); }}>{title}</a>)}
      </nav><p className="workspace-note-context">Profile revision {state.profile.revision}</p></SidebarSection>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">
          Your research lens · revision {state.profile.revision}
        </span>
        <Link className="daily-link" href="/workspace/today" prefetch={false}>
          Back to Today →
        </Link>
      </div>
      <div className="daily-intro ws-interests-intro">
        <div>
          <h1>
            Follow a field.
            <br />
            <em>Or your own question.</em>
          </h1>
          <p>
            Explicit interests shape the next briefing. Your preferences stay
            editable.
          </p>
        </div>
      </div>
      <ServiceNotice error={error} />
      <form id={formId} onSubmit={(event) => void save(event)}>
        <fieldset className="ws-interest-fields" disabled={busy} aria-busy={busy}>
        <section className="daily-lens">
          <div id="interest-question" tabIndex={-1}>
            <label>
              Your current research question
              <textarea
                rows={4}
                maxLength={2000}
                value={data.research_question}
                onChange={(event) =>
                  change({ research_question: event.target.value })
                }
              />
            </label>
            <label>
              Daily reading window
              <select
                value={data.minutes}
                onChange={(event) =>
                  change({ minutes: Number(event.target.value) as 5 | 15 | 45 })
                }
              >
                <option value={5}>5 minutes</option>
                <option value={15}>15 minutes</option>
                <option value={45}>45 minutes</option>
              </select>
            </label>
          </div>
          <fieldset id="interest-streams" tabIndex={-1}>
            <legend>Your research streams</legend>
            {STREAMS.map((stream) => (
              <label key={stream.id}>
                <input
                  type="checkbox"
                  checked={data.streams.includes(stream.id)}
                  onChange={() =>
                    change({
                      streams: data.streams.includes(stream.id)
                        ? data.streams.filter((id) => id !== stream.id)
                        : [...data.streams, stream.id],
                    })
                  }
                />
                <span>
                  {stream.label}
                  <small>{stream.detail}</small>
                </span>
              </label>
            ))}
            <p className="daily-muted">
              Rocket Twin and spatial work have limited coverage in the
              currently connected ML/lab sources. A selected stream is not a
              claim of comprehensive monitoring.
            </p>
          </fieldset>
        </section>
        <div className="daily-interests-grid">
          <section id="interest-topics" tabIndex={-1}>
            <Suspense fallback={<p className="daily-muted" aria-busy="true">Loading the topic catalogue…</p>}>
              <InterestTopics selected={data.topics} coverage={state.interest_coverage} onChange={(topics) => change({ topics })} />
            </Suspense>
          </section>
          <aside className="daily-interest-summary" id="interest-terms" tabIndex={-1}>
            <h2>Your terms and boundaries</h2>
            <label>
              Custom interests or watch terms
              <span className="workspace-topic-count">One term per line</span>
              <textarea
                rows={5}
                value={customRaw ?? data.custom_topics.join("\n")}
                onChange={(event) => {
                  change({}, { customRaw: event.target.value });
                }}
                placeholder="agent memory&#10;sim-to-real control"
              />
            </label>
            <label>
              Exclude these terms
              <span className="workspace-topic-count">
                Exclusions take priority over positive matches
              </span>
              <textarea
                rows={4}
                value={exclusionsRaw ?? data.exclusions.join("\n")}
                onChange={(event) => {
                  change({}, { exclusionsRaw: event.target.value });
                }}
              />
            </label>
            <label>
              Exploration allocation
              <select
                value={data.exploration}
                onChange={(event) =>
                  change({ exploration: Number(event.target.value) })
                }
              >
                <option value={0}>0% · only explicit matches</option>
                <option value={0.15}>15% upper bound · round down</option>
                <option value={0.3}>30% upper bound · round down</option>
              </select>
            </label>
            <p className="daily-muted">
              The percentage caps the final edition’s item count. Small
              briefings can have zero exploration items; the allowance is never
              rounded up.
            </p>
            <div className="workspace-allocation-previews">
              <h3>Current saved preference, by reading window</h3>
              {state.allocation_previews.map((allocation) => (
                <AllocationReceipt
                  key={String(allocation.minutes)}
                  allocation={allocation}
                  minutes={
                    typeof allocation.minutes === "number"
                      ? allocation.minutes
                      : undefined
                  }
                  compact
                />
              ))}
              {draft && (
                <p className="daily-muted">
                  Save your draft to recalculate these slots for its actual
                  candidates and cap.
                </p>
              )}
            </div>
            <p>
              {data.topics.length} topics selected. Ranking shows the actual
              matching terms. Opening a paper does not rewrite your declared
              interests.
            </p>
          </aside>
        </div>
        <div id="interest-coverage" tabIndex={-1}><InterestCoverage
          coverage={state.interest_coverage}
          sources={state.sources}
          draft={draft !== null}
        /></div>
        </fieldset>
      </form>
      {!draftStorage && <p className="workspace-version-notice">Browser recovery is unavailable. A confirmed server save is durable; local draft text is not. Save or copy it before browser history navigation.</p>}
      <ControlBar><div className="workspace-toolbar ws-interests-actions">
        <span className="ws-unsaved" aria-live="polite">{draft ? "Unsaved interest changes" : `Saved profile · revision ${state.profile.revision}`}</span>
          <button className="daily-button" type="submit" form={formId} disabled={busy}>
            {busy ? "Saving interests…" : "Save interests and question"}
          </button>
          {draft && (
            <button
              type="button"
              className="daily-secondary"
              disabled={busy}
              onClick={() => void discard()}
            >
              Discard draft and reload saved profile
            </button>
          )}
          <Message>{notice}</Message>
        </div></ControlBar>
    </div>
  );
}
