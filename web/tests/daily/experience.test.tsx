import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Today } from "@/components/daily/Today";
import { Reader } from "@/components/daily/Reader";
import { Interests } from "@/components/daily/Interests";
import { Library } from "@/components/daily/Library";
import { DailyShell } from "@/components/daily/DailyShell";
import { INITIAL_DATA, previewStore } from "@/lib/daily/store";
import { ITEMS } from "@/lib/daily/fixtures";
import topics from "@/lib/daily/topics.json";

vi.mock("next/navigation", () => ({ usePathname: () => "/today" }));
beforeEach(() => {
  window.localStorage.clear();
  previewStore.update(() => structuredClone(INITIAL_DATA));
  window.location.hash = "";
});

describe("daily briefing decisions", () => {
  it("limits the finite edition, preserves saves and marks a day done reversibly", async () => {
    const user = userEvent.setup();
    render(<Today />);
    await user.click(screen.getByRole("button", { name: "5 min" }));
    expect(screen.getByText("1 item · your selected lens")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /^Save When the corpus/ }),
    );
    expect(screen.getByText("Saved", { exact: true })).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /^Unsave When the corpus/ }),
    );
    await user.click(screen.getByRole("button", { name: "Done for today" }));
    expect(screen.getByRole("status")).toHaveTextContent("Edition marked done");
    await user.click(
      screen.getByRole("button", { name: "Reopen today’s briefing" }),
    );
    await user.click(screen.getByRole("button", { name: "45 min" }));
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });
  it("does not invent matches or a saved history", () => {
    previewStore.update((d) => ({ ...d, topics: [], customTopics: [] }));
    render(<Today />);
    expect(
      screen.getByRole("link", { name: "Choose interests" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Your current question")).toBeInTheDocument();
  });
  it("keeps unmatched custom topics without pretending coverage exists", () => {
    previewStore.update((d) => ({
      ...d,
      configured: false,
      topics: [],
      customTopics: ["marine systems"],
    }));
    render(<Today />);
    expect(screen.getByText(/No sample items match/)).toBeInTheDocument();
  });
  it("resumes only a recorded question", () => {
    previewStore.update((d) => ({
      ...d,
      entries: [
        {
          id: "q",
          itemId: "corpus-shift",
          kind: "next-action",
          body: "Hold the corpus fixed",
          anchor: "source",
        },
      ],
    }));
    render(<Today />);
    expect(
      screen.getByRole("link", { name: /Reopen your reading/ }),
    ).toHaveAttribute("href", "/library/items/corpus-shift#notes");
  });
});

describe("source reader and owner notes", () => {
  it("saves, edits and retains a question with its source version", async () => {
    const user = userEvent.setup();
    render(<Reader item={ITEMS[0]!} />);
    await user.click(screen.getByRole("button", { name: "Save to Library" }));
    await user.click(
      screen.getByRole("button", { name: "Remove from saved items" }),
    );

    const body = screen.getByRole("textbox", { name: "Your question" });
    await user.clear(body);
    await user.type(body, "Is the corpus fixed?");
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved in this browser",
    );
    await user.click(screen.getByRole("button", { name: "Edit question" }));
    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "Pin corpus and query set");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Save as" }),
      "next-action",
    );
    await user.click(
      screen.getByRole("button", { name: "Update next action" }),
    );
    expect(previewStore.getSnapshot().data.entries).toHaveLength(1);
    expect(previewStore.getSnapshot().data.entries[0]?.body).toBe(
      "Pin corpus and query set",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Updated");
    fireEvent.submit(screen.getByRole("textbox").closest("form")!);
    expect(previewStore.getSnapshot().data.entries).toHaveLength(1);
  });
  it.each([1, 2])(
    "keeps access boundaries for non-full-text item %s",
    (index) => {
      render(<Reader item={ITEMS[index]!} />);
      expect(
        screen.getByRole("button", { name: "Generation not enabled" }),
      ).toBeDisabled();
      expect(
        screen.getByText(/does not establish the full experimental/),
      ).toBeInTheDocument();
    },
  );
  it("reports an unsaved session when browser writes fail", async () => {
    const user = userEvent.setup();
    const spy = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("quota");
      });
    render(
      <DailyShell>
        <Reader item={ITEMS[0]!} />
      </DailyShell>,
    );
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(screen.getByRole("status")).toHaveTextContent("this tab only");
    expect(screen.getByText(/Browser storage unavailable/)).toBeInTheDocument();
    spy.mockRestore();
  });
});

describe("interests and portable research memory", () => {
  it("edits topics, streams and the organizing question without enabling intake", async () => {
    const user = userEvent.setup();
    render(<Interests topics={topics.topics} />);
    await user.clear(
      screen.getByRole("textbox", { name: "Your current research question" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Your current research question" }),
      "How do I verify memory retrieval?",
    );
    await user.click(
      screen.getByRole("button", { name: "Save research question" }),
    );
    expect(
      screen.getByText("Research question saved in this browser."),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", { name: /Rocket Twin watch/ }),
    );
    await user.click(
      screen.getByRole("checkbox", { name: /Rocket Twin watch/ }),
    );
    await user.type(screen.getByRole("searchbox"), "retrieval augmented");
    const topic = screen.getByRole("checkbox", {
      name: /Retrieval augmented generation/,
    });
    await user.click(topic);
    await user.click(topic);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Broad field" }),
      "oa-field:17",
    );
    expect(
      screen.getByRole("checkbox", { name: /Computer Science/ }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Use suggested ML lens" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Your own topic or question" }),
      "agent memory",
    );
    await user.click(
      screen.getByRole("button", { name: "Add custom interest" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Remove agent memory" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Remove Retrieval and memory" }),
    );
    expect(previewStore.getSnapshot().data.researchQuestion).toBe(
      "How do I verify memory retrieval?",
    );
  });
  it("offers an honest empty library and exports recorded notes", async () => {
    const user = userEvent.setup();
    render(<Library />);
    expect(
      screen.getByRole("button", { name: "Export notes as Markdown" }),
    ).toBeDisabled();
    act(() =>
      previewStore.update((d) => ({
        ...d,
        saved: ["corpus-shift"],
        anchors: { "corpus-shift": "notes" },
        entries: [
          {
            id: "q",
            itemId: "corpus-shift",
            kind: "question",
            body: "What changed?",
            anchor: "source",
          },
        ],
      })),
    );
    const create = vi.fn(() => "blob:export");
    const revoke = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      value: create,
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      value: revoke,
      configurable: true,
    });
    await user.click(
      screen.getByRole("button", { name: "Export notes as Markdown" }),
    );
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    expect(revoke).toHaveBeenCalledWith("blob:export");
    expect(
      screen.getByRole("link", { name: /Resume reading/ }),
    ).toHaveAttribute("href", "/library/items/corpus-shift#notes");
  });
});
