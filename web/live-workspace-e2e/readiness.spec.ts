import { expect, test } from "@playwright/test";
import type { WorkspaceState } from "../lib/workspace/api";

/** Compact return proof; write only after asserting the isolated principal. */
test("Today puts the saved thread and first reading item within reach", async ({ page }, info) => {
  const response = await page.request.get("/api/workspace/state");
  const state = await response.json() as WorkspaceState;
  expect(state.principal_key_id).toBe(process.env.WORKSPACE_VERIFICATION_PRINCIPAL ?? "e2e");
  expect(state.principal_key_id).not.toBe("personal-local");
  const item = state.works.find(work => work.abstract)!, id = crypto.randomUUID();
  expect(item).toBeTruthy();
  const anchor = `${item.access_state}:0:${Math.min(60, Array.from(item.abstract).length)}`;
  const saved = await page.request.post("/api/workspace/entries", { data: { id, revision: 0, request_id: id, data: {work_id: item.work_id, version_id: item.version_id, kind: "question", body: "Verification question: which evidence and baseline should stay fixed in a small reproducible retrieval experiment?", anchor} } });
  expect(saved.ok()).toBe(true);
  await page.goto("/workspace/today");
  // The compact controller keeps one exact-source continuation link; its
  // redundant heading is folded on mobile to leave room for actual reading.
  const thread = page.locator(".workspace-continuation .workspace-activity-link");
  await expect(thread).toBeVisible();
  const resume = new URL((await thread.getAttribute("href"))!, page.url());
  expect(resume.searchParams.get("entry")).toBe(id);
  expect(resume.searchParams.get("version")).toBe(item.version_id);
  expect(decodeURIComponent(resume.hash)).toBe(`#${anchor}`);
  const first = page.locator(".daily-item h3").first();
  const threadBox = await thread.boundingBox(), firstBox = await first.boundingBox();
  expect(threadBox!.y).toBeLessThan(firstBox!.y);
  if (info.project.name === "mobile") {
    expect(firstBox!.y).toBeLessThan(800);
    const clearance = await page.locator("article.ws-focus").evaluate(article => {
      const title = article.querySelector("h3")!.getBoundingClientRect();
      const range = document.createRange(); range.selectNodeContents(article.querySelector(".ws-focus-abstract")!);
      const lines: { top: number; bottom: number }[] = [];
      for (const rect of range.getClientRects()) if (rect.height && !lines.some(line => Math.abs(line.top - rect.top) < 1)) lines.push({ top: rect.top, bottom: rect.bottom });
      return { title: { top: title.top, bottom: title.bottom }, lines: lines.slice(0, 2), playerTop: document.querySelector(".ws-bar")!.getBoundingClientRect().top };
    });
    expect(clearance.title.top).toBeGreaterThanOrEqual(0);
    expect(clearance.title.bottom).toBeLessThan(clearance.playerTop);
    expect(clearance.lines).toHaveLength(2);
    for (const line of clearance.lines) { expect(line.top).toBeGreaterThanOrEqual(0); expect(line.bottom).toBeLessThan(clearance.playerTop); }
  }
  await info.attach("layout.json", {body: JSON.stringify({viewport: page.viewportSize(), continuation: threadBox, first_item: firstBox}), contentType:"application/json"});
  await expect(page.getByText("Edition details", { exact: false })).toBeVisible();
  await page.screenshot({ path: info.outputPath("today-compact.png"), fullPage: true });
  await page.screenshot({ path: info.outputPath("today-viewport.png") });
});

