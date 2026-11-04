import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveReader } from "@/components/workspace/Reader";
import { settleReaderTarget } from "@/lib/workspace/navigation";
import { work, workspace } from "./fixtures";
import type { WorkspaceState } from "@/lib/workspace/api";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(location.search) }));
vi.mock("@/lib/workspace/navigation", () => ({ settleReaderTarget: vi.fn() }));
let state: WorkspaceState;
beforeEach(() => {
  sessionStorage.clear(); vi.mocked(settleReaderTarget).mockClear();
  const item = work();
  const abstract = `${"Earlier source context. ".repeat(160)}EXACT FAR PASSAGE${" Later context.".repeat(30)}`;
  const start = abstract.indexOf("EXACT FAR PASSAGE");
  state = workspace({ works: [{ ...item, versions: item.versions.map((version) => ({ ...version, abstract })) }] });
  history.replaceState(null, "", `/workspace/items/${encodeURIComponent(item.work_id)}?version=${encodeURIComponent(item.version_id)}#abstract%3A${start}%3A${start + 17}`);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (new URL(url, location.origin).pathname.endsWith("/state")) return Response.json(state);
    throw new Error(`Unexpected request ${url}`);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Reader navigation targets", () => {
  it("resolves a valid far abstract range to its actual mark rather than the top of the source panel", async () => {
    render(<LiveReader id={state.works[0]!.work_id} />);
    await screen.findByRole("heading", { name: "Retained source abstract" });
    const mark = document.getElementById("source-anchor");
    expect(mark).toHaveTextContent("EXACT FAR PASSAGE");
    await waitFor(() => expect(settleReaderTarget).toHaveBeenCalledWith(mark));
    expect(settleReaderTarget).not.toHaveBeenCalledWith(document.getElementById("source"));
  });
  it("gives an explicitly requested saved entry priority over a simultaneous source fragment", async () => {
    const item = state.works[0]!;
    item.entries = [{ id: "saved-question", revision: 1, work_id: item.work_id, version_id: item.version_id, kind: "question", body: "Saved source question", anchor: "abstract:4:12", updated_at: "2026-11-02T16:00:00Z", activity_sequence: 1 }];
    const url = new URL(location.href); url.searchParams.set("entry", "saved-question"); history.replaceState(null, "", url);
    render(<LiveReader id={item.work_id} />); await screen.findByText("Saved source question");
    const entry = document.getElementById("workspace-entry-saved-question");
    await waitFor(() => expect(settleReaderTarget).toHaveBeenCalledWith(entry));
    expect(settleReaderTarget).not.toHaveBeenCalledWith(document.getElementById("source-anchor"));
  });
  it("falls back to the source section for an invalid range instead of inventing a passage target", async () => {
    history.replaceState(null, "", `${location.pathname}${location.search}#abstract%3A99999%3A100000`);
    render(<LiveReader id={state.works[0]!.work_id} />); await screen.findByRole("heading", { name: "Retained source abstract" });
    expect(document.getElementById("source-anchor")).toBeNull();
    await waitFor(() => expect(settleReaderTarget).toHaveBeenCalledWith(document.getElementById("source")));
  });
});
