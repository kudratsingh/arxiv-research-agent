import { expect, test } from "@playwright/test";
import type { WorkspaceState } from "../lib/workspace/api";

/** Compact return proof; write only after asserting the isolated principal. */
test("Today puts the saved thread and first reading item within reach", async ({ page }, info) => {
  const response = await page.request.get("/api/workspace/state");
  const state = await response.json() as WorkspaceState;
  expect(state.principal_key_id).toBe(process.env.WORKSPACE_VERIFICATION_PRINCIPAL ?? "e2e");
  expect(state.principal_key_id).not.toBe("personal-local");
  const item = state.works[0]!, id = crypto.randomUUID();
  const saved = await page.request.post("/api/workspace/entries", { data: { id, revision: 0, request_id: id, data: {work_id: item.work_id, version_id: item.version_id, kind: "question", body: "Verification question: which evidence and baseline should stay fixed in a small reproducible retrieval experiment?", anchor: "abstract:0"} } });
  expect(saved.ok()).toBe(true);
  await page.goto("/workspace/today");
  const thread = page.getByRole("heading", { name: "Continue your question" });
  await expect(thread).toBeVisible();
  const first = page.locator(".daily-item h3").first();
  const threadBox = await thread.boundingBox(), firstBox = await first.boundingBox();
  expect(threadBox!.y).toBeLessThan(firstBox!.y);
  if (info.project.name === "mobile") expect(firstBox!.y).toBeLessThan(844);
  await info.attach("layout.json", {body: JSON.stringify({viewport: page.viewportSize(), continuation: threadBox, first_item: firstBox}), contentType:"application/json"});
  await expect(page.getByText("Edition details", { exact: false })).toBeVisible();
  await page.screenshot({ path: info.outputPath("today-compact.png"), fullPage: true });
  await page.screenshot({ path: info.outputPath("today-viewport.png") });
});

