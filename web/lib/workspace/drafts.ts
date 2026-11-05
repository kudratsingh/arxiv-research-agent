/** Unsaved authored text only. Scope is account + immutable source version. */
export const DRAFT_KEY = "arxiv-agent.workspace-drafts.v1";
export interface ReaderDraft {
  id: string;
  revision: number;
  body: string;
  kind: "question" | "note" | "next-action";
  anchor: string;
}
type Drafts = { version: 1; entries: Record<string, ReaderDraft> };
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
  if (
    typeof entry.id !== "string" ||
    typeof entry.revision !== "number" ||
    typeof entry.body !== "string" ||
    entry.body.length > 10_000 ||
    !["question", "note", "next-action"].includes(entry.kind) ||
    typeof entry.anchor !== "string"
  )
    throw new Error("Malformed saved draft");
  return entry;
}
export function storeDraft(
  owner: string,
  work: string,
  version: string,
  draft: ReaderDraft | null,
) {
  const data = parse(sessionStorage.getItem(DRAFT_KEY));
  const id = scope(owner, work, version);
  if (draft === null) delete data.entries[id];
  else data.entries[id] = draft;
  const raw = JSON.stringify(data);
  if (Object.keys(data.entries).length > 40 || raw.length > 250_000)
    throw new Error("Draft storage is full");
  sessionStorage.setItem(DRAFT_KEY, raw);
}

export const DRAFT_NAVIGATION_NOTICE = "Save or copy your unsaved text before leaving this source version. Browser draft recovery is unavailable.";
