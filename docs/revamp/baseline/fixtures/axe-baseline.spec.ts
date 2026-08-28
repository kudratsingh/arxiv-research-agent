import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const baseUrl = process.env.BASELINE_BASE_URL ?? "http://127.0.0.1:13000";
const axeSource =
  process.env.AXE_SOURCE ?? "/tmp/arxiv-gate1-playwright/node_modules/axe-core/axe.min.js";
const output = join(process.cwd(), "docs", "revamp", "baseline", "axe");

test.use({ channel: "chrome", colorScheme: "light" });
test.setTimeout(120_000);

async function audit(
  page: Page,
  state: string,
  route: string,
  readyText?: string | RegExp
) {
  await page.goto(`${baseUrl}${route}`, { waitUntil: "domcontentloaded" });
  if (readyText) {
    await expect(page.getByText(readyText).first()).toBeVisible();
  }
  await page.addScriptTag({ path: axeSource });
  const results = await page.evaluate(async () => {
    const axe = (
      window as unknown as {
        axe: {
          run: (
            context: Document,
            options: { runOnly: { type: "tag"; values: string[] } }
          ) => Promise<unknown>;
        };
      }
    ).axe;
    return axe.run(document, {
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"],
      },
    });
  });
  await writeFile(join(output, `${state}.json`), `${JSON.stringify(results, null, 2)}\n`);
}

test("export standalone axe reports for the Gate 1 matrix", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await audit(page, "home", "/", "arxiv-research-agent");
  await audit(page, "conversation-empty", "/c/baseline-empty", "Empty research thread");
  await audit(page, "conversation-populated", "/c/baseline-populated", "Scientific claim verification");
  await audit(page, "plan-review", "/c/baseline-populated?job=baseline-plan-review", "Plan review");
  await audit(page, "running", "/c/baseline-populated?job=baseline-running", "Current turn");
  await audit(page, "failed-partial", "/c/baseline-populated?job=baseline-failed-partial", "Job failed");
  await audit(page, "cancelled", "/c/baseline-populated?job=baseline-cancelled", "cancelled");
  await audit(page, "expired-job", "/c/baseline-populated?job=baseline-expired", /stream unavailable for job/);
  await audit(page, "conversation-not-found", "/c/baseline-not-found", "Conversation not found.");
  await audit(page, "framework-not-found", "/baseline-not-found", "This page could not be found.");

  await page.route("**/api/conversations", async (route) => {
    await route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "synthetic local upstream failure" }),
    });
  });
  await audit(page, "backend-offline", "/", "synthetic local upstream failure");
  await page.unroute("**/api/conversations");

  await page.emulateMedia({ colorScheme: "dark" });
  await audit(page, "conversation-populated-dark", "/c/baseline-populated", "Scientific claim verification");
});
