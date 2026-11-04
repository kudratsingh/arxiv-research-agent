import type { ProfileData } from "./api";

export interface InterestDraft {
  version: 1;
  baseRevision: number;
  data: ProfileData;
  customRaw: string | null;
  exclusionsRaw: string | null;
  attempt?: { fingerprint: string; id: string };
}
const MAX_BYTES = 250_000;
function key(owner: string) { return `arxiv.workspace.interest-draft.v1:${encodeURIComponent(owner)}`; }
function strings(value: unknown, limit: number): value is string[] {
  return Array.isArray(value) && value.length <= limit && value.every((item) => typeof item === "string" && item.length <= 500);
}
function parse(raw: string): InterestDraft {
  if (raw.length > MAX_BYTES) throw new Error("Local interest draft is too large");
  const draft = JSON.parse(raw) as InterestDraft;
  const data = draft?.data;
  if (draft?.version !== 1 || !Number.isInteger(draft.baseRevision) || draft.baseRevision < 0 || !data ||
    !strings(data.topics, 500) || !strings(data.custom_topics, 100) || !strings(data.exclusions, 100) || !strings(data.streams, 20) ||
    ![5, 15, 45].includes(data.minutes) || typeof data.research_question !== "string" || data.research_question.length > 2000 ||
    typeof data.exploration !== "number" || !Number.isFinite(data.exploration) || data.exploration < 0 || data.exploration > .3 ||
    !(data.pinned_entry_id === null || typeof data.pinned_entry_id === "string" && data.pinned_entry_id.length > 0 && data.pinned_entry_id.length <= 120) ||
    !(draft.customRaw === null || typeof draft.customRaw === "string") || !(draft.exclusionsRaw === null || typeof draft.exclusionsRaw === "string") ||
    draft.attempt !== undefined && (typeof draft.attempt.fingerprint !== "string" || typeof draft.attempt.id !== "string" || !draft.attempt.id || draft.attempt.id.length > 120)) {
    throw new Error("Unsupported local interest draft");
  }
  return draft;
}
export function loadInterestDraft(owner: string): InterestDraft | null {
  const raw = sessionStorage.getItem(key(owner));
  return raw === null ? null : parse(raw);
}
/** Preserve an unreadable original rather than replacing private authored text. */
export function storeInterestDraft(owner: string, draft: InterestDraft | null) {
  const raw = sessionStorage.getItem(key(owner));
  if (raw !== null) parse(raw);
  if (draft === null) { sessionStorage.removeItem(key(owner)); return; }
  const next = JSON.stringify(draft);
  parse(next);
  sessionStorage.setItem(key(owner), next);
}
/** Only the explicit discard action may remove an unreadable local original. */
export function discardInterestDraft(owner: string) { sessionStorage.removeItem(key(owner)); }
