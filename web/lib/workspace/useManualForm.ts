import { useEffect, useId, useRef, useState } from "react";
import { requestId } from "./api";
import { blockWorkspaceNavigation } from "./navigationGuard";
import { forgetDraft, recallDraft, rememberDraft } from "./draftMemory";

interface FormDraft { id: string; revision: number; values: Record<string, string>; attempt?: { fingerprint: string; id: string } }
function read(raw: string, fields: readonly string[], id: string, generated: boolean): FormDraft {
  if (raw.length > 250_000) throw new Error("Oversized form draft");
  const value = JSON.parse(raw) as FormDraft;
  if (!value || typeof value.id !== "string" || (generated ? !new RegExp(`^${id.split("-")[0]}-[a-f0-9]{32}$`).test(value.id) : value.id !== id) || !Number.isInteger(value.revision) || value.revision < 0 || !value.values ||
    fields.some(field => typeof value.values[field] !== "string") ||
    value.attempt && (typeof value.attempt.id !== "string" || typeof value.attempt.fingerprint !== "string")) throw new Error("Unsupported form draft");
  return value;
}
export function useDraftGuard(dirty: boolean, busy: boolean, refuse: () => void) {
  useEffect(() => {
    if (!dirty && !busy) return;
    const release = blockWorkspaceNavigation(refuse);
    const click = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.hasAttribute("download") || link.target === "_blank" || link.getAttribute("href")?.startsWith("#")) return;
      event.preventDefault(); event.stopPropagation(); refuse();
    };
    const unload = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    document.addEventListener("click", click, true); window.addEventListener("beforeunload", unload);
    return () => { release(); document.removeEventListener("click", click, true); window.removeEventListener("beforeunload", unload); };
  }, [dirty, busy, refuse]);
}
export function stableContextId(kind: "project" | "thread" | "artifact") { return `${kind}-${requestId().replaceAll("-", "")}`; }
function revealDraftSurface(id: string) {
  for (let node = document.getElementById(id); node; node = node.parentElement) if (node instanceof HTMLDetailsElement) node.setAttribute("open", "");
}
/** Private authored fields only; no server save is implied by browser recovery. */
export function useManualForm(owner: string, scope: string, id: string, revision: number, initial: Record<string, string>, generated = false) {
  const surfaceId = useId();
  const key = `arxiv.workspace.manual-draft.v1:${JSON.stringify([owner, scope])}`;
  const [recovery] = useState(() => {
    const memory = recallDraft<FormDraft>(key);
    try { const raw = sessionStorage.getItem(key); return { draft: memory ? read(JSON.stringify(memory), Object.keys(initial), id, generated) : raw ? read(raw, Object.keys(initial), id, generated) : null, available: true }; }
    catch {
      try { return { draft: memory ? read(JSON.stringify(memory), Object.keys(initial), id, generated) : null, available: false }; }
      catch { return { draft: null, available: false }; }
    }
  });
  const [draft, setDraft] = useState<FormDraft>(recovery.draft ?? { id, revision, values: initial });
  const draftRef = useRef(draft);
  const [dirty, setDirty] = useState(Boolean(recovery.draft));
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(recovery.draft ? "Recovered local edits. They are not saved on the server." : "");
  const [storage, setStorage] = useState(recovery.available);
  function cache(next: FormDraft) {
    draftRef.current = next; setDraft(next);
    try {
      rememberDraft(key, next);
      const prior = sessionStorage.getItem(key); if (prior) read(prior, Object.keys(initial), id, generated);
      const raw = JSON.stringify(next); if (raw.length > 250_000) throw new Error("Draft storage full");
      sessionStorage.setItem(key, raw); setStorage(true);
    } catch { setStorage(false); }
  }
  function change(field: string, value: string) { cache({ ...draftRef.current, values: { ...draftRef.current.values, [field]: value } }); setDirty(true); }
  function clear(explicitDiscard = false, values = initial) {
    forgetDraft(key);
    try { if (!explicitDiscard) { const raw = sessionStorage.getItem(key); if (raw) read(raw, Object.keys(initial), id, generated); } sessionStorage.removeItem(key); }
    catch { setStorage(false); }
    const fresh = { id, revision, values }; draftRef.current = fresh; setDraft(fresh); setDirty(false);
  }
  function attempt(payload: unknown) {
    const fingerprint = JSON.stringify(payload), previous = draftRef.current.attempt;
    const request = previous?.fingerprint === fingerprint ? previous.id : requestId();
    cache({ ...draftRef.current, attempt: { fingerprint, id: request } }); return request;
  }
  function rebase(nextRevision: number) {
    if (busy || !Number.isInteger(nextRevision) || nextRevision <= draftRef.current.revision) return;
    cache({ ...draftRef.current, revision: nextRevision, attempt: undefined }); setDirty(true);
    setNotice(`Local edits kept on reviewed revision ${nextRevision}. Review them, then explicitly save; no write has been sent.`);
  }
  useDraftGuard(dirty, busy, () => {
    revealDraftSurface(surfaceId);
    setNotice(busy ? "Wait for this save to finish before leaving." : "Save or explicitly discard these local edits before leaving.");
  });
  return { draft, values: draft.values, change, clear, attempt, rebase, dirty, busy, setBusy, notice, setNotice, storage, surfaceId };
}
