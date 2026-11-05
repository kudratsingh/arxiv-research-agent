/** Unsaved authored text only. Scope is account + immutable source version. */
import { forgetDraft, recallDraft, rememberDraft } from "./draftMemory";
export const DRAFT_KEY = "arxiv-agent.workspace-drafts.v1";
export interface ReaderDraft {
  id: string;
  revision: number;
  body: string;
  kind: "question" | "note" | "next-action";
  anchor: string;
}
type Drafts = { version: 1; entries: Record<string, ReaderDraft> };
function validate(entry: ReaderDraft) {
  if (typeof entry.id !== "string" || !Number.isInteger(entry.revision) || entry.revision < 0 ||
    typeof entry.body !== "string" || entry.body.length > 10_000 ||
    !["question", "note", "next-action"].includes(entry.kind) || typeof entry.anchor !== "string") throw new Error("Malformed saved draft");
  return entry;
}
function scope(owner: string, work: string, version: string) {
  return JSON.stringify([owner, work, version]);
}
function parse(raw: string | null): Drafts {
  if (!raw) return { version: 1, entries: {} };
  if (raw.length > 250_000) throw new Error("Draft storage is full");
  const result = JSON.parse(raw) as Drafts;
  if (
    result.version !== 1 ||
    !result.entries ||
    Array.isArray(result.entries) ||
    typeof result.entries !== "object"
  )
    throw new Error("Unknown draft format");
  return result;
}
export function loadDraft(
  owner: string,
  work: string,
  version: string,
): ReaderDraft | null {
  const entry = parse(sessionStorage.getItem(DRAFT_KEY)).entries[
    scope(owner, work, version)
  ];
  if (!entry) return null;
  return validate(entry);
}
export function storeDraft(
  owner: string,
  work: string,
  version: string,
  draft: ReaderDraft | null,
) {
  const memoryKey = `reader:${scope(owner, work, version)}`;
  if (draft) validate(draft);
  rememberDraft(memoryKey, { draft, persisted: false });
  const data = parse(sessionStorage.getItem(DRAFT_KEY));
  const id = scope(owner, work, version);
  if (draft === null) delete data.entries[id];
  else data.entries[id] = draft;
  const raw = JSON.stringify(data);
  if (Object.keys(data.entries).length > 40 || raw.length > 250_000)
    throw new Error("Draft storage is full");
  sessionStorage.setItem(DRAFT_KEY, raw);
  if (draft === null) forgetDraft(memoryKey);
  else rememberDraft(memoryKey, { draft, persisted: true });
}

export function recoverDraft(owner: string, work: string, version: string) {
  const memory = recallDraft<{ draft: ReaderDraft | null; persisted: boolean }>(`reader:${scope(owner, work, version)}`);
  try { const stored = loadDraft(owner, work, version); return { draft: memory ? memory.draft : stored, available: memory?.persisted ?? true }; }
  catch (failure) { if (memory) return { draft: memory.draft, available: false }; throw failure; }
}

export const DRAFT_NAVIGATION_NOTICE = "Save or copy your unsaved text before leaving this source version. Browser draft recovery is unavailable.";
