import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntheticWorkbench } from "@/components/workspace/SyntheticWorkbench";
import type { FakeJob, MaterialDocument } from "@/lib/workspace/api";
import { work } from "./fixtures";
import { MAT, SPAN, retained } from "./materialFixtures";

import { JOB, draft, job, preview } from "./syntheticFixtures";
let material: MaterialDocument;
let materialList: MaterialDocument[];
let failures: Record<string, number>;
let calls: { path: string; body: Record<string, unknown> }[];
let checkpoints: FakeJob[];
let history: FakeJob[];
let advanceWait: Promise<FakeJob> | null;
let resolveAdvance: ((value: FakeJob) => void) | null;
beforeEach(() => {
  material = retained();
  materialList = [material];
  failures = {};
  calls = [];
  history = [];
  advanceWait = null;
  resolveAdvance = null;
  checkpoints = [
    job("checking", 2),
    job("repairing", 3),
    job("checking", 4),
    job("ready", 5),
  ];
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
      if (path === "materials") return Response.json(materialList);
      if (path.startsWith("materials/")) return Response.json(material);
      if (path === "generation/preview") return Response.json(preview());
      if (path === "generation/jobs")
        return Response.json(init?.method === "POST" ? job() : history);
      if (path === `generation/jobs/${JOB}/advance`)
        return Response.json(
          advanceWait
            ? await advanceWait
            : (checkpoints.shift() ?? job("queued", 1)),
        );
      if (path === `generation/jobs/${JOB}/cancel`)
        return Response.json(job("cancelled", 3));
      if (path === `generation/jobs/${JOB}/recover`)
        return Response.json(job("queued", 4));
      if (path === `generation/jobs/${JOB}`)
        return Response.json(job("interrupted", 3));
      return new Response(null, { status: 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());
function setup() {
  const announce = vi.fn(),
    onSource = vi.fn();
  return {
    ...render(
      <SyntheticWorkbench
        workId={work().work_id}
        versionId={work().version_id}
        announce={announce}
        onSource={onSource}
      />,
    ),
    announce,
    onSource,
  };
}
async function choose(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole("button", { name: "Choose retained source context" }),
  );
  await user.selectOptions(await screen.findByLabelText("Source context"), MAT);
  await screen.findByRole("button", {
    name: "Preview exact synthetic request",
  });
}
async function prepared(user: ReturnType<typeof userEvent.setup>) {
  await choose(user);
  await user.click(
    screen.getByRole("button", { name: "Preview exact synthetic request" }),
  );
  await screen.findByRole("button", { name: "Run synthetic workflow · $0" });
}

describe("explicit zero-spend synthetic workbench", () => {
  it("does not load context or create work until invoked and requires preview before run", async () => {
    const user = userEvent.setup();
    setup();
    expect(calls).toHaveLength(0);
    expect(
      screen.getByText(/Your notes, profile and reading history are excluded/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run synthetic workflow · $0" }),
    ).not.toBeInTheDocument();
    await choose(user);
    expect(calls.every((call) => call.path.startsWith("materials"))).toBe(true);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    );
    expect(
      calls.find((call) => call.path === "generation/preview")!.body,
    ).toEqual({
      kind: "summary",
      material_ids: [MAT],
      span_ids: [],
      question: "",
    });
    expect(
      screen.getByRole("region", { name: "Exact synthetic request JSON" }),
    ).toHaveTextContent('"notes": false');
    expect(calls.some((call) => call.path === "generation/jobs")).toBe(false);
  });
  it("runs at most four foreground stages and exposes simulated split usage, diagnostics and exact source evidence", async () => {
    const user = userEvent.setup();
    const view = setup();
    await prepared(user);
    await user.click(
      screen.getByRole("button", { name: "Run synthetic workflow · $0" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Synthetic checkpoint · ready",
      }),
    ).toBeInTheDocument();
    expect(calls.filter((call) => call.path.endsWith("/advance"))).toHaveLength(
      4,
    );
    expect(
      calls.find((call) => call.path === "generation/jobs")!.body,
    ).toMatchObject({
      expected_digest: "digest-exact-context",
      material_ids: [MAT],
      request_id: expect.any(String),
    });
    expect(screen.getByText("1200 in / 300 out")).toBeInTheDocument();
    expect(screen.getByText("400 in / 50 out")).toBeInTheDocument();
    expect(screen.getByText("0 in / 0 out")).toBeInTheDocument();
    expect(
      screen.getByText(/This result has not qualified a real model/),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Inspect retained evidence/ }),
    );
    expect(view.onSource).toHaveBeenCalledWith(`material:${MAT}:page:3:2:13`);
    await user.click(
      screen.getByText("Synthetic check diagnostics · not a quality score"),
    );
    expect(
      screen.getByRole("region", { name: "Synthetic check diagnostics" }),
    ).toHaveTextContent('"supported": 1');
    expect(
      screen.getByText("Inference · proposal, not verified"),
    ).toBeInTheDocument();
    expect(screen.getByText("Write a bounded test.")).toBeInTheDocument();
  });
  it("takes a typed question only after opt-in and invalidates a preview when any context input changes", async () => {
    const user = userEvent.setup();
    setup();
    await prepared(user);
    await user.click(
      screen.getByRole("checkbox", {
        name: "Include a question I type for this synthetic request",
      }),
    );
    expect(
      screen.queryByRole("button", { name: "Run synthetic workflow · $0" }),
    ).not.toBeInTheDocument();
    await user.type(
      screen.getByLabelText("Optional request question"),
      "Which assumptions would I test?",
    );
    await user.selectOptions(
      screen.getByLabelText("Synthetic workflow"),
      "deep_dive",
    );
    await user.click(screen.getAllByRole("checkbox")[0]!);
    await user.click(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    );
    expect(
      calls.filter((call) => call.path === "generation/preview").at(-1)!.body,
    ).toMatchObject({
      kind: "deep_dive",
      question: "Which assumptions would I test?",
      span_ids: [SPAN],
    });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Include a question I type for this synthetic request",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    );
    expect(
      calls.filter((call) => call.path === "generation/preview").at(-1)!.body
        .question,
    ).toBe("");
  });
  it("refuses an oversized whole source locally, allowing a bounded explicit passage without truncation", async () => {
    const user = userEvent.setup();
    material = retained({
      spans: Array.from({ length: 5 }, (_, index) => ({
        ...retained().spans[0]!,
        span_id: `span-${index}`,
        text: index === 0 ? "🧭".repeat(2500) : `Short source passage ${index}`,
      })),
    });
    materialList = [material];
    setup();
    await choose(user);
    expect(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Choose a smaller explicit passage set/),
    ).toBeInTheDocument();
    await user.click(screen.getAllByRole("checkbox")[1]!);
    expect(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    ).toBeEnabled();
    await user.click(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    );
    expect(
      calls.find((call) => call.path === "generation/preview")!.body.span_ids,
    ).toEqual(["span-1"]);
  });
  it("preserves a failed create request's idempotency key and stops a foreground run when a stage does not advance", async () => {
    const user = userEvent.setup();
    setup();
    await prepared(user);
    failures["generation/jobs"] = 503;
    await user.click(
      screen.getByRole("button", { name: "Run synthetic workflow · $0" }),
    );
    expect(
      await screen.findByText(/The synthetic action did not complete/),
    ).toBeInTheDocument();
    const first = calls.find((call) => call.path === "generation/jobs")!.body
      .request_id;
    delete failures["generation/jobs"];
    checkpoints = [job()];
    await user.click(
      screen.getByRole("button", { name: "Run synthetic workflow · $0" }),
    );
    await screen.findByRole("button", { name: "Advance one synthetic step" });
    expect(
      calls.filter((call) => call.path === "generation/jobs").at(-1)!.body
        .request_id,
    ).toBe(first);
    expect(calls.filter((call) => call.path.endsWith("/advance"))).toHaveLength(
      1,
    );
    expect(
      screen.getByRole("button", { name: "Run synthetic workflow · $0" }),
    ).toBeDisabled();
  });
  it("cancels while a step is pending and never overwrites the cancellation with its late response", async () => {
    const user = userEvent.setup();
    setup();
    await prepared(user);
    advanceWait = new Promise((resolve) => {
      resolveAdvance = resolve;
    });
    await user.click(
      screen.getByRole("button", { name: "Run synthetic workflow · $0" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Cancel synthetic run" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Synthetic checkpoint · cancelled",
      }),
    ).toBeInTheDocument();
    await act(async () => {
      resolveAdvance!(job("checking", 2));
    });
    expect(
      screen.getByRole("heading", { name: "Synthetic checkpoint · cancelled" }),
    ).toBeInTheDocument();
    expect(calls.filter((call) => call.path.endsWith("/advance"))).toHaveLength(
      1,
    );
  });
  it("stops further advances after leaving the component and retains the last server checkpoint", async () => {
    const user = userEvent.setup();
    const view = setup();
    await prepared(user);
    advanceWait = new Promise((resolve) => {
      resolveAdvance = resolve;
    });
    await user.click(
      screen.getByRole("button", { name: "Run synthetic workflow · $0" }),
    );
    await screen.findByRole("button", { name: "Cancel synthetic run" });
    view.unmount();
    await act(async () => {
      resolveAdvance!(job("checking", 2));
    });
    expect(calls.filter((call) => call.path.endsWith("/advance"))).toHaveLength(
      1,
    );
    expect(calls.some((call) => call.path.endsWith("/cancel"))).toBe(false);
  });
  it("loads only this source version's checkpoints and permits explicit reload, recovery and one-step advance", async () => {
    const user = userEvent.setup();
    setup();
    history = [
      job("interrupted", 3),
      {
        ...job("ready", 5),
        id: "other-source",
        request: { sources: [{ work_id: "other", version_id: "other:v1" }] },
      },
      { ...job(), id: "no-sources", request: {} },
    ];
    await user.click(
      screen.getByRole("button", {
        name: "Load this version’s synthetic checkpoints",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: `summary · interrupted · ${JOB}`,
      }),
    );
    expect(screen.queryByText(/other-source/)).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Recover expired checkpoint" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Synthetic checkpoint · queued",
      }),
    ).toBeInTheDocument();
    checkpoints = [job("checking", 5)];
    await user.click(
      screen.getByRole("button", { name: "Advance one synthetic step" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Synthetic checkpoint · checking",
      }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reload checkpoint" }));
    expect(
      await screen.findByRole("heading", {
        name: "Synthetic checkpoint · interrupted",
      }),
    ).toBeInTheDocument();
  });
  it("shows honest empty and failure states without fabricating material, history or a preview", async () => {
    const user = userEvent.setup();
    setup();
    materialList = [];
    await user.click(
      screen.getByRole("button", { name: "Choose retained source context" }),
    );
    expect(
      await screen.findByText(/No retained text is available/),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "Load this version’s synthetic checkpoints",
      }),
    );
    expect(
      await screen.findByText(/No synthetic checkpoints are retained/),
    ).toBeInTheDocument();
    failures.materials = 503;
    await user.click(
      screen.getByRole("button", { name: "Choose retained source context" }),
    );
    expect(
      await screen.findByText(/The synthetic action did not complete/),
    ).toBeInTheDocument();
    delete failures.materials;
    materialList = [material];
    await choose(user);
    failures["generation/preview"] = 409;
    await user.click(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    );
    expect(
      await screen.findByText(/The synthetic action did not complete/),
    ).toHaveTextContent("record changed in another tab");
    expect(
      screen.queryByRole("button", { name: "Run synthetic workflow · $0" }),
    ).not.toBeInTheDocument();
  });
  it("rejects a mismatched material version and clears selected context on an explicit deselection", async () => {
    const user = userEvent.setup();
    setup();
    material = retained({ version_id: "different:v1" });
    await user.click(
      screen.getByRole("button", { name: "Choose retained source context" }),
    );
    await user.selectOptions(
      await screen.findByLabelText("Source context"),
      MAT,
    );
    expect(
      await screen.findByText(/The synthetic action did not complete/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Preview exact synthetic request" }),
    ).not.toBeInTheDocument();
    material = retained();
    await user.selectOptions(screen.getByLabelText("Source context"), MAT);
    await screen.findByRole("button", {
      name: "Preview exact synthetic request",
    });
    await user.selectOptions(screen.getByLabelText("Source context"), "");
    expect(
      screen.queryByRole("button", { name: "Preview exact synthetic request" }),
    ).not.toBeInTheDocument();
  });
  it("reports checkpoint failures without discarding the inspectable state and retries recovery explicitly", async () => {
    const user = userEvent.setup();
    setup();
    history = [job("interrupted", 3)];
    failures["generation/jobs"] = 503;
    await user.click(
      screen.getByRole("button", {
        name: "Load this version’s synthetic checkpoints",
      }),
    );
    expect(
      await screen.findByText(/The synthetic action did not complete/),
    ).toBeInTheDocument();
    delete failures["generation/jobs"];
    await user.click(
      screen.getByRole("button", {
        name: "Load this version’s synthetic checkpoints",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: `summary · interrupted · ${JOB}`,
      }),
    );
    failures[`generation/jobs/${JOB}/recover`] = 503;
    await user.click(
      screen.getByRole("button", { name: "Recover expired checkpoint" }),
    );
    expect(
      await screen.findByText(/The synthetic action did not complete/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Synthetic checkpoint · interrupted",
      }),
    ).toBeInTheDocument();
    delete failures[`generation/jobs/${JOB}/recover`];
    await user.click(
      screen.getByRole("button", { name: "Recover expired checkpoint" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Synthetic checkpoint · queued",
      }),
    ).toBeInTheDocument();
    failures[`generation/jobs/${JOB}/cancel`] = 503;
    await user.click(
      screen.getByRole("button", { name: "Cancel synthetic run" }),
    );
    expect(
      await screen.findByText(/The synthetic action did not complete/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Synthetic checkpoint · queued" }),
    ).toBeInTheDocument();
  });
  it("displays cached partial results and unverified inference separately, with abstract evidence returning to its actual offsets", async () => {
    const user = userEvent.setup();
    const view = setup();
    const value = job("ready", 3);
    value.state = "ready_partial";
    value.cached = true;
    value.cancel_requested = true;
    value.error = "fixture_abstained";
    value.draft = {
      ...draft(),
      questions: [],
      proposed_actions: [],
      limitations: [],
      claims: draft().claims.map((claim) => ({
        ...claim,
        inference_label: null,
        evidence: claim.evidence.map((evidence) => ({
          ...evidence,
          scope: "abstract",
          page: null,
        })),
      })),
    };
    value.result = null;
    history = [
      value,
      {
        ...job(),
        id: "malformed-context",
        request: {
          sources: [
            null,
            3,
            {},
            { work_id: "other" },
            { work_id: work().work_id, version_id: "other" },
          ],
        },
      },
    ];
    await user.click(
      screen.getByRole("button", {
        name: "Load this version’s synthetic checkpoints",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: `summary · ready partial · ${JOB}`,
      }),
    );
    expect(
      screen.getByText(/identical synthetic result reused from cache/),
    ).toBeInTheDocument();
    expect(screen.getByText("Stopped: fixture_abstained")).toBeInTheDocument();
    expect(
      screen.getByText("Inference · unverified proposal"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Cancellation requested/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel synthetic run" }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Inspect retained evidence/ }),
    );
    expect(view.onSource).toHaveBeenCalledWith("abstract:2:13");
  });
  it("retries a failed material read, handles empty extracted text and clears a stale preview before another workflow", async () => {
    const user = userEvent.setup();
    setup();
    failures[`materials/${MAT}`] = 503;
    await user.click(
      screen.getByRole("button", { name: "Choose retained source context" }),
    );
    await user.selectOptions(
      await screen.findByLabelText("Source context"),
      MAT,
    );
    expect(
      await screen.findByText(/The synthetic action did not complete/),
    ).toBeInTheDocument();
    delete failures[`materials/${MAT}`];
    material = retained({ spans: [] });
    await user.selectOptions(screen.getByLabelText("Source context"), MAT);
    expect(
      await screen.findByRole("button", {
        name: "Preview exact synthetic request",
      }),
    ).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Source context"), "");
    material = retained({ complete: true, page_numbers: null });
    materialList = [material];
    await user.click(
      screen.getByRole("button", { name: "Choose retained source context" }),
    );
    await user.selectOptions(screen.getByLabelText("Source context"), MAT);
    await user.click(
      await screen.findByRole("button", {
        name: "Preview exact synthetic request",
      }),
    );
    expect(
      await screen.findByRole("button", {
        name: "Run synthetic workflow · $0",
      }),
    ).toBeEnabled();
    await user.selectOptions(
      screen.getByLabelText("Synthetic workflow"),
      "deep_dive",
    );
    expect(
      screen.queryByRole("button", { name: "Run synthetic workflow · $0" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("checkbox")[0]!);
    await user.click(screen.getAllByRole("checkbox")[0]!);
    await user.click(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    );
    expect(
      calls.filter((call) => call.path === "generation/preview").at(-1)!.body
        .span_ids,
    ).toEqual([]);
  });
  it("uses a new explicit request after cancelling an acknowledged run while retaining failed-create retry identity", async () => {
    const user = userEvent.setup();
    setup();
    await prepared(user);
    checkpoints = [job()];
    await user.click(
      screen.getByRole("button", { name: "Run synthetic workflow · $0" }),
    );
    await screen.findByRole("button", { name: "Advance one synthetic step" });
    const first = calls.find((call) => call.path === "generation/jobs")!.body
      .request_id;
    await user.click(
      screen.getByRole("button", { name: "Cancel synthetic run" }),
    );
    await screen.findByRole("heading", {
      name: "Synthetic checkpoint · cancelled",
    });
    await user.click(
      screen.getByRole("button", { name: "Preview exact synthetic request" }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Run synthetic workflow · $0",
      }),
    );
    await screen.findByRole("button", { name: "Advance one synthetic step" });
    const creates = calls.filter((call) => call.path === "generation/jobs");
    expect(creates).toHaveLength(2);
    expect(creates[1]!.body.request_id).not.toBe(first);
    expect(creates[1]!.body.expected_digest).toBe(
      creates[0]!.body.expected_digest,
    );
  });
});
