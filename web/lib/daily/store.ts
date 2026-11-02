import { RESEARCH_QUESTION, STREAMS } from "./profile";

/** the workspace ADR proposal: disposable preview data, never a job or credential store. */
export const PREVIEW_KEY = "arxiv-agent.workspace-preview.v1";
export interface Entry {
  id: string;
  itemId: string;
  kind: "question" | "note" | "next-action";
  body: string;
  anchor: string;
}
export interface PreviewData {
  revision: 1;
  topics: string[];
  customTopics: string[];
  configured: boolean;
  minutes: number;
  saved: string[];
  entries: Entry[];
  anchors: Record<string, string>;
  done: boolean;
  researchQuestion: string;
  streams: string[];
}
export const INITIAL_DATA: PreviewData = {
  revision: 1,
  topics: [...new Set(STREAMS.flatMap((stream) => stream.topics))],
  customTopics: [],
  configured: true,
  minutes: 15,
  saved: [],
  entries: [],
  anchors: {},
  done: false,
  researchQuestion: RESEARCH_QUESTION,
  streams: STREAMS.map((stream) => stream.id),
};
export interface PreviewSnapshot {
  data: PreviewData;
  storage: "pending" | "saved" | "unavailable";
}
const INITIAL: PreviewSnapshot = { data: INITIAL_DATA, storage: "pending" };
const MAX_BYTES = 200_000;

export function parsePreview(raw: string | null): PreviewData {
  if (!raw) return INITIAL_DATA;
  if (raw.length > MAX_BYTES) throw new Error("preview record too large");
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object") throw new Error("invalid preview");
  const d = value as PreviewData;
  d.researchQuestion ??= RESEARCH_QUESTION;
  d.streams ??= STREAMS.map((stream) => stream.id);
  const strings = (v: unknown): v is string[] =>
    Array.isArray(v) &&
    v.length <= 500 &&
    v.every((x) => typeof x === "string" && x.length <= 500);
  if (
    typeof d.researchQuestion !== "string" ||
    d.researchQuestion.length > 2000 ||
    !strings(d.streams) ||
    d.revision !== 1 ||
    !strings(d.topics) ||
    !strings(d.customTopics) ||
    !strings(d.saved) ||
    typeof d.configured !== "boolean" ||
    typeof d.done !== "boolean" ||
    ![5, 15, 45].includes(d.minutes) ||
    !Array.isArray(d.entries) ||
    d.entries.length > 200 ||
    !d.anchors ||
    typeof d.anchors !== "object" ||
    Array.isArray(d.anchors) ||
    !Object.values(d.anchors).every(
      (a) =>
        typeof a === "string" && ["source", "understand", "notes"].includes(a),
    ) ||
    !d.entries.every(
      (e) =>
        e &&
        typeof e.id === "string" &&
        typeof e.itemId === "string" &&
        ["question", "note", "next-action"].includes(e.kind) &&
        typeof e.body === "string" &&
        e.body.length <= 4000 &&
        typeof e.anchor === "string",
    )
  ) {
    throw new Error("invalid preview record");
  }
  return d;
}

export function createPreviewStore(
  storage: () => Pick<Storage, "getItem" | "setItem">,
) {
  let snapshot = INITIAL;
  let loaded = false;
  const listeners = new Set<() => void>();
  return {
    getSnapshot: () => snapshot,
    getServerSnapshot: () => INITIAL,
    subscribe(listener: () => void) {
      listeners.add(listener);
      if (!loaded) {
        loaded = true;
        try {
          snapshot = {
            data: parsePreview(storage().getItem(PREVIEW_KEY)),
            storage: "saved",
          };
        } catch {
          snapshot = { data: INITIAL_DATA, storage: "unavailable" };
        }
      }
      return () => {
        listeners.delete(listener);
      };
    },
    update(change: (current: PreviewData) => PreviewData) {
      const data = change(snapshot.data);
      let status: PreviewSnapshot["storage"] = "saved";
      try {
        const raw = JSON.stringify(data);
        parsePreview(raw);
        storage().setItem(PREVIEW_KEY, raw);
      } catch {
        status = "unavailable";
      }
      snapshot = { data, storage: status };
      listeners.forEach((listener) => listener());
    },
  };
}

export const previewStore = createPreviewStore(() => window.localStorage);
