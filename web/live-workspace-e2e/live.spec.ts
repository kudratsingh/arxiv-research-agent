import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { WorkspaceState } from "../lib/workspace/api";

/** Real loopback API + Postgres only. Failure injection aborts one save; no fixture responses fill the live UI. */
test.describe.configure({ mode: "serial" });

async function realState(page: import("@playwright/test").Page) {
  const response = await page.request.get("/api/workspace/state");
  expect(response.ok()).toBe(true);
  const state = (await response.json()) as WorkspaceState;
  expect(state.principal_key_id).toBeTruthy();
  expect(state.generation).toBe("approval_required");
  expect(state.sources.length).toBe(5);
  return state;
}

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
  await page.route("**/api/workspace/entries", (route) =>
    route.abort("failed"),
  );
  await page
    .getByRole("button", { name: "Save question", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("unavailable");
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
  await page.unroute("**/api/workspace/entries");
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
