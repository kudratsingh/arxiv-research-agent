import { describe, expect, it, vi } from "vitest";
import { libraryQueue, neighbours, readerTarget, resolveFocus, todayEditionQueue, todayQueue } from "@/lib/workspace/queue";
import type { ReadingData, WorkItem } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";
import { available } from "./materialFixtures";

const now = new Date("2026-11-03T12:00:00Z");
const item = (id: string) => work({ work_id: id });
function edition(works: WorkItem[]) {
  const state = workspace({ works });
  state.editions[0]!.work_ids = works.map((value) => value.work_id);
  return state;
}
describe("controller queues", () => {
  it("retains edition order and does not invent missing works or versions", () => {
    const a = item("a"), b = item("b"), c = item("c");
    const state = edition([b, c, a]);
    state.editions[0]!.work_ids = ["a", "missing", "b", "c"];
    state.editions[0]!.work_versions = { a: a.versions[0]!.version_id, c: "missing-version" };
    const before = structuredClone(state);
    const queue = todayEditionQueue(state);
    expect(queue.map((value) => value.work_id)).toEqual(["a", "b"]);
    expect(queue[0]).toMatchObject({
      version_id: a.versions[0]!.version_id, version_label: "v1", title: a.versions[0]!.title,
      url: a.versions[0]!.url, authors: a.versions[0]!.authors,
      abstract: a.versions[0]!.abstract, access_state: "abstract", content_hash: "digest-1",
    });
    expect(queue[1]).toBe(b);
    expect(state).toEqual(before);
    expect(todayEditionQueue(workspace({ editions: [] }))).toEqual([]);
  });
  it("uses current title, URL and authors only when pinned metadata is empty", () => {
    const a = work();
    Object.assign(a.versions[0]!, { title: "", url: "", authors: [] });
    const state = edition([a]);
    state.editions[0]!.work_versions[a.work_id] = a.versions[0]!.version_id;
    expect(todayEditionQueue(state)[0]).toMatchObject({ title: a.title, url: a.url, authors: a.authors });
  });
  it.each([
    ["unread", null, true], ["saved", null, true], ["read", null, true],
    ["dismissed", null, false], ["archived", null, false],
    ["snoozed", null, true], ["snoozed", "2026-11-03T11:59:59Z", true],
    ["snoozed", "2026-11-03T12:00:00Z", true],
    ["snoozed", "2026-11-03T12:00:01Z", false], ["snoozed", "invalid", false],
  ] as const)("preserves %s / %s visibility", (status, snoozed_until, visible) => {
    const a = work();
    a.reading = { ...a.reading, status, snoozed_until };
    expect(todayQueue(edition([a]), now)).toEqual(visible ? [a] : []);
  });
  it("uses the current clock when the caller omits one", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(now);
      expect(todayQueue(edition([work()]))).toHaveLength(1);
    } finally { vi.useRealTimers(); }
  });
  it("preserves Library filters, order, and notes on otherwise unread work", () => {
    const statuses: ReadingData["status"][] = ["saved", "read", "archived", "unread", "dismissed"];
    const works = statuses.map((status) => {
      const value = item(status); value.reading.status = status; return value;
    });
    const withNote = item("noted");
    withNote.entries = [{ id: "entry", revision: 1, kind: "question", body: "Why?", anchor: "abstract:0",
      version_id: withNote.version_id, work_id: withNote.work_id, updated_at: "", activity_sequence: 1 }];
    const state = workspace({ works: [...works, withNote] });
    for (const view of ["saved", "read", "archived"]) {
      expect(libraryQueue(state, view).map((value) => value.work_id)).toEqual([view]);
    }
    expect(libraryQueue(state, "notes")).toEqual([withNote]);
    expect(libraryQueue(state, "all").map((value) => value.work_id)).toEqual(["saved", "read", "archived", "dismissed", "noted"]);
    expect(libraryQueue(state, "unknown")).toEqual([works[0]]);
  });
});

describe("focused selection", () => {
  const a = item("a"), b = item("b"), c = item("c"), d = item("d");
  it("selects a visible id, falls back for unknown ids, and handles empty queues", () => {
    expect(resolveFocus([a, b], ["a", "b"], "b")).toBe(b);
    expect(resolveFocus([a, b], ["a", "b"], "unknown")).toBe(a);
    expect(resolveFocus([a, b], ["a", "b"], null)).toBe(a);
    expect(resolveFocus([], ["a"], "a")).toBeNull();
    expect(resolveFocus([], [], null)).toBeNull();
  });
  it("uses full edition order to advance past removed works or fall back to the previous one", () => {
    expect(resolveFocus([d, a], ["a", "b", "c", "d"], "b")).toBe(d);
    expect(resolveFocus([a], ["a", "b", "c", "d"], "d")).toBe(a);
    expect(resolveFocus([a], ["b", "c"], "b")).toBe(a);
    expect(resolveFocus([a, b, c], ["a", "b", "c"], "b")).toBe(b);
  });
  it("reports zero-based position and bounded neighbours without wrapping", () => {
    expect(neighbours([a, b, c], "b")).toEqual({ previous: a, next: c, index: 1, count: 3 });
    expect(neighbours([a, b], "a")).toEqual({ previous: null, next: b, index: 0, count: 2 });
    expect(neighbours([a, b], "b")).toEqual({ previous: a, next: null, index: 1, count: 2 });
    expect(neighbours([a], "a")).toEqual({ previous: null, next: null, index: 0, count: 1 });
    expect(neighbours([a], "unknown")).toEqual({ previous: null, next: null, index: -1, count: 1 });
    expect(neighbours([], null)).toEqual({ previous: null, next: null, index: -1, count: 0 });
  });
});

describe("reader target continuity", () => {
  it("uses latest material initially, then the saved version and anchor", () => {
    const a = work();
    expect(readerTarget(a)).toEqual({ version: a.version_id, anchor: "abstract:0" });
    a.reading = { ...a.reading, revision: 1, version_id: a.versions[0]!.version_id, anchor: "notes" };
    expect(readerTarget(a)).toEqual({ version: a.versions[0]!.version_id, anchor: "notes" });
    expect(readerTarget(a, a.version_id)).toEqual({ version: a.version_id, anchor: "abstract:0" });
  });
  it("uses a PDF first anchor unless a matching saved revision supplies its own", () => {
    const a = work({ retained_materials: [available()] });
    expect(readerTarget(a).anchor).toBe(available().first_anchor);
    a.reading = { ...a.reading, revision: 1, version_id: a.version_id, anchor: "understand" };
    expect(readerTarget(a).anchor).toBe("understand");
    a.reading.revision = 0;
    expect(readerTarget(a).anchor).toBe(available().first_anchor);
    a.versions[1]!.retained_materials[0]!.first_anchor = null;
    expect(readerTarget(a).anchor).toBe("abstract:0");
  });
});
