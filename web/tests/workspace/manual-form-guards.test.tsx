import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useManualForm, useDraftGuard } from "@/lib/workspace/useManualForm";
import { rememberDraft, resetDraftMemory } from "@/lib/workspace/draftMemory";
const key = 'arxiv.workspace.manual-draft.v1:["owner","scope"]';
const valid = { id: "fixed", revision: 1, values: { title: "Private edit" } };
beforeEach(() => { sessionStorage.clear(); resetDraftMemory(); });
afterEach(() => vi.restoreAllMocks());
const hook = () => useManualForm("owner", "scope", "fixed", 1, { title: "" });
describe("private manual draft validation and guard boundaries", () => {
  it.each([null, { ...valid, id: "other" }, { ...valid, revision: -1 }, { ...valid, revision: 1.5 }, { ...valid, values: {} }, { ...valid, attempt: { id: 7, fingerprint: "x" } }, { ...valid, attempt: { id: "x", fingerprint: 7 } }])("refuses malformed browser recovery %# without a server write", bad => {
    sessionStorage.setItem(key, JSON.stringify(bad)); const { result } = renderHook(hook);
    expect(result.current.values.title).toBe(""); expect(result.current.storage).toBe(false); expect(result.current.dirty).toBe(false);
  });
  it("refuses oversized recovery and corrupt in-memory recovery", () => {
    sessionStorage.setItem(key, "x".repeat(250001)); const first = renderHook(hook); expect(first.result.current.storage).toBe(false); first.unmount();
    rememberDraft(key, { ...valid, values: {} }); const second = renderHook(hook); expect(second.result.current.values.title).toBe(""); expect(second.result.current.storage).toBe(false);
  });
  it("validates generated entity kind while recovering its original stable identity", () => {
    const id = `project-${"a".repeat(32)}`; sessionStorage.setItem(key, JSON.stringify({ ...valid, id }));
    const { result } = renderHook(() => useManualForm("owner", "scope", `project-${"b".repeat(32)}`, 0, { title: "" }, true));
    expect(result.current.draft.id).toBe(id); expect(result.current.values.title).toBe("Private edit");
  });
  it("retains edits when storage fills and refuses stale, fractional or busy rebases", () => {
    const { result } = renderHook(hook);
    act(() => result.current.change("title", "x".repeat(250001))); expect(result.current.storage).toBe(false); expect(result.current.dirty).toBe(true);
    act(() => { result.current.rebase(0); result.current.rebase(1.5); }); expect(result.current.draft.revision).toBe(1);
    act(() => result.current.setBusy(true)); act(() => result.current.rebase(2)); expect(result.current.draft.revision).toBe(1);
    act(() => result.current.setBusy(false)); act(() => result.current.rebase(2)); expect(result.current.draft.revision).toBe(2);
    expect(result.current.notice).toContain("no write has been sent");
    sessionStorage.setItem(key, "malformed"); act(() => result.current.clear()); expect(result.current.storage).toBe(false); expect(result.current.dirty).toBe(false);
  });
  it("allows downloads, fragments, new tabs, modified clicks and non-links while blocking ordinary navigation", () => {
    const refuse = vi.fn();
    function Guard({ dirty, busy }: { dirty: boolean; busy: boolean }) { useDraftGuard(dirty, busy, refuse); return <><a href="/workspace/today">Leave</a><a href="#notes">Fragment</a><a href="/download" download>Download</a><a href="/new" target="_blank">New tab</a><button>Local</button></>; }
    const view = render(<Guard dirty busy={false} />);
    for (const name of ["Fragment", "Download", "New tab"]) fireEvent.click(screen.getByText(name));
    fireEvent.click(screen.getByText("Local"));
    for (const modifiers of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) fireEvent.click(screen.getByText("Leave"), modifiers);
    expect(refuse).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Leave")); expect(refuse).toHaveBeenCalledOnce();
    const unload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unload); expect(unload.defaultPrevented).toBe(true);
    view.rerender(<Guard dirty={false} busy />); const pendingUnload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(pendingUnload); expect(pendingUnload.defaultPrevented).toBe(false);
    view.rerender(<Guard dirty={false} busy={false} />); fireEvent.click(screen.getByText("Leave")); expect(refuse).toHaveBeenCalledOnce();
  });
});
