import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

const baseUrl = process.env.BASELINE_BASE_URL ?? "http://127.0.0.1:13000";
const screenshots = join(process.cwd(), "docs", "revamp", "baseline", "screenshots");

test.use({ channel: "chrome", colorScheme: "light" });
test.setTimeout(120_000);

async function shot(
  page: Page,
  route: string,
  file: string,
  viewport: { width: number; height: number },
  readyText?: string | RegExp
) {
  await page.setViewportSize(viewport);
  await page.goto(`${baseUrl}${route}`, { waitUntil: "domcontentloaded" });
  if (readyText) {
    await expect(page.getByText(readyText).first()).toBeVisible();
  }
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(screenshots, file) });
}

test("capture the Gate 1 route and state matrix", async ({ page }) => {
  await shot(page, "/", "home-desktop-full.png", { width: 1440, height: 1200 }, "arxiv-research-agent");
  await shot(page, "/", "home-mobile-full.png", { width: 412, height: 915 }, "arxiv-research-agent");

  let heldList: Route | undefined;
  await page.route("**/api/conversations", async (route) => {
    heldList = route;
  });
  await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Loading…")).toBeVisible();
  await page.screenshot({ path: join(screenshots, "sidebar-loading-desktop.png") });
  await heldList?.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  await page.unroute("**/api/conversations");

  await shot(page, "/c/baseline-empty", "conversation-empty-desktop.png", { width: 1440, height: 1200 }, "Empty research thread");
  await shot(page, "/c/baseline-empty", "conversation-empty-mobile-full.png", { width: 412, height: 915 }, "Empty research thread");

  let heldConversation: Route | undefined;
  await page.route("**/api/conversations/baseline-populated", async (route) => {
    heldConversation = route;
  });
  await page.goto(`${baseUrl}/c/baseline-populated`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Loading conversation…")).toBeVisible();
  await page.screenshot({ path: join(screenshots, "conversation-loading-desktop.png") });
  await heldConversation?.continue();
  await page.unroute("**/api/conversations/baseline-populated");

  await shot(page, "/c/baseline-populated", "conversation-populated-desktop-full.png", { width: 1440, height: 1400 }, "Scientific claim verification");
  await shot(page, "/c/baseline-populated", "conversation-populated-mobile-full.png", { width: 412, height: 1200 }, "Scientific claim verification");
  await shot(page, "/c/baseline-populated?job=baseline-plan-review", "plan-review-desktop.png", { width: 1440, height: 2200 }, "Plan review");
  await shot(page, "/c/baseline-populated?job=baseline-plan-review", "plan-review-mobile-full.png", { width: 412, height: 1800 }, "Plan review");
  await shot(page, "/c/baseline-populated?job=baseline-running", "running-desktop.png", { width: 1440, height: 1800 }, "Current turn");

  // A valid 200 event stream that closes without a terminal frame leaves
  // EventSource in the browser-managed retry state. This deterministic route
  // is distinct from an expired-job 404 and never touches the model API.
  await page.route("**/api/research/baseline-running/stream", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: { "cache-control": "no-cache" },
      body: ": synthetic connection interruption\n\n",
    });
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText(/connection interrupted; browser is retrying/)).toBeVisible({
    timeout: 10_000,
  });
  await page.screenshot({ path: join(screenshots, "reconnecting-desktop.png") });
  await page.unroute("**/api/research/baseline-running/stream");

  await shot(page, "/c/baseline-populated?job=baseline-failed-partial", "failed-partial-desktop.png", { width: 1440, height: 1800 }, "Job failed");
  await shot(page, "/c/baseline-populated?job=baseline-failed-partial", "failed-partial-mobile.png", { width: 412, height: 1200 }, "Job failed");
  await shot(page, "/c/baseline-populated?job=baseline-cancelled", "cancelled-desktop.png", { width: 1440, height: 1800 }, "cancelled");
  await shot(page, "/c/baseline-populated?job=baseline-expired", "expired-job-desktop.png", { width: 1440, height: 1600 }, /stream unavailable for job/);
  await shot(page, "/c/baseline-not-found", "conversation-not-found-desktop.png", { width: 1440, height: 1200 }, "Conversation not found.");
  await shot(page, "/baseline-not-found", "framework-not-found-desktop.png", { width: 1440, height: 1200 }, "This page could not be found.");

  await page.route("**/api/conversations", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "synthetic local submission failure" }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
  await page.getByRole("textbox", { name: "Research question" }).fill("A local test-only question");
  await page.getByRole("button", { name: "Run research" }).click();
  await expect(page.getByText(/synthetic local submission failure/)).toBeVisible();
  await page.screenshot({ path: join(screenshots, "submission-error-desktop.png") });
  await page.unroute("**/api/conversations");

  await page.route("**/api/conversations", async (route) => {
    await route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "synthetic local upstream failure" }),
    });
  });
  await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/synthetic local upstream failure/)).toBeVisible();
  await page.screenshot({ path: join(screenshots, "backend-offline-desktop.png") });
  await page.unroute("**/api/conversations");

  await page.emulateMedia({ colorScheme: "dark" });
  await shot(page, "/c/baseline-populated", "conversation-populated-dark-desktop.png", { width: 1440, height: 1400 }, "Scientific claim verification");
});
