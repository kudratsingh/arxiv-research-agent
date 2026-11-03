import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type {
  MaterialDocument,
  MaterialInfo,
  WorkspaceState,
} from "../lib/workspace/api";

test("actual public PDF excerpts retain original pages and an exact source anchor through save and reload", async ({
  page,
}, testInfo) => {
  const principal = process.env.WORKSPACE_VERIFICATION_PRINCIPAL;
  expect(
    principal,
    "Name an isolated verification principal explicitly.",
  ).toBeTruthy();
  expect(principal).not.toBe("personal-local");
  const stateResponse = await page.request.get("/api/workspace/state");
  expect(stateResponse.ok()).toBe(true);
  const state = (await stateResponse.json()) as WorkspaceState;
  expect(state.principal_key_id).toBe(principal);
  const item = state.works.find(
    (candidate) => candidate.source_id === "scientific-sample",
  );
  expect(
    item,
    "Explicitly register the bounded public PDF qualification samples first; no response is fabricated.",
  ).toBeTruthy();
  const list = await page.request.get(
    `/api/workspace/materials?work_id=${encodeURIComponent(item!.work_id)}&version_id=${encodeURIComponent(item!.version_id)}`,
  );
  expect(list.ok()).toBe(true);
  const material = ((await list.json()) as MaterialInfo[]).find(
    (candidate) => candidate.page_count !== null,
  );
  expect(material).toBeTruthy();
  const loaded = await page.request.get(
    `/api/workspace/materials/${material!.material_id}`,
  );
  expect(loaded.ok()).toBe(true);
  const document = (await loaded.json()) as MaterialDocument;
  const span = document.spans.find((candidate) => candidate.page !== null)!;
  expect(span).toBeTruthy();
  expect(document.complete).toBe(false);
  expect(document.scope).toBe("excerpt");
  await page.goto(
    `/workspace/items/${encodeURIComponent(item!.work_id)}?version=${encodeURIComponent(item!.version_id)}`,
  );
  await page
    .getByRole("button", { name: "Find retained PDF excerpts", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Retained document", exact: true })
    .selectOption(document.material_id);
  await expect(
    page.getByRole("heading", {
      name: "Retained document excerpts",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "This is an excerpt of the paper. Omitted pages have not been read or reconstructed.",
      { exact: true },
    ),
  ).toBeVisible();
  const paragraph = page.locator(
    `#retained-span-${span.span_id} .workspace-retained-text`,
  );
  const selected = await paragraph.evaluate((element) => {
    const node =
      element.querySelector("mark")?.firstChild ?? element.firstChild!;
    const quote = Array.from(node.textContent ?? "")
      .slice(0, 80)
      .join("");
    const range = window.document.createRange();
    range.setStart(node, 0);
    range.setEnd(node, quote.length);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    return quote;
  });
  const anchor = `material:${document.material_id}:page:${span.page}:${span.start}:${span.start + Array.from(selected).length}`;
  await page.getByRole("link", { name: "Your notes", exact: true }).click();
  await expect(
    page.getByText(`Anchor: ${anchor}`, { exact: true }),
  ).toBeVisible();
  const body = `Public PDF verification ${testInfo.project.name} ${Date.now()}: what does this retained passage establish?`;
  await page
    .getByRole("textbox", { name: "Your question", exact: true })
    .fill(body);
  await page
    .getByRole("button", { name: "Save question", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "is saved on the server",
  );
  const savedResponse = await page.request.get("/api/workspace/state");
  const saved = (await savedResponse.json()) as WorkspaceState;
  const entry = saved.works
    .find((candidate) => candidate.work_id === item!.work_id)!
    .entries.find((candidate) => candidate.body === body)!;
  expect(entry.anchor).toBe(anchor);
  expect(entry.version_id).toBe(item!.version_id);
  await page.goto(
    `/workspace/items/${encodeURIComponent(item!.work_id)}?version=${encodeURIComponent(item!.version_id)}&entry=${entry.id}#notes`,
  );
  await expect(page.locator(`#workspace-entry-${entry.id}`)).toBeFocused();
  await page.getByRole("link", { name: "Source", exact: true }).click();
  await expect(page.locator(`#retained-span-${span.span_id} mark`)).toHaveText(
    selected,
  );
  await page
    .getByText("Source version, hash and extraction receipt", { exact: true })
    .click();
  await expect(
    page.getByRole("region", {
      name: "Retained source provenance",
      exact: true,
    }),
  ).toContainText(document.source_hash);
  await expect(
    page.getByRole("link", { name: "Open original PDF ↗", exact: true }),
  ).toHaveAttribute("href", /^https:\/\/arxiv\.org\/pdf\//);
  await page.screenshot({
    path: testInfo.outputPath("retained-public-pdf.png"),
    fullPage: true,
  });
  await page.reload();
  await expect(page.locator(`#retained-span-${span.span_id} mark`)).toHaveText(
    selected,
  );
  const a11y = await new AxeBuilder({ page }).analyze();
  expect(
    a11y.violations.filter((violation) =>
      ["critical", "serious"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
});
