import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { recoverDraft, storeDraft } from "@/lib/workspace/drafts";
import { recoverInterestDraft, storeInterestDraft } from "@/lib/workspace/interestDrafts";
import { useManualForm } from "@/lib/workspace/useManualForm";
import { workspace } from "./fixtures";

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });
function unavailable() {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("disabled"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("disabled"); });
}
describe("current-document recovery without browser storage", () => {
  it("recovers exact Reader text and anchor across remount scope, never another account/work/version", () => {
    sessionStorage.clear(); unavailable();
    const draft = { id: "unsaved", revision: 0, kind: "question" as const, body: "Unsubmitted α question", anchor: "abstract:4:19" };
    expect(() => storeDraft("owner-a", "work-a", "v1", draft)).toThrow();
    expect(recoverDraft("owner-a", "work-a", "v1")).toEqual({ draft, available: false });
    for (const args of [["owner-b", "work-a", "v1"], ["owner-a", "work-b", "v1"], ["owner-a", "work-a", "v2"]] as const) expect(() => recoverDraft(args[0], args[1], args[2])).toThrow();
    expect(() => storeDraft("owner-a", "work-a", "v1", null)).toThrow();
    expect(recoverDraft("owner-a", "work-a", "v1").draft).toBeNull();
  });
  it("recovers independent preferences without changing their server base revision", () => {
    unavailable(); const draft = { version: 1 as const, baseRevision: 7, data: { ...workspace().profile.data, research_question: "Private unsaved question" }, customRaw: null, exclusionsRaw: null };
    expect(() => storeInterestDraft("owner", draft)).toThrow();
    expect(recoverInterestDraft("owner")).toEqual({ value: draft, available: false });
    expect(() => recoverInterestDraft("other")).toThrow();
  });
  it("recovers project form fields and retry identity after a client-history style unmount", () => {
    unavailable();
    let attempt = "";
    function Form() { const form = useManualForm("owner", "project-new", "stable-project", 3, { title: "" }); return <><input aria-label="Title" value={form.values.title} onChange={event => form.change("title", event.target.value)} /><button onClick={() => { attempt = form.attempt({ title: form.values.title, revision: form.draft.revision }); }}>Attempt</button><p>{form.draft.revision}</p><button onClick={() => form.clear(true)}>Discard</button></>; }
    const first = render(<Form />); fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Precise unsaved project" } }); fireEvent.click(screen.getByText("Attempt")); const original = attempt;
    first.unmount(); const second = render(<Form />);
    expect(screen.getByLabelText("Title")).toHaveValue("Precise unsaved project"); fireEvent.click(screen.getByText("Attempt")); expect(attempt).toBe(original);
    act(() => { fireEvent.click(screen.getByText("Discard")); }); second.unmount(); render(<Form />); expect(screen.getByLabelText("Title")).toHaveValue("");
  });
});
