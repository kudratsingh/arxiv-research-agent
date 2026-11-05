import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveToday } from "@/components/workspace/Today";
import { LiveLibrary } from "@/components/workspace/Library";
import { LiveInterests } from "@/components/workspace/Interests";
import { LiveReader } from "@/components/workspace/Reader";
import { LiveRadar } from "@/components/workspace/Radar";
import { LiveOperations } from "@/components/workspace/Operations";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { INITIAL_DATA, PREVIEW_KEY } from "@/lib/daily/store";
import { DRAFT_KEY, storeDraft } from "@/lib/workspace/drafts";
import type { EntryRevision, WorkspaceState } from "@/lib/workspace/api";
import { SOURCE_TEXT, work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspace/today",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
let current: WorkspaceState;
let failures: Record<string, number>;
let calls: { path: string; body: Record<string, unknown> }[];
let importConflicts: string[];
let nextCursor: string | null;
beforeEach(() => {
  current = workspace();
  failures = {};
  calls = [];
  importConflicts = [];
  nextCursor = null;
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/workspace/today");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url, "http://localhost").pathname.replace(
        "/api/workspace/",
        "",
      );
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : {};
      calls.push({ path: String(url).replace("/api/workspace/", ""), body });
      if (failures[path]) return new Response(null, { status: failures[path] });
      if (path === "context/state" || path === "refresh") return Response.json(current);
      if (path === "profile") {
        current.profile = {
          revision: current.profile.revision + 1,
          data: body.data as WorkspaceState["profile"]["data"],
        };
        return Response.json(current.profile);
      }
      if (path === "edition") return Response.json(current.editions[0]);
      if (path === "context/reading") {
        const item = current.works.find(
          (entry) => entry.work_id === body.work_id,
        )!;
        item.reading = {
          ...(body.data as typeof item.reading),
          revision: item.reading.revision + 1,
        };
        return Response.json(item.reading);
      }
      if (path === "context/entries") {
        const entry = {
          ...(body.data as EntryRevision),
          id: String(body.id),
          revision: Number(body.revision) + 1,
        };
        const item = current.works.find(
          (entry) => entry.work_id === (body.data as EntryRevision).work_id,
        )!;
        item.entries = [
          ...item.entries.filter((previous) => previous.id !== entry.id),
          entry,
        ];
        return Response.json(entry);
      }
      if (path === "manual") {
        const item = work({
          work_id: "url:manual",
          title: String(body.value),
          access_state: "metadata",
          abstract: "",
        });
        current.works.push(item);
        return Response.json(item);
      }
      if (path.startsWith("import/"))
        return Response.json({
          digest: "preview-digest",
          entries_new: path.endsWith("apply") ? 0 : 1,
          entries_existing: path.endsWith("apply") ? 1 : 0,
          conflicts: importConflicts,
          profile_will_change: Boolean(body.import_profile),
          original_retained: true,
        });
      if (path === "schedule") {
        current.schedule = {
          ...(body.data as WorkspaceState["schedule"]),
          revision: current.schedule.revision + 1,
          next_check: null,
        };
        return Response.json(current.schedule);
      }
      if (path === "context/items")
        return Response.json({
          items: current.works,
          next_cursor: nextCursor,
          as_of: current.as_of,
        });
      return new Response(null, { status: 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());
const load = async () => {
  expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText("Opening the selected paper…")).not.toBeInTheDocument());
};

async function openPreviewImport(user: ReturnType<typeof userEvent.setup>) {
  const disclosure = screen.getByText("Import preview notes", { exact: true });
  if (!disclosure.closest("details")?.open) await user.click(disclosure);
  await screen.findByRole("button", { name: "Preview browser import" });
}

describe("real source briefing", () => {
  it("keeps a separately labelled live shell and preserves preview access", () => {
    render(
      <WorkspaceShell>
        <p>Child</p>
      </WorkspaceShell>,
    );
    expect(
      screen.getByRole("link", { name: /Fictional preview/ }),
    ).toHaveAttribute("href", "/today");
    expect(screen.getByRole("link", { name: /Radar/ })).toHaveAttribute(
      "href",
      "/workspace/radar",
    );
    expect(screen.getByRole("main")).toHaveTextContent("Child");
  });
  it("shows a real stored edition, check receipts and durable undo", async () => {
    const user = userEvent.setup();
    current.editions[0]!.coverage = current.sources;
    render(<LiveToday />);
    await load();
    expect(
      screen.getByRole("link", { name: current.works[0]!.title }),
    ).toHaveAttribute("href", expect.stringContaining("arxiv%3A"));
    await user.click(screen.getByText(/Source checks: 1 of 2/));
    expect(
      screen.getByText(/No successful check recorded/),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /^Save A controlled/ }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved on the server: saved",
    );
    await user.click(screen.getByRole("button", { name: "Undo last change" }));
    expect(screen.getByRole("status")).toHaveTextContent("unread");
    await user.click(screen.getByRole("button", { name: /^Snooze one day/ }));
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });
  it("creates a genuinely different reading-window edition and keeps model calls off", async () => {
    const user = userEvent.setup();
    render(<LiveToday />);
    await load();
    await user.click(screen.getByRole("button", { name: "5 min" }));
    await waitFor(() =>
      expect(calls.some((call) => call.path === "edition")).toBe(true),
    );
    expect(current.profile.data.minutes).toBe(5);
    expect(
      screen.getByRole("button", { name: /Generation awaiting approval/ }),
    ).toBeDisabled();
    await user.click(screen.getByText(/Source checks:/));
    await user.click(screen.getByRole("button", { name: "Check sources now" }));
    expect(calls.find((call) => call.path === "refresh")?.body).toEqual({
      source_ids: [],
    });
  });
  it("distinguishes no edition, successful emptiness, failed checks and connection failure", async () => {
    const first = render(<LiveToday />);
    await load();
    first.unmount();
    current.editions = [];
    const empty = render(<LiveToday />);
    expect(
      await screen.findByText("Make your first bounded check."),
    ).toBeInTheDocument();
    empty.unmount();
    current = workspace({ works: [] });
    const partial = render(<LiveToday />);
    expect(
      await screen.findByText("No matches in available checks."),
    ).toBeInTheDocument();
    partial.unmount();
    current.sources = current.sources.map((source) => ({
      ...source,
      status: "ok",
    }));
    const success = render(<LiveToday />);
    expect(
      await screen.findByText("No matches in this reading window."),
    ).toBeInTheDocument();
    success.unmount();
    failures["context/state"] = 503;
    render(<LiveToday />);
    expect(
      await screen.findByText("No fictional items have been substituted."),
    ).toBeInTheDocument();
    delete failures["context/state"];
    await userEvent.click(
      screen.getByRole("button", { name: "Retry connection" }),
    );
    await load();
  });
  it("does not silently retry a conflicting reading state", async () => {
    failures["context/reading"] = 409;
    const user = userEvent.setup();
    render(<LiveToday />);
    await load();
    await user.click(screen.getByRole("button", { name: /^Dismiss/ }));
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
    expect(calls.filter((call) => call.path === "context/reading")).toHaveLength(1);
  });
  it("shows committed partial source results as available with a limited window", async () => {
    current.sources = [
      {
        source_id: "arxiv-cs-lg",
        name: "arXiv cs.LG",
        status: "partial",
        last_success_at: null,
        receipt: { truncated: true, request_count: 1 },
      },
    ];
    current.editions[0]!.coverage = current.sources;
    render(<LiveToday />);
    await load();
    expect(
      screen.getByText(/Source checks: 1 of 1 available/),
    ).toBeInTheDocument();
    expect(screen.getByText("1 limited source windows")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: current.works[0]!.title }),
    ).toBeInTheDocument();
  });
  it("pins an earlier edition's metadata and reader link when the source later changes", async () => {
    const item = current.works[0]!;
    current.editions[0]!.work_versions = {
      [item.work_id]: "arxiv:2610.00001:v1",
    };
    item.reading.version_id = item.version_id;
    render(<LiveToday />);
    await load();
    const source = screen.getByRole("link", {
      name: "An earlier controlled retrieval study",
    });
    expect(source).toHaveAttribute(
      "href",
      expect.stringContaining("version=arxiv%3A2610.00001%3Av1"),
    );
    expect(
      screen.getByText("An earlier retrieval abstract."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "A controlled retrieval study" }),
    ).not.toBeInTheDocument();
  });
  it("does not substitute newer source material for an unavailable edition version", async () => {
    current.editions[0]!.work_versions = {
      [current.works[0]!.work_id]: "missing-version",
    };
    render(<LiveToday />);
    await load();
    expect(
      screen.getByText(/Newer versions were not substituted/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });
});

describe("durable notes and version continuity", () => {
  it("labels a publisher feed excerpt separately from a paper abstract", async () => {
    current.works = [
      work({ access_state: "excerpt", versions: [], kind: "official_blog" }),
    ];
    render(<LiveReader id="arxiv:2610.00001" />);
    await load();
    expect(
      screen.getByRole("heading", { name: "Retained feed excerpt" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Anchor: excerpt:0")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Retained source abstract" }),
    ).not.toBeInTheDocument();
  });
  it("retains unsaved words through an outage and retries the same identity", async () => {
    const user = userEvent.setup();
    render(<LiveReader id="arxiv:2610.00001" />);
    await load();
    const text = screen.getByRole("textbox", { name: "Your question" });
    await user.type(text, "Which baseline is controlled?");
    failures["context/entries"] = 503;
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(text).toHaveValue("Which baseline is controlled?");
    expect(screen.getByRole("status")).toHaveTextContent("still here");
    expect(sessionStorage.getItem(DRAFT_KEY)).toContain("Which baseline");
    delete failures["context/entries"];
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(screen.getByRole("status")).toHaveTextContent("saved on the server");
    expect(text).toHaveValue("");
    const attempts = calls.filter((call) => call.path === "context/entries");
    expect(attempts[0]!.body.request_id).toBe(attempts[1]!.body.request_id);
    expect(attempts[0]!.body.id).toBe(attempts[1]!.body.id);
    expect(sessionStorage.getItem(DRAFT_KEY)).not.toContain("Which baseline");
  });
  it("recovers only an account-and-version draft, leaves old notes on old versions and allows guarded editing", async () => {
    const entry: EntryRevision = {
      id: "old",
      revision: 1,
      updated_at: "2026-11-02T15:00:00Z",
      activity_sequence: 1,
      work_id: "arxiv:2610.00001",
      version_id: "arxiv:2610.00001:v1",
      kind: "note",
      body: "Earlier source question",
      anchor: "abstract:0:2",
    };
    current.works[0]!.entries.push(entry);
    storeDraft("owner-a", entry.work_id, "arxiv:2610.00001:v2", {
      id: "recover",
      revision: 0,
      kind: "question",
      body: "Recovered unsaved text",
      anchor: "abstract:1:4",
    });
    const user = userEvent.setup();
    render(<LiveReader id={entry.work_id} />);
    await load();
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue(
      "Recovered unsaved text",
    );
    expect(
      screen.getByText("Notes on other source versions"),
    ).toBeInTheDocument();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Source version" }),
      entry.version_id,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "An earlier controlled retrieval study",
    );
    expect(
      screen.getByRole("link", { name: "Open original source ↗" }),
    ).toHaveAttribute("href", "https://arxiv.org/abs/2610.00001v1");
    expect(
      screen.getByText(/You are reading an earlier retained version/),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue(
      "",
    );
    await user.click(screen.getByRole("button", { name: "Edit note" }));
    const body = screen.getByRole("textbox", { name: "Your note" });
    await user.clear(body);
    await user.type(body, "Edited earlier note");
    await user.click(screen.getByRole("button", { name: "Save note" }));
    expect(
      (
        calls.find((call) => call.path === "context/entries")!.body
          .data as EntryRevision
      ).version_id,
    ).toBe(entry.version_id);
    expect(screen.getByText("Edited earlier note")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "View latest source version" }),
    );
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue(
      "Recovered unsaved text",
    );
  });
  it("retains real selected character offsets and resumes source context", async () => {
    window.history.replaceState(
      null,
      "",
      "/workspace/items/arxiv%3A2610.00001#abstract%3A2%3A12",
    );
    const user = userEvent.setup();
    render(<LiveReader id="arxiv:2610.00001" />);
    await load();
    expect(
      await screen.findByText(
        /Resumed source passage at character offsets 2–12/,
      ),
    ).toBeInTheDocument();
    const actual = document.querySelector(".daily-source-text p")!;
    const range = document.createRange();
    range.selectNodeContents(actual);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    fireEvent.mouseUp(actual);
    expect(
      screen.getByText(`Selected source passage: “${SOURCE_TEXT}”`),
    ).toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "Your question" }),
      "Test this scope",
    );
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(
      (
        calls.find((call) => call.path === "context/entries")!.body
          .data as EntryRevision
      ).anchor,
    ).toBe(`abstract:0:${SOURCE_TEXT.length}`);
  });
  it.each(["abstract", "excerpt"])(
    "retains code-point offsets for a %s passage with astral symbols before and inside it",
    async (scope) => {
      const text = "🌠 prefix 𝛼 + 🚀 signal suffix";
      const selected = "𝛼 + 🚀";
      const item = current.works[0]!;
      item.abstract = text;
      item.access_state = scope;
      item.versions = item.versions.map((version) =>
        version.version_id === item.version_id
          ? {
              ...version,
              abstract: text,
              access_state: scope,
              source_scope: scope,
            }
          : version,
      );
      const user = userEvent.setup();
      const firstVisit = render(<LiveReader id={item.work_id} />);
      await load();
      const paragraph = document.querySelector(".daily-source-text p")!;
      const node = paragraph.firstChild!;
      const range = document.createRange();
      // Browser DOM ranges use UTF-16, while the persisted source contract uses
      // code points. There is an astral character on both sides of this boundary.
      const browserStart = text.indexOf(selected);
      range.setStart(node, browserStart);
      range.setEnd(node, browserStart + selected.length);
      const browserSelection = window.getSelection()!;
      browserSelection.removeAllRanges();
      browserSelection.addRange(range);
      fireEvent.mouseUp(paragraph);
      expect(
        screen.getByText(`Selected source passage: “${selected}”`),
      ).toBeInTheDocument();
      expect(document.getElementById("source-anchor")).toHaveTextContent(
        selected,
      );
      await user.type(
        screen.getByRole("textbox", { name: "Your question" }),
        "Does this exact mathematical passage support the comparison?",
      );
      await user.click(screen.getByRole("button", { name: "Save question" }));
      const saved = current.works[0]!.entries[0]!;
      expect(saved.anchor).toBe(`${scope}:9:14`);
      expect(saved.version_id).toBe(item.version_id);
      firstVisit.unmount();
      window.history.replaceState(
        null,
        "",
        `/workspace/items/${encodeURIComponent(item.work_id)}?version=${encodeURIComponent(item.version_id)}#${encodeURIComponent(saved.anchor)}`,
      );
      render(<LiveReader id={item.work_id} />);
      await load();
      expect(document.getElementById("source-anchor")?.textContent).toBe(
        selected,
      );
      expect(document.querySelector(".daily-source-text p")?.textContent).toBe(
        text,
      );
      expect(
        screen.getByText(/Resumed source passage at character offsets 9–14/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "Does this exact mathematical passage support the comparison?",
        ),
      ).toBeInTheDocument();
    },
  );
  it("preserves failed edit text and manual reading when metadata is all that exists", async () => {
    current.works = [
      work({ abstract: "", versions: [], access_state: "metadata" }),
    ];
    const user = userEvent.setup();
    render(<LiveReader id="arxiv:2610.00001" />);
    await load();
    expect(
      screen.getByText(/No abstract or full text was acquired/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    expect(calls.some((call) => call.path === "context/reading")).toBe(true);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Save as" }),
      "next-action",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Your next action" }),
      "Read the original",
    );
    failures["context/entries"] = 409;
    await user.click(screen.getByRole("button", { name: "Save next action" }));
    expect(screen.getByRole("textbox")).toHaveValue("Read the original");
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
  });
  it("opens only known records and never substitutes a fictional reader", async () => {
    render(<LiveReader id="missing" />);
    expect(
      await screen.findByText("This source is not in the loaded workspace."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Fictional text written for this preview"),
    ).not.toBeInTheDocument();
  });
  it("keeps notes visible when their requested version is unavailable without replacing its material", async () => {
    window.history.replaceState(
      null,
      "",
      "/workspace/items/arxiv%3A2610.00001?version=missing-version",
    );
    current.works[0]!.entries.push({
      id: "missing",
      revision: 1,
      updated_at: "2026-11-02T15:00:00Z",
      activity_sequence: 1,
      work_id: "arxiv:2610.00001",
      version_id: "missing-version",
      kind: "question",
      body: "A question tied to missing material",
      anchor: "abstract:1:7",
    });
    render(<LiveReader id="arxiv:2610.00001" />);
    expect(
      await screen.findByText("This retained source version is unavailable."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("A question tied to missing material"),
    ).toBeInTheDocument();
    expect(screen.queryByText(SOURCE_TEXT)).not.toBeInTheDocument();
  });
});

describe("profile, import and return state", () => {
  it("saves all editable preferences using a revision, with real multiline custom terms", async () => {
    const user = userEvent.setup();
    render(<LiveInterests />);
    await load();
    const question = screen.getByRole("textbox", {
      name: "Your current research question",
    });
    await user.clear(question);
    await user.type(question, "What should I test next?");
    const custom = screen.getByRole("textbox", {
      name: /Custom interests or watch terms/,
    });
    await user.clear(custom);
    await user.type(custom, "agent memory\nfixed baselines");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Daily reading window" }),
      "45",
    );
    await user.click(
      screen.getByRole("button", { name: "Save interests and question" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("saved on the server");
    expect(current.profile.data.custom_topics).toEqual([
      "agent memory",
      "fixed baselines",
    ]);
    expect(current.profile.data.minutes).toBe(45);
    expect(calls.find((call) => call.path === "profile")!.body.revision).toBe(
      1,
    );
  });
  it("retains a conflicting profile draft until an explicit discard", async () => {
    failures.profile = 409;
    const user = userEvent.setup();
    render(<LiveInterests />);
    await load();
    const question = screen.getByRole("textbox", {
      name: "Your current research question",
    });
    await user.clear(question);
    await user.type(question, "Keep this draft");
    await user.click(
      screen.getByRole("button", { name: "Save interests and question" }),
    );
    expect(question).toHaveValue("Keep this draft");
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
    await user.click(
      screen.getByRole("button", {
        name: "Discard draft and reload saved profile",
      }),
    );
    expect(question).toHaveValue(current.profile.data.research_question);
  });
  it("keeps browser notes untouched until an explicit conflict-free import", async () => {
    localStorage.setItem(
      PREVIEW_KEY,
      JSON.stringify({
        ...INITIAL_DATA,
        entries: [
          {
            id: "preview-note",
            itemId: "fixture",
            kind: "question",
            body: "Preview question",
            anchor: "source",
          },
        ],
      }),
    );
    const original = localStorage.getItem(PREVIEW_KEY);
    const user = userEvent.setup();
    render(<LiveLibrary />);
    await load();
    expect(calls.some((call) => call.path.startsWith("import"))).toBe(false);
    await openPreviewImport(user);
    await user.click(
      screen.getByRole("button", { name: "Preview browser import" }),
    );
    expect(
      screen.getByText("1 new notes/questions/actions"),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.path.endsWith("apply"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm import" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Import saved on the server",
    );
    expect(localStorage.getItem(PREVIEW_KEY)).toBe(original);
    expect(calls.find((call) => call.path.endsWith("apply"))!.body.digest).toBe(
      "preview-digest",
    );
  });
  it("blocks conflicting imports, handles missing originals and keeps a manual save failed until acknowledged", async () => {
    const user = userEvent.setup();
    render(<LiveLibrary />);
    await load();
    await openPreviewImport(user);
    await user.click(
      screen.getByRole("button", { name: "Preview browser import" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Nothing was imported",
    );
    localStorage.setItem(PREVIEW_KEY, JSON.stringify(INITIAL_DATA));
    importConflicts = ["A server note has changed"];
    await openPreviewImport(user);
    await user.click(
      screen.getByRole("button", { name: "Preview browser import" }),
    );
    expect(screen.getByText("A server note has changed")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Confirm import" }),
    ).not.toBeInTheDocument();
    const input = screen.getByRole("textbox", {
      name: "Save an arXiv ID, DOI or source URL",
    });
    await user.type(input, "https://example.org/source");
    failures.manual = 503;
    await user.click(screen.getByRole("button", { name: "Save source link" }));
    expect(input).toHaveValue("https://example.org/source");
    delete failures.manual;
    await user.click(screen.getByRole("button", { name: "Save source link" }));
    expect(input).toHaveValue("");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Access remains metadata",
    );
  });
  it("previews pasted exports from another origin and refuses malformed schemas", async () => {
    const user = userEvent.setup();
    render(<LiveLibrary />);
    await load();
    await openPreviewImport(user);
    await user.click(
      screen.getByText("Import an export from a different preview address"),
    );
    const raw = screen.getByRole("textbox", {
      name: "Or paste exported preview JSON",
    });
    fireEvent.change(raw, { target: { value: '{"revision":9}' } });
    await user.click(
      screen.getByRole("button", { name: "Preview exported JSON" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("unsupported schema");
    fireEvent.change(raw, { target: { value: JSON.stringify(INITIAL_DATA) } });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Also import the preview interests and research question",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Preview exported JSON" }),
    );
    expect(
      screen.getByText("Profile will change after confirmation"),
    ).toBeInTheDocument();
    expect(
      calls.find((call) => call.path === "import/preview")!.body.import_profile,
    ).toBe(true);
    expect(localStorage.getItem(PREVIEW_KEY)).toBeNull();
  });
});

describe("Radar and local operations", () => {
  it("sends actual source/date/access/state filters with a stable pagination cutoff", async () => {
    nextCursor = "next-page";
    const user = userEvent.setup();
    render(<LiveRadar />);
    await load();
    await screen.findByRole("button", { name: "Next page →" });
    await user.type(
      screen.getByRole("searchbox", { name: "Search titles and abstracts" }),
      "retrieval",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Source" }),
      "arxiv-cs-lg",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Date window (known publication/update)" }),
      "30",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Available material" }),
      "abstract",
    );
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() =>
      expect(
        calls.filter((call) => call.path.startsWith("context/items?")).at(-1)!.path,
      ).toContain("days=30"),
    );
    await user.click(screen.getByRole("button", { name: "Next page →" }));
    await waitFor(() =>
      expect(calls.at(-1)!.path).toContain("cursor=next-page"),
    );
    expect(window.location.search).toContain("as_of=");
    await user.click(screen.getByRole("button", { name: "First page" }));
    await waitFor(() =>
      expect(window.location.search).not.toContain("cursor="),
    );
  });
  it("makes source receipts inspectable and cannot activate a recurring schedule", async () => {
    current.tasks = [
      {
        id: "task-1",
        status: "failed",
        kind: "intake",
        attempts: 2,
        reason: "Source timeout",
        due_at: "2026-11-02T15:00:00Z",
      },
    ];
    const user = userEvent.setup();
    render(<LiveOperations />);
    await load();
    expect(screen.getByText("Recurring schedule disabled")).toBeInTheDocument();
    expect(screen.getByText("Source timeout")).toBeInTheDocument();
    await user.click(screen.getAllByText("Inspect this check’s receipt")[0]!);
    expect(screen.getByText(/"request_count": 1/)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Check arXiv cs.LG now" }),
    );
    expect(
      calls.find((call) => call.path === "refresh")!.body.source_ids,
    ).toEqual(["arxiv-cs-lg"]);
    fireEvent.change(screen.getByLabelText("Proposed local check time"), {
      target: { value: "08:15" },
    });
    await user.click(screen.getByRole("button", { name: /Save preferences/ }));
    expect(
      calls.find((call) => call.path === "schedule")!.body.data,
    ).toMatchObject({ enabled: false, local_time: "08:15" });
    expect(screen.getByRole("status")).toHaveTextContent("remain disabled");
  });
});

describe("recovery paths that must not erase authored data", () => {
  it("loads a bounded exported file for explicit review, keeps it after an apply conflict, and retries the same transfer", async () => {
    const user = userEvent.setup();
    render(<LiveLibrary />);
    await load();
    await openPreviewImport(user);
    await user.click(
      screen.getByText("Import an export from a different preview address"),
    );
    const input = screen.getByLabelText("Preview JSON file");
    const original = JSON.stringify({
      ...INITIAL_DATA,
      entries: [
        {
          id: "file-note",
          itemId: "preview-work",
          kind: "note",
          body: "Imported authored note",
          anchor: "source",
        },
      ],
    });
    const file = new File([original], "preview.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", {
      value: () => Promise.resolve(original),
    });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() =>
      expect(
        screen.getByRole("textbox", { name: "Or paste exported preview JSON" }),
      ).toHaveValue(original),
    );
    expect(calls.some((call) => call.path.startsWith("import/"))).toBe(false);
    await user.click(
      screen.getByRole("button", { name: "Preview exported JSON" }),
    );
    failures["import/apply"] = 409;
    await user.click(screen.getByRole("button", { name: "Confirm import" }));
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
    expect(
      screen.getByRole("textbox", { name: "Or paste exported preview JSON" }),
    ).toHaveValue(original);
    delete failures["import/apply"];
    await user.click(screen.getByRole("button", { name: "Confirm import" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Import saved on the server",
    );
    const transfers = calls.filter((call) => call.path === "import/apply");
    expect(transfers[0]!.body.digest).toBe(transfers[1]!.body.digest);
    expect(transfers[0]!.body.record).toEqual(transfers[1]!.body.record);
    expect(
      screen.getByRole("link", { name: "Export supplied original" }),
    ).toHaveAttribute("download", "research-preview-original.json");
  });
  it("rejects oversized or unreadable import files without disturbing the supplied original", async () => {
    const user = userEvent.setup();
    render(<LiveLibrary />);
    await load();
    await openPreviewImport(user);
    await user.click(
      screen.getByText("Import an export from a different preview address"),
    );
    const input = screen.getByLabelText("Preview JSON file");
    fireEvent.change(input, { target: { files: [] } });
    const large = new File(["x".repeat(200001)], "large.json", {
      type: "application/json",
    });
    fireEvent.change(input, { target: { files: [large] } });
    expect(screen.getByRole("status")).toHaveTextContent("limited to 200 KB");
    const broken = new File(["{}"], "broken.json", {
      type: "application/json",
    });
    Object.defineProperty(broken, "text", {
      value: () => Promise.reject(new Error("read failure")),
    });
    fireEvent.change(input, { target: { files: [broken] } });
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "file could not be read",
      ),
    );
    localStorage.setItem(PREVIEW_KEY, JSON.stringify(INITIAL_DATA));
    failures["import/preview"] = 503;
    await openPreviewImport(user);
    await user.click(
      screen.getByRole("button", { name: "Preview browser import" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "retry when the service is available",
    );
    expect(localStorage.getItem(PREVIEW_KEY)).toBe(
      JSON.stringify(INITIAL_DATA),
    );
  });
  it("shows the last loaded reading state through an outage, keeps text despite failed browser recovery, and can retry the server", async () => {
    sessionStorage.setItem(DRAFT_KEY, "unsupported original draft format");
    const user = userEvent.setup();
    render(<LiveReader id="arxiv:2610.00001" />);
    await load();
    expect(screen.getByRole("status")).toHaveTextContent(
      "draft recovery is unavailable",
    );
    const text = screen.getByRole("textbox", { name: "Your question" });
    await user.type(text, "Keep my question even when both stores fail");
    expect(
      screen.getByText(/Draft recovery is unavailable. Copy your text/),
    ).toBeInTheDocument();
    failures["context/reading"] = 409;
    await user.click(screen.getByRole("button", { name: "Save to Library" }));
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
    expect(text).toHaveValue("Keep my question even when both stores fail");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Source version" }),
      "arxiv:2610.00001:v1",
    );
    expect(screen.getByRole("combobox", { name: "Source version" })).toHaveValue("arxiv:2610.00001:v2");
    expect(text).toHaveValue("Keep my question even when both stores fail");
    expect(
      screen.getByText(/Draft recovery is unavailable. Copy your text/),
    ).toBeInTheDocument();
    delete failures["context/reading"];
    await user.click(screen.getByRole("button", { name: "Discard unsaved draft" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Source version" }),
      "arxiv:2610.00001:v1",
    );
    await user.click(
      screen.getByRole("button", { name: "View latest source version" }),
    );
    await user.click(screen.getByRole("button", { name: "Mark read" }));
    expect(current.works[0]!.reading.status).toBe("read");
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(current.works[0]!.reading.status).toBe("archived");
  });
  it("confirms a server save even if clearing the browser draft fails and keeps unrelated work unchanged", async () => {
    current.works.push(
      work({ work_id: "arxiv:other", title: "An unrelated source" }),
    );
    const user = userEvent.setup();
    render(<LiveReader id="arxiv:2610.00001" />);
    await load();
    const text = screen.getByRole("textbox", { name: "Your question" });
    await user.type(text, "Server acknowledgement is authoritative");
    sessionStorage.setItem(DRAFT_KEY, "malformed after composing");
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "is saved on the server",
    );
    expect(
      screen.getByText("Server acknowledgement is authoritative"),
    ).toBeInTheDocument();
    expect(current.works[1]!.entries).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Edit question" }));
    await user.type(
      screen.getByRole("textbox", { name: "Your question" }),
      " changed locally",
    );
    await user.click(screen.getByRole("button", { name: "Cancel edit" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "saved note was not changed",
    );
    expect(current.works[0]!.entries[0]!.body).toBe(
      "Server acknowledgement is authoritative",
    );
  });
  it("does not claim a failed refresh or reading-window change succeeded", async () => {
    const user = userEvent.setup();
    render(<LiveToday />);
    await load();
    failures.refresh = 503;
    await user.click(screen.getByText(/Source checks:/));
    await user.click(screen.getByRole("button", { name: "Check sources now" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "retry when the service is available",
    );
    expect(
      screen.getByRole("link", { name: "A controlled retrieval study" }),
    ).toBeInTheDocument();
    failures.profile = 409;
    await user.click(screen.getByRole("button", { name: "45 min" }));
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
    expect(current.profile.data.minutes).toBe(15);
  });
});

describe("the visible personal controls round trip their actual data", () => {
  it("changes fields, detailed topics, streams, exclusions and exploration without inventing connected coverage", async () => {
    const user = userEvent.setup();
    render(<LiveInterests />);
    await load();
    const search = await screen.findByRole("searchbox", { name: "Find a topic" });
    await user.type(search, "retrieval");
    const selectedTopic = screen.getByRole("checkbox", {
      name: /Retrieval and memory/,
    });
    await user.click(selectedTopic);
    expect(selectedTopic).not.toBeChecked();
    await user.click(selectedTopic);
    await user.clear(search);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Browse a field" }),
      "oa-field:17",
    );
    expect(
      screen.getByRole("checkbox", { name: /Computer Science/ }),
    ).toBeInTheDocument();
    const rocket = screen.getByRole("checkbox", { name: /Rocket Twin watch/ });
    await user.click(rocket);
    await user.click(rocket);
    await user.type(
      screen.getByRole("textbox", { name: /Exclude these terms/ }),
      "paid promotion\nrobot marketing",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Exploration allocation" }),
      "0",
    );
    await user.type(search, "a topic absent from this catalogue");
    expect(
      screen.getByText("No catalogue entries match. Add a custom interest."),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Save interests and question" }),
    );
    expect(current.profile.data.exclusions).toEqual([
      "paid promotion",
      "robot marketing",
    ]);
    expect(current.profile.data.exploration).toBe(0);
    expect(current.profile.data.topics).toContain("ml:retrieval-and-memory");
    expect(current.profile.data.streams).not.toContain("rocket-twin");
  });
  it("filters notes/read/archive views, preserves source versions in resume links and permits undo", async () => {
    const first = current.works[0]!;
    first.reading.status = "saved";
    first.reading.version_id = "arxiv:2610.00001:v1";
    first.reading.anchor = "abstract:1:7";
    first.entries.push({
      id: "q",
      revision: 1,
      updated_at: "2026-11-02T15:00:00Z",
      activity_sequence: 1,
      work_id: first.work_id,
      version_id: "arxiv:2610.00001:v1",
      kind: "next-action",
      body: "Compare the earlier baseline",
      anchor: "abstract:1:7",
    });
    current.works.push(
      work({
        work_id: "read-source",
        title: "A read source",
        reading: {
          revision: 1,
          status: "read",
          anchor: "abstract:0",
          version_id: "",
          snoozed_until: null,
          updated_at: "",
          activity_sequence: 0,
        },
      }),
    );
    const user = userEvent.setup();
    const mounted = render(<LiveLibrary />);
    await load();
    expect(
      screen.getByText(/A newer source version is available/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Resume this question →" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("version=arxiv%3A2610.00001%3Av1"),
    );
    await user.click(
      screen.getByRole("button", { name: /^Unsave A controlled/ }),
    );
    await user.click(screen.getByRole("button", { name: "Undo last change" }));
    expect(
      screen.getByText("Compare the earlier baseline"),
    ).toBeInTheDocument();
    const view = screen.getByRole("combobox", { name: "Library view" });
    // The simple navigation mock reads the URL when Next would notify it.
    await user.selectOptions(view, "notes");
    mounted.rerender(<LiveLibrary />);
    expect(
      screen.getByText("Compare the earlier baseline"),
    ).toBeInTheDocument();
    await user.selectOptions(view, "read");
    mounted.rerender(<LiveLibrary />);
    expect(
      screen.getByRole("link", { name: "A read source" }),
    ).toBeInTheDocument();
    await user.selectOptions(view, "archived");
    mounted.rerender(<LiveLibrary />);
    expect(screen.getByText("No items in this view.")).toBeInTheDocument();
    await user.selectOptions(view, "all");
    mounted.rerender(<LiveLibrary />);
    // The controller exposes every work in its queue and one in the stage.
    await user.click(screen.getByRole("button", { name: /Show paper .*A read source/ }));
    expect(
      screen.getByRole("link", { name: "A read source" }),
    ).toBeInTheDocument();
  });
  it("keeps failed source and schedule changes visible without activating recurring work", async () => {
    current.schedule = {
      revision: 3,
      enabled: true,
      timezone: "America/Los_Angeles",
      local_time: "07:00",
      next_check: "2026-11-03T15:00:00Z",
    };
    current.tasks = [
      { state: "queued", attempt: 1 },
      { kind: "metadata", status: "failed", reason: "Retry exhausted" },
    ];
    const user = userEvent.setup();
    render(<LiveOperations />);
    await load();
    failures.refresh = 503;
    await user.click(
      screen.getByRole("button", { name: "Check arXiv cs.LG now" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "retry when the service is available",
    );
    const zone = screen.getByRole("textbox", { name: "IANA timezone" });
    await user.clear(zone);
    await user.type(zone, "Europe/London");
    failures.schedule = 409;
    await user.click(
      screen.getByRole("button", {
        name: "Pause schedule and save preferences",
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
    expect(zone).toHaveValue("Europe/London");
    delete failures.schedule;
    await user.click(
      screen.getByRole("button", {
        name: "Pause schedule and save preferences",
      }),
    );
    expect(current.schedule.enabled).toBe(false);
    expect(current.schedule.timezone).toBe("Europe/London");
  });
  it("keeps a failed Radar request explicit, restores filters on browser back, and does not require a saved state to browse", async () => {
    failures["context/items"] = 503;
    const user = userEvent.setup();
    render(<LiveRadar />);
    await load();
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "retry when the service is available",
      ),
    );
    delete failures["context/items"];
    current.works = [];
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Reading state" }),
      "saved",
    );
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(
      await screen.findByText("No stored items match these filters."),
    ).toBeInTheDocument();
    window.history.replaceState(
      null,
      "",
      "/workspace/radar?q=memory&days=0&status=read",
    );
    fireEvent.popState(window);
    await waitFor(() =>
      expect(
        screen.getByRole("searchbox", { name: "Search titles and abstracts" }),
      ).toHaveValue("memory"),
    );
    expect(
      calls.filter((call) => call.path.startsWith("context/items?")).at(-1)!.path,
    ).toContain("status=read");
  });
});
