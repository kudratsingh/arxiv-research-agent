import { describe, expect, it } from "vitest";
import {
  createPreviewStore,
  INITIAL_DATA,
  parsePreview,
  PREVIEW_KEY,
} from "@/lib/daily/store";

describe("isolated workspace preview continuity", () => {
  it("restores a versioned question and source anchor on a return visit", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => {
        values.set(key, value);
      },
    };
    const store = createPreviewStore(() => storage);
    const stop = store.subscribe(() => undefined);
    store.update((data) => ({
      ...data,
      anchors: { "corpus-shift": "notes" },
      entries: [
        {
          id: "question-1",
          itemId: "corpus-shift",
          kind: "question",
          body: "Is my corpus fixed?",
          anchor: "source",
        },
      ],
    }));
    expect([...values.keys()]).toEqual([PREVIEW_KEY]);
    const reopened = createPreviewStore(() => storage);
    reopened.subscribe(() => undefined);
    expect(reopened.getSnapshot().data.entries[0]?.body).toBe(
      "Is my corpus fixed?",
    );
    expect(reopened.getSnapshot().data.anchors["corpus-shift"]).toBe("notes");
    stop();
  });
  it("reports blocked storage and retains the current session", () => {
    const store = createPreviewStore(() => {
      throw new Error("blocked");
    });
    store.subscribe(() => undefined);
    expect(store.getSnapshot().storage).toBe("unavailable");
    store.update((d) => ({ ...d, done: true }));
    expect(store.getSnapshot().storage).toBe("unavailable");
    expect(store.getSnapshot().data.done).toBe(true);
  });
  it.each([
    "{",
    "null",
    JSON.stringify({ ...INITIAL_DATA, revision: 9 }),
    JSON.stringify({ ...INITIAL_DATA, topics: [2] }),
    JSON.stringify({ ...INITIAL_DATA, entries: [{ body: "bad" }] }),
    JSON.stringify({ ...INITIAL_DATA, anchors: { x: "unsafe" } }),
    "a".repeat(200001),
  ])("refuses corrupted or out-of-version records", (raw) => {
    expect(() => parsePreview(raw)).toThrow();
  });
  it("starts empty of invented user activity", () => {
    expect(parsePreview(null).entries).toEqual([]);
    expect(parsePreview(null).saved).toEqual([]);
    expect(parsePreview(null).researchQuestion).toContain(
      "controlled compute budget",
    );
  });
});
