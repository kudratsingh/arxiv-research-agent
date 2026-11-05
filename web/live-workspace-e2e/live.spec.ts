import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { WorkspaceState } from "../lib/workspace/api";

/** Real loopback API + Postgres only. Failure injection aborts one save; no fixture responses fill the live UI. */
test.describe.configure({ mode: "serial" });

// Controller filters/view/export live once in the responsive sidebar.
async function openControls(page: import("@playwright/test").Page) {
  const toggle = page.getByRole("button", { name: "Queue & controls", exact: true });
  if (await toggle.isVisible() && await toggle.getAttribute("aria-expanded") === "false") await toggle.click();
}
async function closeControls(page: import("@playwright/test").Page) {
  const toggle = page.getByRole("button", { name: "Queue & controls", exact: true });
  if (await toggle.isVisible() && await toggle.getAttribute("aria-expanded") === "true") await page.keyboard.press("Escape");
}

async function realState(page: import("@playwright/test").Page) {
  const response = await page.request.get("/api/workspace/state");
  expect(response.ok()).toBe(true);
  const state = (await response.json()) as WorkspaceState;
  expect(state.principal_key_id).toBeTruthy();
  const principal = process.env.WORKSPACE_VERIFICATION_PRINCIPAL ?? "e2e";
  expect(
    principal,
    "Write walkthroughs require an isolated verification principal.",
  ).not.toBe("personal-local");
  expect(state.principal_key_id).toBe(principal);
  expect(state.generation).toBe("approval_required");
  expect(state.sources.length).toBe(5);
  return state;
}

test.beforeEach(async ({ page }) => {
  await realState(page);
});

test("real Today → source → server-saved question → reload → Library export", async ({
  page,
}, testInfo) => {
  const state = await realState(page);
  const item = state.works.find(
    (work) => work.abstract && !work.source_id.startsWith("preview"),
  );
  expect(
    item,
    "Run the bounded intake command first; the live walkthrough never substitutes a fictional source.",
  ).toBeTruthy();
  await page.goto("/workspace/today");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "What changed",
  );
  await expect(
    page.getByText(
      "Real source metadata · private server saves · generation off",
    ),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("today.png"),
    fullPage: true,
  });
  await page.goto(
    `/workspace/items/${encodeURIComponent(item!.work_id)}?version=${encodeURIComponent(item!.version_id)}`,
  );
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(item!.title);
  await expect(
    page.getByRole("heading", {
      name:
        item!.access_state === "excerpt"
          ? "Retained feed excerpt"
          : "Retained source abstract",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open original source ↗" }),
  ).toHaveAttribute("href", item!.url);
  const save = page.getByRole("button", {
    name: "Save to Library",
    exact: true,
  });
  if (await save.isVisible()) {
    await save.click();
    await expect(page.getByRole("status")).toContainText(
      "Reading state saved on the server",
    );
  }
  await page.getByRole("link", { name: "Your notes", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save question", exact: true }),
  ).toBeDisabled();
  const question = `Walkthrough ${testInfo.project.name} ${Date.now()}: which baseline would make this reproducible?`;
  await page
    .getByRole("textbox", { name: "Your question", exact: true })
    .fill(question);
  await page
    .getByRole("button", { name: "Save question", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "is saved on the server",
  );
  await page.reload();
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("reader-notes.png"),
    fullPage: true,
  });
  await page
    .getByRole("navigation", { name: "Research workspace" })
    .getByRole("link", { name: /Library/ })
    .click();
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await openControls(page);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: /Export notes as Markdown/ }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toMatch(/\.md$/);
  await download.saveAs(testInfo.outputPath("notes.md"));
});

test("a failed real save retains the draft across reload and permits recovery", async ({
  page,
}, testInfo) => {
  const state = await realState(page),
    item = state.works.find(
      (work) => work.abstract && !work.source_id.startsWith("preview"),
    )!;
  await page.goto(
    `/workspace/items/${encodeURIComponent(item.work_id)}?version=${encodeURIComponent(item.version_id)}#notes`,
  );
  const text = `Outage recovery ${testInfo.project.name} ${Date.now()}: keep this unsaved question.`;
  await page
    .getByRole("textbox", { name: "Your question", exact: true })
    .fill(text);
  let intercepted = 0;
  // D2 moves Reader writes to the context-aware endpoint. Fail the real
  // emitted request, keeping the outage/reload/retry assertions intact.
  await page.route("**/api/workspace/context/entries", (route) => {
    intercepted++;
    return route.abort("failed");
  });
  await page
    .getByRole("button", { name: "Save question", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("unavailable");
  expect(intercepted).toBe(1);
  await expect(
    page.getByRole("textbox", { name: "Your question", exact: true }),
  ).toHaveValue(text);
  await page.reload();
  await expect(
    page.getByRole("textbox", { name: "Your question", exact: true }),
  ).toHaveValue(text);
  await expect(page.getByRole("status")).toContainText(
    "Recovered your unsaved draft",
  );
  await page.unroute("**/api/workspace/context/entries");
  await page
    .getByRole("button", { name: "Save question", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "is saved on the server",
  );
  await page.reload();
  await expect(page.getByText(text, { exact: true })).toBeVisible();
});

test("real filters, editable interests, honest source receipts and disabled schedule", async ({
  page,
}, testInfo) => {
  await page.goto("/workspace/radar?days=0");
  await expect(
    page.getByRole("heading", { name: "Stored source records" }),
  ).toBeVisible();
  await openControls(page);
  await page
    .getByRole("searchbox", { name: "Search titles and abstracts" })
    .fill("retrieval");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/q=retrieval/);
  await page.screenshot({
    path: testInfo.outputPath("radar.png"),
    fullPage: true,
  });
  await page.goto("/workspace/interests");
  await expect(
    page.getByRole("textbox", { name: "Your current research question" }),
  ).not.toHaveValue("");
  await expect(page.getByText(/384 catalogue entries/)).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("interests.png"),
    fullPage: true,
  });
  await page.goto("/workspace/operations");
  await expect(
    page.getByText("Recurring schedule disabled", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: /Save preferences · keep schedule disabled/,
    }),
  ).toBeVisible();
  const receipt = page
    .getByText("Inspect this check’s receipt", { exact: true })
    .first();
  await receipt.click();
  await expect(page.locator(".workspace-receipt").first()).toContainText(
    "request_count",
  );
  await page.screenshot({
    path: testInfo.outputPath("operations.png"),
    fullPage: true,
  });
  const a11y = await new AxeBuilder({ page }).analyze();
  expect(
    a11y.violations.filter((violation) =>
      ["critical", "serious"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
});

test("keyboard-only source-to-question flow keeps the real server record", async ({
  page,
}, testInfo) => {
  const state = await realState(page);
  const item = state.works.find(
    (work) => work.abstract && !work.source_id.startsWith("preview"),
  )!;
  await page.goto(
    `/workspace/items/${encodeURIComponent(item.work_id)}?version=${encodeURIComponent(item.version_id)}`,
  );
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(item.title);
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to main content" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  const notes = page.getByRole("link", { name: "Your notes", exact: true });
  for (let index = 0; index < 16; index++) {
    if (await notes.evaluate((element) => element === document.activeElement))
      break;
    await page.keyboard.press("Tab");
  }
  await expect(notes).toBeFocused();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("combobox", { name: "Save as" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("textbox", { name: "Your question", exact: true }),
  ).toBeFocused();
  const question = `Keyboard walkthrough ${testInfo.project.name} ${Date.now()}: what evidence should I check?`;
  await page.keyboard.insertText(question);
  await expect(
    page.getByRole("button", { name: "Save question", exact: true }),
  ).toBeEnabled();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Save question", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText(
    "is saved on the server",
  );
  await page.reload();
  await expect(page.getByText(question, { exact: true })).toBeVisible();
});

test("editing an earlier question becomes latest activity, pins its exact version and returns to the Library view", async ({
  page,
}, testInfo) => {
  const initial = await realState(page);
  const item = initial.works.find(
    (work) => work.versions.filter((version) => version.abstract).length > 1,
  );
  expect(
    item,
    "The isolated browser seed must retain two material versions.",
  ).toBeTruthy();
  const earlier = item!.versions.find(
    (version) => version.version_id !== item!.version_id,
  )!;
  const marker = `${testInfo.project.name} ${Date.now()}`;
  const first = `Earlier question ${marker}: which baseline stays fixed?`;
  const later = `Later question ${marker}: how is retrieval measured?`;
  let entryId: string | undefined;
  const originalReading = {
    status: item!.reading.status,
    anchor: item!.reading.anchor,
    version_id: item!.reading.version_id || item!.version_id,
    snoozed_until: item!.reading.snoozed_until,
  };
  async function restoreOrSetReading(data: typeof originalReading) {
    const state = await realState(page);
    const reading = state.works.find(
      (work) => work.work_id === item!.work_id,
    )!.reading;
    const response = await page.request.post("/api/workspace/reading", {
      data: {
        work_id: item!.work_id,
        revision: reading.revision,
        request_id: crypto.randomUUID(),
        data,
      },
    });
    expect(response.ok()).toBe(true);
  }
  try {
    // Keep the edited work unread so Saved cannot accidentally satisfy Notes.
    // Only the guarded verification principal is changed; restore in finally.
    if (item!.reading.status !== "unread") {
      await restoreOrSetReading({
        ...originalReading,
        status: "unread",
        snoozed_until: null,
      });
    }
    for (const [version, question] of [
      [earlier.version_id, first],
      [item!.version_id, later],
    ]) {
      await page.goto(
        `/workspace/items/${encodeURIComponent(item!.work_id)}?version=${encodeURIComponent(version!)}#notes`,
      );
      await page
        .getByRole("textbox", { name: "Your question", exact: true })
        .fill(question!);
      await page
        .getByRole("button", { name: "Save question", exact: true })
        .click();
      await expect(page.getByRole("status")).toContainText(
        "is saved on the server",
      );
    }
    const created = await realState(page);
    entryId = created.works
      .find((work) => work.work_id === item!.work_id)!
      .entries.find((entry) => entry.body === first)!.id;
    await page.goto("/workspace/today");
    await expect(page.locator(".workspace-activity")).toContainText(later);
    await page.goto("/workspace/library?view=notes");
    await openControls(page);
    await expect(
      page.getByRole("combobox", { name: "Library view" }),
    ).toHaveValue("notes");
    await closeControls(page);
    const libraryEntry = page
      .getByRole("article")
      .filter({ has: page.getByText(first, { exact: true }) });
    await libraryEntry
      .getByRole("link", { name: "Resume this question →" })
      .click();
    const resumed = page.locator(`[id="workspace-entry-${entryId}"]`);
    await expect(resumed).toBeFocused();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      earlier.title || item!.title,
    );
    await resumed
      .getByRole("button", { name: "Edit question", exact: true })
      .click();
    const edited = `${first} Edited after inspecting the retained version.`;
    await page
      .getByRole("textbox", { name: "Your question", exact: true })
      .fill(edited);
    await page
      .getByRole("button", { name: "Save question", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText(
      "is saved on the server",
    );
    await page.getByRole("link", { name: "← Library", exact: true }).click();
    await expect(page).toHaveURL(/\/workspace\/library\?view=notes$/);
    await openControls(page);
    await expect(
      page.getByRole("combobox", { name: "Library view" }),
    ).toHaveValue("notes");
    await closeControls(page);
    await expect(page.getByText(edited, { exact: true })).toBeVisible();
    await page.goto("/workspace/today");
    await expect(page.locator(".workspace-activity")).toContainText(edited);
    await page.getByText("Source and pin options", { exact: true }).click();
    await page
      .getByRole("button", { name: "Pin this question", exact: true })
      .click();
    await expect(page.locator(".workspace-activity")).toContainText(
      "Pinned · your question",
    );
    await page.locator(".workspace-activity").getByRole("link").click();
    await expect(resumed).toBeFocused();
    await page.getByRole("button", { name: "Mark read", exact: true }).click();
    await expect(page.getByRole("status")).toContainText(
      "Reading state saved on the server",
    );
    await page.goto("/workspace/today");
    await expect(page.locator(".workspace-activity")).toContainText(edited);
    await page.getByText("Source and pin options", { exact: true }).click();
    await page
      .getByRole("button", { name: "Unpin saved item", exact: true })
      .click();
    await expect(page.locator(".workspace-activity")).toContainText(
      "Latest activity · reading location",
    );
    await page.screenshot({
      path: testInfo.outputPath("activity-and-return.png"),
      fullPage: true,
    });
  } finally {
    const state = await realState(page);
    if (entryId && state.profile.data.pinned_entry_id === entryId) {
      const response = await page.request.post("/api/workspace/profile", {
        data: {
          revision: state.profile.revision,
          request_id: crypto.randomUUID(),
          data: { ...state.profile.data, pinned_entry_id: null },
        },
      });
      expect(response.ok()).toBe(true);
    }
    await restoreOrSetReading(originalReading);
  }
});

test("a frozen candidate review stays unlabelled until an explicit verification judgment is saved", async ({
  page,
}, testInfo) => {
  await page.goto("/workspace/review");
  // P6 moves packet preparation into the single responsive controls slot.
  await openControls(page);
  const prepare = page.getByRole("button", {
    name: /^Prepare (up to 10 candidates|another candidate set)$/,
  });
  await expect(prepare).toBeEnabled();
  const preparedResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/workspace/review/prepare") &&
      response.request().method() === "POST",
  );
  await prepare.click();
  const packet = (await (await preparedResponse).json()) as {
    id: string;
    items: { feedback: { label: string | null } }[];
  };
  expect(packet.items.length).toBeGreaterThan(0);
  expect(packet.items.length).toBeLessThanOrEqual(10);
  expect(
    packet.items.every((candidate) => candidate.feedback.label === null),
  ).toBe(true);
  await expect(
    page.getByRole("heading", {
      name: `${packet.items.length} candidates · 0 labelled`,
      exact: true,
    }),
  ).toBeVisible();
  const candidate = page.getByRole("article").first();
  await candidate.getByRole("radio", { name: "Maybe", exact: true }).check();
  const reason = `Verification-only feedback ${testInfo.project.name} ${Date.now()}; not an owner usefulness label.`;
  await candidate
    .getByRole("textbox", {
      name: "Optional reason for candidate 1",
      exact: true,
    })
    .fill(reason);
  await expect(
    page.getByRole("heading", {
      name: `${packet.items.length} candidates · 0 labelled`,
      exact: true,
    }),
  ).toBeVisible();
  await candidate
    .getByRole("button", { name: "Save judgment for candidate 1", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Your maybe label is saved on the server",
  );
  await candidate
    .getByRole("link", { name: "Inspect retained source →", exact: true })
    .click();
  await page
    .getByRole("link", { name: "← Candidate review", exact: true })
    .click();
  await expect(page).toHaveURL(
    new RegExp(`/workspace/review\\?packet=${packet.id}$`),
  );
  await page.reload();
  await expect(
    page
      .getByRole("article")
      .first()
      .getByRole("radio", { name: "Maybe", exact: true }),
  ).toBeChecked();
  await expect(
    page.getByRole("textbox", {
      name: "Optional reason for candidate 1",
      exact: true,
    }),
  ).toHaveValue(reason);
  await page.screenshot({
    path: testInfo.outputPath("candidate-review.png"),
    fullPage: true,
  });
});

test("an explicit synthetic request uses only selected retained text and exposes its zero-dollar checkpoint", async ({
  page,
}, testInfo) => {
  const state = await realState(page);
  const item = state.works.find(
    (work) => work.abstract && work.access_state !== "metadata",
  )!;
  expect(
    item,
    "The isolated seed must contain an actual stored abstract; the browser does not intercept it.",
  ).toBeTruthy();
  const response = await page.request.get(
    `/api/workspace/materials?work_id=${encodeURIComponent(item.work_id)}&version_id=${encodeURIComponent(item.version_id)}`,
  );
  expect(response.ok()).toBe(true);
  const materials = (await response.json()) as {
    material_id: string;
    page_count: number | null;
    scope: string;
  }[];
  const selected = materials.find(
    (material) =>
      material.page_count === null &&
      ["abstract", "excerpt"].includes(material.scope),
  );
  expect(
    selected,
    "The actual API must retain source text before synthetic execution.",
  ).toBeTruthy();
  let advances = 0;
  page.on("request", (request) => {
    if (
      /\/api\/workspace\/generation\/jobs\/[^/]+\/advance$/.test(request.url())
    )
      advances++;
  });
  await page.goto(
    `/workspace/items/${encodeURIComponent(item.work_id)}?version=${encodeURIComponent(item.version_id)}#understand`,
  );
  await page
    .getByRole("button", {
      name: "Choose retained source context",
      exact: true,
    })
    .click();
  await page
    .getByRole("combobox", { name: "Source context", exact: true })
    .selectOption(selected!.material_id);
  await expect(
    page.getByRole("textbox", {
      name: "Optional request question",
      exact: true,
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Preview exact synthetic request",
      exact: true,
    })
    .click();
  const raw = await page
    .getByRole("region", { name: "Exact synthetic request JSON", exact: true })
    .textContent();
  const request = JSON.parse(raw!) as {
    private_context: {
      notes: boolean;
      profile: boolean;
      reading_history: boolean;
    };
    question: string;
  };
  expect(request.private_context).toEqual({
    notes: false,
    profile: false,
    reading_history: false,
  });
  expect(request.question).toBe("");
  await page
    .getByRole("button", { name: "Run synthetic workflow · $0", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: /^Synthetic checkpoint · ready( partial)?$/,
    }),
  ).toBeVisible();
  expect(advances).toBeLessThanOrEqual(4);
  await expect(
    page.getByText(
      /This result has not qualified a real model or calibrated judge/,
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Run synthetic workflow · $0",
      exact: true,
    }),
  ).toBeDisabled();
  const job = await page.request.get("/api/workspace/generation/jobs");
  expect(job.ok()).toBe(true);
  const checkpoints = (await job.json()) as {
    usage: { actual_usd: string };
    mode: string;
  }[];
  expect(checkpoints.length).toBeGreaterThan(0);
  expect(
    checkpoints.every(
      (checkpoint) =>
        checkpoint.mode === "fake" &&
        checkpoint.usage.actual_usd === "0.000000",
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("synthetic-workflow.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: /^Inspect retained evidence/ })
    .first()
    .click();
  await expect(page.locator("#source mark")).toBeVisible();
  await expect(page.locator("#source mark")).toBeInViewport();
  const a11y = await new AxeBuilder({ page }).analyze();
  expect(
    a11y.violations.filter((violation) =>
      ["critical", "serious"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
});
