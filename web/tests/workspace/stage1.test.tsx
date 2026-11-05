import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveToday } from "@/components/workspace/Today";
import { LiveReader } from "@/components/workspace/Reader";
import { LiveLibrary } from "@/components/workspace/Library";
import { LiveInterests } from "@/components/workspace/Interests";
import { AllocationReceipt } from "@/components/workspace/AllocationReceipt";
import type {
  Activity,
  EntryRevision,
  WorkspaceState,
} from "@/lib/workspace/api";
import { DRAFT_KEY } from "@/lib/workspace/drafts";
import { work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
let current: WorkspaceState;
let failures: Record<string, number>;
let calls: { path: string; body: Record<string, unknown> }[];

function entry(overrides: Partial<EntryRevision> = {}): EntryRevision {
  return {
    id: "entry-a",
    revision: 2,
    work_id: "arxiv:2610.00001",
    version_id: "arxiv:2610.00001:v1",
    kind: "question",
    body: "An earlier question, edited most recently",
    anchor: "abstract:3:10",
    updated_at: "2026-11-02T16:00:00Z",
    activity_sequence: 12,
    ...overrides,
  };
}
function activity(value: EntryRevision): Activity {
  return {
    sequence: value.activity_sequence,
    entry_id: value.id,
    work_id: value.work_id,
    version_id: value.version_id,
    kind: "entry",
    entry_kind: value.kind,
    body: value.body,
    anchor: value.anchor,
    revision: value.revision,
    updated_at: value.updated_at,
  };
}
function allocation(overrides: Record<string, unknown> = {}) {
  return {
    slots: 3,
    requested_fraction: 0.3,
    planned_max_exploration_slots: 0,
    max_exploration_slots: 0,
    actual_exploration_slots: 0,
    actual_items: 3,
    actual_fraction: 0,
    unused_slots: 0,
    rounding: "floor_final_count",
    ...overrides,
  };
}
beforeEach(() => {
  current = workspace();
  failures = {};
  calls = [];
  localStorage.clear();
  sessionStorage.clear();
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
      calls.push({ path, body });
      if (failures[path]) return new Response(null, { status: failures[path] });
      if (path === "context/state") return Response.json(current);
      if (path === "profile") {
        current.profile = {
          revision: current.profile.revision + 1,
          data: body.data as WorkspaceState["profile"]["data"],
        };
        return Response.json(current.profile);
      }
      if (path === "context/entries") {
        const saved = {
          ...(body.data as EntryRevision),
          id: String(body.id),
          revision: Number(body.revision) + 1,
          activity_sequence: 20,
          updated_at: "2026-11-02T17:00:00Z",
        };
        const item = current.works.find(
          (candidate) => candidate.work_id === saved.work_id,
        )!;
        item.entries = [
          ...item.entries.filter((previous) => previous.id !== saved.id),
          saved,
        ];
        return Response.json(saved);
      }
      if (path === "context/reading")
        return Response.json({
          ...(body.data as object),
          revision: Number(body.revision) + 1,
          activity_sequence: 21,
          updated_at: "2026-11-02T17:01:00Z",
        });
      return new Response(null, { status: 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("durable activity and exact reading continuity", () => {
  it("shows the server's edited-earlier-question activity instead of the last UUID or work in a flattened array", async () => {
    const edited = entry(),
      laterUUID = entry({
        id: "entry-z",
        body: "A later UUID with older activity",
        activity_sequence: 4,
      });
    current.works[0]!.entries = [edited, laterUUID];
    current.works.push(
      work({
        work_id: "work-z",
        title: "Last work in an unrelated sort",
        entries: [
          entry({
            id: "entry-last",
            work_id: "work-z",
            body: "Not the newest saved activity",
            activity_sequence: 1,
          }),
        ],
      }),
    );
    current.activity = [activity(edited), activity(laterUUID)];
    current.latest_activity = activity(edited);
    render(<LiveToday />);
    await screen.findByText("An earlier question, edited most recently");
    expect(
      screen.queryByText("Not the newest saved activity"),
    ).not.toBeInTheDocument();
    const link = screen.getByRole("link", {
      name: "An earlier controlled retrieval study →",
    });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("entry=entry-a"),
    );
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("version=arxiv%3A2610.00001%3Av1"),
    );
    expect(
      screen.getByText("Latest activity · your question"),
    ).toBeInTheDocument();
  });
  it("pins and unpins through revision-guarded preferences without rewriting an edition", async () => {
    const value = entry();
    current.works[0]!.entries = [value];
    current.latest_activity = activity(value);
    const user = userEvent.setup();
    render(<LiveToday />);
    await user.click(await screen.findByText("Source and pin options"));
    await user.click(
      await screen.findByRole("button", { name: "Pin this question" }),
    );
    expect(screen.getByText("Pinned · your question")).toBeInTheDocument();
    expect(calls.find((call) => call.path === "profile")!.body).toMatchObject({
      revision: 1,
      data: { pinned_entry_id: "entry-a" },
    });
    expect(calls.some((call) => call.path === "edition")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Unpin saved item" }));
    expect(current.profile.data.pinned_entry_id).toBeNull();
    expect(
      screen.getByText("Latest activity · your question"),
    ).toBeInTheDocument();
  });
  it("keeps a failed pin unconfirmed and retries the same revision identity", async () => {
    const value = entry();
    current.works[0]!.entries = [value];
    current.latest_activity = activity(value);
    failures.profile = 409;
    const user = userEvent.setup();
    render(<LiveToday />);
    await user.click(await screen.findByText("Source and pin options"));
    await user.click(
      await screen.findByRole("button", { name: "Pin this question" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
    expect(current.profile.data.pinned_entry_id).toBeNull();
    delete failures.profile;
    await user.click(screen.getByRole("button", { name: "Pin this question" }));
    const attempts = calls.filter((call) => call.path === "profile");
    expect(attempts[0]!.body.request_id).toBe(attempts[1]!.body.request_id);
  });
  it("opens and focuses the exact saved question with its earlier source passage and a Library return context", async () => {
    const value = entry();
    current.works[0]!.entries = [
      value,
      entry({ id: "entry-b", body: "Another question at this version" }),
    ];
    window.history.replaceState(
      null,
      "",
      "/workspace/items/arxiv%3A2610.00001?version=arxiv%3A2610.00001%3Av1&entry=entry-a&return_to=%2Fworkspace%2Flibrary%3Fview%3Dnotes#notes",
    );
    const user = userEvent.setup();
    render(<LiveReader id={value.work_id} />);
    await screen.findByText(value.body);
    const target = document.getElementById("workspace-entry-entry-a")!;
    await waitFor(() => expect(target).toHaveFocus());
    expect(within(target).getByText(value.body)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Library" })).toHaveAttribute(
      "href",
      "/workspace/library?view=notes",
    );
    expect(document.getElementById("source-anchor")?.textContent).toBe(
      "earlier",
    );
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue(
      "",
    );
    await user.click(
      within(target).getByRole("button", { name: "Edit question" }),
    );
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue(
      value.body,
    );
    expect(target).toBeInTheDocument();
  });
  it("edits an earlier question without moving its source anchor or overwriting a different draft", async () => {
    const value = entry();
    current.works[0]!.entries = [value];
    window.history.replaceState(
      null,
      "",
      "/workspace/items/arxiv%3A2610.00001?version=arxiv%3A2610.00001%3Av1",
    );
    const user = userEvent.setup();
    render(<LiveReader id={value.work_id} />);
    const textarea = await screen.findByRole("textbox", {
      name: "Your question",
    });
    await user.type(textarea, "An unsaved separate thought");
    await user.click(screen.getByRole("button", { name: "Edit question" }));
    expect(textarea).toHaveValue("An unsaved separate thought");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Save or explicitly discard",
    );
    await user.click(
      screen.getByRole("button", { name: "Discard unsaved draft" }),
    );
    expect(sessionStorage.getItem(DRAFT_KEY)).not.toContain(
      "An unsaved separate thought",
    );
    await user.click(screen.getByRole("button", { name: "Edit question" }));
    await user.clear(textarea);
    await user.type(
      textarea,
      "Edited earlier question after checking its baseline",
    );
    failures["context/entries"] = 409;
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(textarea).toHaveValue(
      "Edited earlier question after checking its baseline",
    );
    delete failures["context/entries"];
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(calls.find((call) => call.path === "context/entries")!.body).toMatchObject({
      id: "entry-a",
      revision: 2,
      data: { version_id: value.version_id, anchor: value.anchor },
    });
    await user.click(screen.getByRole("button", { name: "Pin question" }));
    expect(current.profile.data.pinned_entry_id).toBe("entry-a");
  });
  it("returns safely from a crafted URL and does not substitute another question for an unknown entry", async () => {
    window.history.replaceState(
      null,
      "",
      "/workspace/items/arxiv%3A2610.00001?entry=not-owned&return_to=javascript%3Aalert(1)",
    );
    render(<LiveReader id="arxiv:2610.00001" />);
    expect(
      await screen.findByText(/That saved item is unavailable in this account/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Today" })).toHaveAttribute(
      "href",
      "/workspace/today",
    );
  });
  it("follows a client return to the notes URL even when the question's work is unread", async () => {
    const value = entry();
    current.works[0]!.entries = [value];
    current.works.push(
      work({
        work_id: "a-saved-source",
        title: "A saved source without notes",
        entries: [],
        reading: { ...work().reading, status: "saved" },
      }),
    );
    window.history.replaceState(null, "", "/workspace/library?view=saved");
    const mounted = render(<LiveLibrary />);
    await screen.findByRole("link", { name: "A saved source without notes" });
    expect(screen.queryByText(value.body)).not.toBeInTheDocument();
    // Next's native-history integration rerenders useSearchParams on soft
    // navigation. Re-render the same component instance to model that signal.
    window.history.replaceState(null, "", "/workspace/library?view=notes");
    mounted.rerender(<LiveLibrary />);
    expect(screen.getByRole("combobox", { name: "Library view" })).toHaveValue(
      "notes",
    );
    expect(screen.getByText(value.body)).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "A saved source without notes" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Resume this question →" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining(
        "return_to=%2Fworkspace%2Flibrary%3Fview%3Dnotes",
      ),
    );
  });
  it("preserves a Library notes filter and the exact entry identity in its resume link", async () => {
    const value = entry();
    current.works[0]!.entries = [value];
    window.history.replaceState(null, "", "/workspace/library?view=notes");
    render(<LiveLibrary />);
    const link = await screen.findByRole("link", {
      name: "Resume this question →",
    });
    expect(screen.getByRole("combobox", { name: "Library view" })).toHaveValue(
      "notes",
    );
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("entry=entry-a"),
    );
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining(
        "return_to=%2Fworkspace%2Flibrary%3Fview%3Dnotes",
      ),
    );
  });
});

describe("honest vocabulary coverage and exploration allocation", () => {
  it("discloses actual saved parent-group terms, connected source scope and navigation-only fields", async () => {
    current.profile.data.topics = ["ml:neural-architectures", "oa-field:17"];
    current.interest_coverage = [
      {
        topic_id: "ml:neural-architectures",
        label: "Neural architectures",
        matching_mode: "descendant_terms",
        terms: ["transformer", "attention"],
        descendant_ids: ["ml:neural-architectures/transformers"],
        source_ids: ["arxiv-cs-lg"],
        status: "limited",
        limitations: [
          "Matching source metadata does not establish full literature coverage.",
        ],
      },
      {
        topic_id: "oa-field:17",
        label: "Computer Science",
        matching_mode: "browse_only",
        terms: [],
        descendant_ids: [],
        source_ids: [],
        status: "unconnected",
        limitations: ["A broad catalogue anchor has no matching vocabulary."],
      },
    ];
    const user = userEvent.setup();
    render(<LiveInterests />);
    const coverage = await screen.findByRole("region", {
      name: "What these interests actually monitor",
    });
    await user.click(within(coverage).getByText("Neural architectures"));
    expect(
      within(coverage).getByText(/transformer, attention/),
    ).toBeInTheDocument();
    expect(within(coverage).getByText("arXiv cs.LG")).toBeInTheDocument();
    await user.click(within(coverage).getByText("Computer Science"));
    expect(
      within(coverage).getByText("Browse only · no matching vocabulary"),
    ).toBeInTheDocument();
    const question = screen.getByRole("textbox", {
      name: "Your current research question",
    });
    await user.type(question, " another question");
    expect(
      within(coverage).getByText(/Your draft is not applied here yet/),
    ).toBeInTheDocument();
  });
  it("shows the server's strict zero allocation at a three-item window and the recorded larger-window allocation", () => {
    const first = render(
      <AllocationReceipt allocation={allocation()} minutes={15} />,
    );
    expect(
      screen.getByText(/15 min · 0 exploration items/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/among 3 selected \(0%\). Requested cap: 30%/),
    ).toBeInTheDocument();
    first.unmount();
    render(
      <AllocationReceipt
        allocation={allocation({
          slots: 9,
          planned_max_exploration_slots: 2,
          max_exploration_slots: 2,
          actual_exploration_slots: 2,
          actual_items: 9,
          actual_fraction: 2 / 9,
        })}
        minutes={45}
      />,
    );
    expect(
      screen.getByText(/45 min · 2 exploration items/),
    ).toBeInTheDocument();
    expect(screen.getByText(/22.2%/)).toBeInTheDocument();
  });
  it("keeps sparse-candidate and empty/historical denominators explicit", async () => {
    const user = userEvent.setup();
    const sparse = render(
      <AllocationReceipt
        allocation={allocation({ slots: 9, actual_items: 2, unused_slots: 7 })}
        minutes={45}
      />,
    );
    await user.click(screen.getByText("Inspect this edition’s allocation"));
    expect(screen.getByText("7")).toBeInTheDocument();
    sparse.unmount();
    const empty = render(
      <AllocationReceipt
        allocation={allocation({
          actual_items: 0,
          actual_fraction: null,
          unused_slots: 3,
        })}
        minutes={15}
        compact
      />,
    );
    expect(screen.getByText(/no items/)).toBeInTheDocument();
    empty.unmount();
    render(<AllocationReceipt allocation={{}} />);
    expect(
      screen.getByText(/no recorded exploration allocation/),
    ).toBeInTheDocument();
  });
});
