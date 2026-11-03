import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Layout from "@/app/(live)/layout";
import Template from "@/app/(live)/template";
import TodayPage from "@/app/(live)/workspace/today/page";
import RadarPage from "@/app/(live)/workspace/radar/page";
import InterestsPage from "@/app/(live)/workspace/interests/page";
import LibraryPage from "@/app/(live)/workspace/library/page";
import OperationsPage from "@/app/(live)/workspace/operations/page";
import ItemPage from "@/app/(live)/workspace/items/[id]/page";
import { Library as PreviewLibrary } from "@/components/daily/Library";
import { INITIAL_DATA, parsePreview, previewStore } from "@/lib/daily/store";
import { workspace } from "./fixtures";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspace/today",
  useSearchParams: () => new URLSearchParams(window.location.search),
  notFound: () => {
    throw new Error("not found");
  },
}));
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  window.history.replaceState(null, "", "/workspace/today");
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      Promise.resolve(
        Response.json(
          path.includes("/items?")
            ? { items: [], next_cursor: null, as_of: "2026-11-02T15:00:00Z" }
            : workspace(),
        ),
      ),
    ),
  );
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("live route admission and identity contracts", () => {
  it("requires an explicit live flag independently of the fictional preview flag", () => {
    vi.stubEnv("WORKSPACE_LIVE", "");
    vi.stubEnv("WORKSPACE_PREVIEW", "1");
    expect(() => Layout({ children: "private workspace" })).toThrow(
      "not found",
    );
    vi.stubEnv("WORKSPACE_LIVE", "1");
    expect(Layout({ children: "private workspace" })).toBe("private workspace");
  });
  it("mounts the real Today in its own shell with source checks and fixture access separately labelled", async () => {
    render(
      <Template>
        <TodayPage />
      </Template>,
    );
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "What changed",
    );
    expect(screen.getByRole("main")).toContainElement(
      screen.getByRole("heading", { level: 1 }),
    );
    expect(
      screen.getByRole("link", { name: /Fictional preview/ }),
    ).toHaveAttribute("href", "/today");
    await userEvent.setup().click(screen.getByText(/Source checks:/));
    expect(
      screen.getByRole("button", { name: "Check sources now" }),
    ).toBeInTheDocument();
  });
  it("decodes canonical work identifiers exactly at the dynamic-route boundary", async () => {
    render(
      await ItemPage({ params: Promise.resolve({ id: "arxiv%3A2610.00001" }) }),
    );
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "A controlled retrieval study",
    );
    await expect(
      ItemPage({ params: Promise.resolve({ id: "%E0%A4%A" }) }),
    ).rejects.toThrow("not found");
  });
  it.each([
    [RadarPage, "A wider view.Your terms, your pace."],
    [InterestsPage, "Follow a field.Or your own question."],
    [LibraryPage, "Keep the source.Keep your thinking."],
    [OperationsPage, "Know what was checked.And what wasn’t."],
  ])(
    "loads a typed route against the same account-scoped API instead of a parallel fixture surface",
    async (Page, heading) => {
      render(<Page />);
      expect(
        await screen.findByRole("heading", { level: 1 }),
      ).toHaveTextContent(heading);
      expect(fetch).toHaveBeenCalledWith(
        "/api/workspace/state",
        expect.objectContaining({ method: "GET", cache: "no-store" }),
      );
    },
  );
});

it("exports the preview original as a parseable schema for explicit import from another origin", async () => {
  previewStore.update(() =>
    structuredClone({
      ...INITIAL_DATA,
      entries: [
        {
          id: "preview-export",
          itemId: "sample",
          kind: "note" as const,
          body: "My original private note",
          anchor: "source",
        },
      ],
    }),
  );
  const blobs: Blob[] = [];
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn((blob: Blob) => {
      blobs.push(blob);
      return "blob:preview-export";
    }),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  render(<PreviewLibrary />);
  await userEvent.click(
    screen.getByRole("button", {
      name: "Download preview JSON for explicit import",
    }),
  );
  expect(click).toHaveBeenCalledOnce();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview-export");
  const raw = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsText(blobs[0]!);
  });
  expect(parsePreview(raw).entries[0]!.body).toBe("My original private note");
  expect(previewStore.getSnapshot().data.entries[0]!.body).toBe(
    "My original private note",
  );
});
