import { afterEach, describe, expect, it } from "vitest";
import { discardInterestDraft, loadInterestDraft, storeInterestDraft, type InterestDraft } from "@/lib/workspace/interestDrafts";
import { workspace } from "./fixtures";
const storageKey = (owner: string) => `arxiv.workspace.interest-draft.v1:${encodeURIComponent(owner)}`;
function record(): InterestDraft { return { version: 1, baseRevision: 3, data: workspace().profile.data, customRaw: "agent memory\n\nfixed baseline\n", exclusionsRaw: "promotion\n", attempt: { fingerprint: "opaque matching payload", id: "same-retry-id" } }; }
afterEach(() => sessionStorage.clear());
describe("bounded account-scoped interest draft recovery", () => {
  it("retains raw edits, revision and retry identity only for their account, and clears only its record", () => {
    const first = record(), second = { ...record(), customRaw: "Another account's draft" };
    expect(loadInterestDraft("owner/a")).toBeNull();
    storeInterestDraft("owner/a", first); storeInterestDraft("owner-b", second);
    expect(loadInterestDraft("owner/a")).toEqual(first); expect(loadInterestDraft("owner-b")).toEqual(second);
    expect(loadInterestDraft("owner-a")).toBeNull();
    storeInterestDraft("owner/a", null); expect(loadInterestDraft("owner/a")).toBeNull(); expect(loadInterestDraft("owner-b")).toEqual(second);
    discardInterestDraft("owner-b"); expect(loadInterestDraft("owner-b")).toBeNull();
  });
  it("keeps a malformed private original intact until explicit discard", () => {
    const original = '{"version":0,"private":"CI synthetic original"}';
    sessionStorage.setItem(storageKey("owner-a"), original);
    expect(() => loadInterestDraft("owner-a")).toThrow();
    expect(() => storeInterestDraft("owner-a", record())).toThrow();
    expect(() => storeInterestDraft("owner-a", null)).toThrow();
    expect(sessionStorage.getItem(storageKey("owner-a"))).toBe(original);
    discardInterestDraft("owner-a"); expect(loadInterestDraft("owner-a")).toBeNull();
  });
  it("refuses oversized data before replacing the existing recovery copy", () => {
    const first = record(); storeInterestDraft("owner-a", first);
    expect(() => storeInterestDraft("owner-a", { ...first, customRaw: "x".repeat(250001) })).toThrow(/too large/);
    expect(loadInterestDraft("owner-a")).toEqual(first);
    sessionStorage.setItem(storageKey("owner-a"), "x".repeat(250001));
    expect(() => loadInterestDraft("owner-a")).toThrow(/too large/);
  });
  it.each([
    ["version", { version: 2 }], ["negative revision", { baseRevision: -1 }], ["fractional revision", { baseRevision: .5 }],
    ["missing data", { data: null }], ["bad raw terms", { customRaw: 1 }], ["bad raw exclusions", { exclusionsRaw: [] }],
    ["missing raw terms", { customRaw: undefined }], ["bad attempt ID", { attempt: { fingerprint: "body", id: 3 } }],
    ["empty attempt ID", { attempt: { fingerprint: "body", id: "" } }], ["oversized attempt ID", { attempt: { fingerprint: "body", id: "a".repeat(121) } }],
    ["bad fingerprint", { attempt: { fingerprint: {}, id: "id" } }],
  ])("refuses %s without editing saved preferences", (_label, patch) => {
    sessionStorage.setItem(storageKey("owner-a"), JSON.stringify({ ...record(), ...patch }));
    expect(() => loadInterestDraft("owner-a")).toThrow(/Unsupported/);
  });
  it.each([
    ["topics object", { topics: {} }], ["too many topics", { topics: Array(501).fill("topic") }], ["non-string topic", { topics: [1] }], ["oversized term", { topics: ["a".repeat(501)] }],
    ["custom terms", { custom_topics: null }], ["too many custom terms", { custom_topics: Array(101).fill("term") }],
    ["exclusions", { exclusions: "text" }], ["too many exclusions", { exclusions: Array(101).fill("term") }],
    ["streams", { streams: [false] }], ["too many streams", { streams: Array(21).fill("core") }],
    ["window", { minutes: 30 }], ["question type", { research_question: false }], ["question bound", { research_question: "a".repeat(2001) }],
    ["exploration type", { exploration: "0.15" }], ["negative exploration", { exploration: -.1 }], ["excess exploration", { exploration: .31 }],
    ["pin type", { pinned_entry_id: 5 }], ["empty pin", { pinned_entry_id: "" }], ["long pin", { pinned_entry_id: "a".repeat(121) }],
  ])("refuses malformed cached profile %s", (_label, patch) => {
    const value = record(); sessionStorage.setItem(storageKey("owner-a"), JSON.stringify({ ...value, data: { ...value.data, ...patch } }));
    expect(() => loadInterestDraft("owner-a")).toThrow(/Unsupported/);
  });
  it("accepts a bounded pin and null raw fields, and rejects nonfinite JSON numbers", () => {
    const value = record(); value.data.pinned_entry_id = "entry-a"; value.customRaw = null; value.exclusionsRaw = null; delete value.attempt;
    storeInterestDraft("owner-a", value); expect(loadInterestDraft("owner-a")).toEqual(value);
    sessionStorage.setItem(storageKey("owner-a"), JSON.stringify(value).replace('"exploration":0.15','"exploration":1e999'));
    expect(() => loadInterestDraft("owner-a")).toThrow(/Unsupported/);
    sessionStorage.setItem(storageKey("owner-a"), "null"); expect(() => loadInterestDraft("owner-a")).toThrow(/Unsupported/);
    sessionStorage.setItem(storageKey("owner-a"), "broken JSON"); expect(() => loadInterestDraft("owner-a")).toThrow();
  });
});
