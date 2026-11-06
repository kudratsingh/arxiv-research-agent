import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveReader } from "@/components/workspace/Reader";
import {
  RetainedSourceReader,
  parseMaterialAnchor,
} from "@/components/workspace/RetainedSource";
import type { MaterialDocument } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
import { job, preview } from "./syntheticFixtures";
import { MAT, retained, text, available } from "./materialFixtures";
import { WorkCard } from "@/components/workspace/WorkCard";
let documentValue: MaterialDocument;
let responses: Record<string, number>;
let calls: { path: string; body: Record<string, unknown> }[];
let state = workspace();
beforeEach(() => {
  documentValue = retained();
  responses = {};
  calls = [];
  state = workspace();
  sessionStorage.clear();
  window.history.replaceState(
    null,
    "",
    `/workspace/items/${encodeURIComponent(work().work_id)}?version=${encodeURIComponent(work().version_id)}`,
  );
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
      if (responses[path])
        return new Response(null, { status: responses[path] });
      if (path === "context/state") return Response.json(state);
      if (path === "materials") return Response.json([documentValue]);
      if (path.startsWith("materials/")) return Response.json(documentValue);
      if (path === "generation/preview") return Response.json(preview());
      if (path === "generation/jobs")
        return Response.json({ ...job("ready", 5), cached: true });
      if (path === "context/reading")
        return Response.json({
          revision: Number(body.revision) + 1,
          ...(body.data as object),
          updated_at: "2026-11-02T17:00:00Z",
          activity_sequence: 5,
        });
      if (path === "context/entries")
        return Response.json({
          id: body.id,
          revision: 1,
          ...(body.data as object),
          updated_at: "2026-11-02T17:00:00Z",
          activity_sequence: 6,
        });
      return new Response(null, { status: 404 });
    }),
  );
});

describe("available reading material is separate from source metadata", () => {
  it("opens the exact-version PDF excerpts on entry without a discovery click", async () => {
    const item = work({ access_state: "metadata", abstract: "", available_scopes: ["excerpt"],
      reading_access_state: "excerpt", retained_materials: [available()] });
    state.works = [item];
    render(<LiveReader id={item.work_id} />);
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.getByRole("heading", {name:"Retained document excerpts"})).toBeInTheDocument();
    expect(calls.some(call=>call.path===`materials/${MAT}`)).toBe(true);
    expect(screen.queryByText(/No abstract or full text was acquired/)).not.toBeInTheDocument();
    expect(item.access_state).toBe("metadata");
  });
  it("cards expose retained excerpts and their original-page entry instead of metadata-only copy", () => {
    const item = work({ access_state:"metadata", abstract:"", available_scopes:["excerpt"],
      reading_access_state:"excerpt",retained_materials:[available()] });
    render(<WorkCard item={item} status={vi.fn()} />);
    expect(screen.getByText("PDF excerpts")).toBeInTheDocument();
    expect(screen.getByText(/Selected original PDF pages/)).toBeInTheDocument();
    expect(screen.getByRole("link",{name:"Read & investigate →"})).toHaveAttribute("href",expect.stringContaining(encodeURIComponent(available().first_anchor!)));
  });
  it("retains the legacy card action contract while the controller owns live actions", async () => {
    const item = work(), status = vi.fn(), user = userEvent.setup();
    const view = render(<WorkCard item={item} status={status} />);
    await user.click(screen.getByRole("button", { name: `Save ${item.title}` }));
    await user.click(screen.getByRole("button", { name: `Dismiss ${item.title}` }));
    await user.click(screen.getByRole("button", { name: `Snooze one day ${item.title}` }));
    expect(status.mock.calls).toEqual([[item, "saved"], [item, "dismissed"], [item, "snoozed"]]);
    const saved = { ...item, reading: { ...item.reading, status: "saved" as const } };
    view.rerender(<WorkCard item={saved} status={status} />);
    await user.click(screen.getByRole("button", { name: `Unsave ${item.title}` }));
    expect(status).toHaveBeenLastCalledWith(saved, "unread");
    view.rerender(<WorkCard item={saved} busy status={status} />);
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
    await user.click(screen.getByRole("button", { name: `Unsave ${item.title}` }));
    expect(status).toHaveBeenCalledTimes(4);
    expect(screen.getByRole("link", { name: "Read & investigate →" })).toHaveAttribute("href", expect.stringContaining(encodeURIComponent(item.version_id)));
  });
  it("retained material on an earlier version does not label a newer version acquired", () => {
    const item=work();item.retained_materials=[];item.available_scopes=["abstract"];
    item.versions[0]!.retained_materials=[available({version_id:item.versions[0]!.version_id})];
    item.versions[0]!.available_scopes=["excerpt"];
    const view=render(<WorkCard item={item} versionId={item.version_id} status={vi.fn()} />);
    expect(screen.queryByText("PDF excerpts")).not.toBeInTheDocument();
    view.rerender(<WorkCard item={item} versionId={item.versions[0]!.version_id} status={vi.fn()} />);
    expect(screen.getByText("PDF excerpts")).toBeInTheDocument();
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.getSelection()?.removeAllRanges();
});
function standalone(anchor = "abstract:0") {
  const onNavigate = vi.fn(),
    onSelect = vi.fn(),
    onActive = vi.fn(),
    announce = vi.fn();
  function Harness() {
    const [current, setCurrent] = useState(anchor);
    return (
      <RetainedSourceReader
        workId={work().work_id}
        versionId={work().version_id}
        anchor={current}
        onNavigate={(value) => {
          onNavigate(value);
          setCurrent(value);
        }}
        onSelect={onSelect}
        onActive={onActive}
        announce={announce}
      />
    );
  }
  const result = render(<Harness />);
  return { ...result, onNavigate, onSelect, onActive, announce };
}
async function openDocument(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole("button", { name: "Find retained PDF excerpts" }),
  );
  await user.selectOptions(
    await screen.findByLabelText("Retained document"),
    MAT,
  );
  return screen.findByRole("region", { name: /Original page 3, characters/ });
}
describe("retained document reading", () => {
  it("preserves original page numbers and extraction boundaries, then selects Unicode code-point offsets", async () => {
    const user = userEvent.setup();
    const view = standalone();
    const page = await openDocument(user);
    expect(
      screen.getByRole("region", { name: /Original page 7, characters/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: /Original page 1,/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/This is an excerpt of the paper/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Equations, tables and omitted methods/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open original PDF ↗" }),
    ).toHaveAttribute("href", "https://arxiv.org/pdf/2610.00001v2");
    const paragraph = page.querySelector(".workspace-retained-text")!;
    const range = document.createRange();
    range.setStart(paragraph.querySelector("mark")!.firstChild!, 3);
    range.setEnd(paragraph.querySelector("mark")!.firstChild!, 14);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    fireEvent.mouseUp(paragraph);
    expect(view.onSelect).toHaveBeenCalledWith(
      `material:${MAT}:page:3:2:13`,
      "A retrieval",
    );
    expect(view.onNavigate).toHaveBeenCalledWith(
      `material:${MAT}:page:3:0:${Array.from(text).length}`,
    );
    await user.click(
      screen.getByText("Source version, hash and extraction receipt"),
    );
    expect(
      screen.getByRole("region", { name: "Retained source provenance" }),
    ).toHaveTextContent("bounded-text");
    await user.click(
      screen.getByRole("button", {
        name: "Return to this version’s abstract or metadata",
      }),
    );
    expect(view.onActive).toHaveBeenLastCalledWith(false);
    expect(view.onNavigate).toHaveBeenLastCalledWith("abstract:0");
  });
  it("restores the exact material, page and highlighted passage from a saved note, then persists the same reading anchor", async () => {
    const anchor = `material:${MAT}:page:3:2:13`;
    state.works[0]!.entries = [
      {
        id: "saved-pdf-question",
        revision: 1,
        work_id: work().work_id,
        version_id: work().version_id,
        kind: "question",
        body: "Does this hold for my retrieval setup?",
        anchor,
        updated_at: "2026-11-02T16:00:00Z",
        activity_sequence: 4,
      },
    ];
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}?entry=saved-pdf-question&version=${encodeURIComponent(work().version_id)}`,
    );
    render(<LiveReader id={work().work_id} />);
    const page = await screen.findByRole("region", {
      name: /Original page 3, characters/,
    });
    expect(
      within(page).getByText("A retrieval", { selector: "mark" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Retained document excerpts" }),
    ).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mark read" }));
    expect(calls.find((call) => call.path === "context/reading")?.body).toMatchObject({
      data: { anchor, status: "read", version_id: work().version_id },
    });
    await user.click(screen.getByRole("link", { name: "Understand" }));
    expect(
      calls.filter((call) => call.path === "context/reading").at(-1)?.body,
    ).toMatchObject({ data: { anchor } });
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });
  it("keeps a PDF passage attached through save and recovery without rebinding an unsaved note merely by opening another material", async () => {
    const user = userEvent.setup();
    const view = render(<LiveReader id={work().work_id} />);
    await screen.findByRole("heading", { name: "Retained source abstract" });
    await user.type(screen.getByLabelText("Your question"), "My own question");
    const page = await openDocument(user);
    expect(screen.getByText("Anchor: abstract:0")).toBeInTheDocument();
    const paragraph = page.querySelector(".workspace-retained-text")!;
    const range = document.createRange();
    range.setStart(paragraph.querySelector("mark")!.firstChild!, 0);
    range.setEnd(paragraph.querySelector("mark")!.firstChild!, 14);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    fireEvent.keyUp(paragraph, { key: "Shift" });
    const anchor = `material:${MAT}:page:3:0:13`;
    expect(screen.getByText(`Anchor: ${anchor}`)).toBeInTheDocument();
    view.unmount();
    render(<LiveReader id={work().work_id} />);
    await screen.findByRole("region", { name: /Original page 3, characters/ });
    expect(screen.getByLabelText("Your question")).toHaveValue(
      "My own question",
    );
    expect(document.querySelector("mark")).toHaveTextContent("🧭 A retrieval");
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(calls.find((call) => call.path === "context/entries")?.body).toMatchObject({
      data: { anchor, body: "My own question", version_id: work().version_id },
    });
  });
  it("refuses identity mismatches and preserves notes when listing or restoring material fails", async () => {
    responses.materials = 503;
    const user = userEvent.setup();
    const view = standalone();
    await user.click(
      screen.getByRole("button", { name: "Find retained PDF excerpts" }),
    );
    expect(
      await screen.findByText(/Retained material could not be opened/),
    ).toHaveTextContent("notes and saved anchor are unchanged");
    delete responses.materials;
    documentValue = retained({ version_id: "another-version" });
    await user.click(
      screen.getByRole("button", { name: "Find retained PDF excerpts" }),
    );
    await user.selectOptions(
      await screen.findByLabelText("Retained document"),
      MAT,
    );
    expect(
      await screen.findByText(/Retained material could not be opened/),
    ).toBeInTheDocument();
    expect(view.onActive).not.toHaveBeenCalledWith(true);
  });
  it("shows an honest no-pages state and never turns an unsafe provenance URL into a link", async () => {
    documentValue = retained({ page_count: null });
    const user = userEvent.setup();
    const view = standalone();
    await user.click(
      screen.getByRole("button", { name: "Find retained PDF excerpts" }),
    );
    expect(
      await screen.findByText(/No document pages are retained/),
    ).toBeInTheDocument();
    view.unmount();
    documentValue = retained({
      provenance: {
        source_url: "javascript:alert(1)",
        pdf_url: "https://owner:secret@example.org/x.pdf",
        original_url: "not a URL",
      },
    });
    standalone(`material:${MAT}:page:3:0:1`);
    await screen.findByRole("region", { name: /Original page 3, characters/ });
    expect(
      screen.queryByRole("link", { name: "Open original PDF ↗" }),
    ).not.toBeInTheDocument();
  });
  it("rejects malformed, reversed and unsafe-number material anchors", () => {
    for (const value of [
      "abstract:0",
      "material:mat-x:page:0:0:1",
      "material:mat-x:page:3:2:1",
      "material:mat-x:page:3:0:9999999999999999999999",
      "material:mat-x:page:3:-1:1",
    ])
      expect(parseMaterialAnchor(value)).toBeNull();
    expect(parseMaterialAnchor(`material:${MAT}:page:7:10:20`)).toEqual({
      materialId: MAT,
      page: 7,
      start: 10,
      end: 20,
    });
  });
  it("moves keyboard focus into the selected Reader section and leaves a PDF view when editing an abstract-anchored note", async () => {
    state.works[0]!.entries = [
      {
        id: "abstract-question",
        revision: 1,
        work_id: work().work_id,
        version_id: work().version_id,
        kind: "question",
        body: "A question about the abstract",
        anchor: "abstract:2:13",
        updated_at: "2026-11-02T16:00:00Z",
        activity_sequence: 4,
      },
    ];
    const user = userEvent.setup();
    render(<LiveReader id={work().work_id} />);
    await screen.findByRole("heading", { name: "Retained source abstract" });
    await openDocument(user);
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    expect(document.getElementById("notes")).toHaveFocus();
    await user.tab();
    expect(screen.getByLabelText("Save as")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Edit question" }));
    expect(
      await screen.findByRole("heading", { name: "Retained source abstract" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: /Original page 3, characters/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue(
      "A question about the abstract",
    );
  });
  it("keeps an unavailable saved material visibly unavailable without substituting another version", async () => {
    responses[`materials/${MAT}`] = 404;
    const view = standalone(`material:${MAT}:page:3:2:13`);
    expect(
      await screen.findByText(/Retained material could not be opened/),
    ).toBeInTheDocument();
    expect(view.onActive).toHaveBeenLastCalledWith(false);
    expect(view.onNavigate).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("region", { name: /Original page 3, characters/ }),
    ).not.toBeInTheDocument();
  });
  it("returns from a cached synthetic result to the exact retained PDF evidence and saves that reading anchor", async () => {
    const user = userEvent.setup();
    render(<LiveReader id={work().work_id} />);
    await screen.findByRole("heading", { name: "Retained source abstract" });
    await user.click(screen.getByRole("link", { name: "Understand" }));
    await user.click(
      await screen.findByRole("button", { name: "Choose retained source context" }),
    );
    await user.selectOptions(
      await screen.findByLabelText("Source context"),
      MAT,
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Preview exact synthetic request",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Run synthetic workflow · $0",
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: /Inspect retained evidence/ }),
    );
    const page = await screen.findByRole("region", {
      name: /Original page 3, characters/,
    });
    expect(
      within(page).getByText("A retrieval", { selector: "mark" }),
    ).toBeInTheDocument();
    expect(
      calls.filter((call) => call.path === "context/reading").at(-1)!.body,
    ).toMatchObject({
      data: {
        anchor: `material:${MAT}:page:3:2:13`,
        version_id: work().version_id,
      },
    });
    expect(document.getElementById("source")).toHaveFocus();
    expect(window.location.hash).toContain(
      encodeURIComponent(`material:${MAT}:page:3:2:13`),
    );
    expect(calls.some((call) => call.path.endsWith("/advance"))).toBe(false);
  });
  it("opens the original PDF from a nested acquisition receipt without implying omitted structures were acquired", async () => {
    documentValue = retained({
      provenance: {
        acquisition: {
          requested_url: "https://arxiv.org/pdf/2610.00001v2",
          fetched_at: "2026-11-02T15:00:00Z",
        },
      },
    });
    standalone(`material:${MAT}:page:3:999:1001`);
    await screen.findByRole("region", { name: /Original page 3, characters/ });
    expect(
      screen.getByRole("link", { name: "Open original PDF ↗" }),
    ).toHaveAttribute("href", "https://arxiv.org/pdf/2610.00001v2");
    expect(document.querySelector("mark")).toBeNull();
    expect(
      screen.getByText(/Equation and table structure is not reconstructed/),
    ).toBeInTheDocument();
  });
  it("ignores selections outside the source, empty selections, and metadata-only text", async () => {
    const user = userEvent.setup();
    render(<LiveReader id={work().work_id} />);
    await screen.findByRole("heading", { name: "Retained source abstract" });
    const paragraph = document.querySelector(".daily-source-text p")!;
    const heading = screen.getByRole("heading", { level: 1 });
    const range = document.createRange();
    range.selectNodeContents(heading);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    fireEvent.mouseUp(paragraph);
    expect(screen.getByText("Anchor: abstract:0")).toBeInTheDocument();
    range.setStart(paragraph.firstChild!, 1);
    range.setEnd(paragraph.firstChild!, 2);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    fireEvent.mouseUp(paragraph);
    expect(screen.getByText("Anchor: abstract:0")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    expect(screen.getByLabelText("Your question")).toHaveValue("");
  });
  it("keeps legacy metadata-only records useful without invented authors, abstract or generated context", async () => {
    const base = work();
    state = workspace({
      profile: {
        ...workspace().profile,
        data: { ...workspace().profile.data, research_question: "" },
      },
      works: [
        work({
          abstract: "",
          authors: [],
          access_state: "metadata",
          reading: {
            ...base.reading,
            status: "saved",
            anchor: "metadata:0",
            version_id: base.version_id,
          },
          versions: [
            {
              ...base.versions[1]!,
              title: "",
              url: "",
              abstract: "",
              authors: [],
              access_state: "metadata",
              source_scope: "metadata",
            },
          ],
        }),
      ],
    });
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}?version=${encodeURIComponent(base.version_id)}&return_to=%2Fworkspace%2Fradar#understand`,
    );
    const user = userEvent.setup();
    render(<LiveReader id={base.work_id} />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      base.title,
    );
    expect(screen.getByRole("link", { name: "← Radar" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Source metadata" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No abstract or full text was acquired/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Add a research question in Interests/),
    ).toBeInTheDocument();
    fireEvent.mouseUp(document.querySelector(".daily-source-text p")!);
    expect(screen.getByText("Anchor: metadata:0")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Remove from saved items" }),
    );
    expect(
      calls.filter((call) => call.path === "context/reading").at(-1)!.body,
    ).toMatchObject({
      data: {
        status: "unread",
        anchor: "metadata:0",
        version_id: base.version_id,
      },
    });
    expect(
      screen.getByRole("link", { name: "Open original source ↗" }),
    ).toHaveAttribute("href", base.url);
  });
});

// D5 integration: the heavy panel is verified separately; this pins the lazy
// Reader entry and exact retained-passage callback without a provider client.
vi.mock("@/components/workspace/AssistancePanel", () => ({ default: ({ onSource }: {onSource:(anchor:string)=>void}) => <button onClick={() => onSource(`material:${MAT}:page:3:0:14`)}>Test exact assistance passage</button> }));
it("opens assistance explicitly and routes its exact passage back into Source", async () => {
  const user = userEvent.setup(); render(<LiveReader id={work().work_id}/>);
  await screen.findByRole("heading", {name:"Retained source abstract"});
  await user.click(screen.getByRole("link", {name:"Understand"}));
  expect(screen.queryByRole("button", {name:"Test exact assistance passage"})).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", {name:"Open assisted reading · local simulation"}));
  await user.click(await screen.findByRole("button", {name:"Test exact assistance passage"}));
  expect(decodeURIComponent(location.hash)).toContain(`material:${MAT}:page:3:0:14`);
  expect(calls.filter(call=>call.path==="context/reading").at(-1)!.body).toMatchObject({data:{version_id:work().version_id,anchor:`material:${MAT}:page:3:0:14`}});
});
it("resumes a saved simulated result without dispatching and preserves its exact version",async()=>{
 const base=work(),id=`assistance-fake-${"e".repeat(40)}`;
 state.works=[work({entries:[{id,revision:1,work_id:base.work_id,version_id:base.version_id,anchor:"abstract:0:14",kind:"note",body:"Saved simulation",updated_at:"2026-11-05T00:00:00Z",activity_sequence:1}]})];
 const user=userEvent.setup();render(<LiveReader id={base.work_id}/>);await screen.findByRole("heading",{name:"Retained source abstract"});
 await user.click(screen.getByRole("link",{name:"Your notes"}));
 expect(screen.getByRole("link",{name:"Resume saved assistance →"})).toHaveAttribute("href",expect.stringContaining(`assistance=fake-${"e".repeat(40)}`));
 expect(calls.filter(c=>c.path.startsWith("assistance/jobs"))).toHaveLength(0);
});
