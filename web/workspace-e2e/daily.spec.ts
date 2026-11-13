/** Offline W1 loop: real navigation and persistence, fictional source data. */
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("interests to source to saved question to return visit", async ({
  page,
}, testInfo) => {
  const api: string[] = [];
  await page.route("**/api/**", (route) => {
    api.push(route.request().url());
    return route.abort();
  });
  await page.goto("/interests");
  await page.getByRole("button", { name: "Use suggested ML lens" }).click();
  await page.getByRole("link", { name: "See your sample briefing" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "What changed.",
  );
  await expect(page.getByText("your selected lens")).toBeVisible();
  await page.getByText("Sample coverage: 5 of 6 checks available").click();
  await expect(
    page.getByText("Sample timeout · interval not checked"),
  ).toBeVisible();
  await expect(page.locator("body")).not.toHaveJSProperty("scrollWidth", 0);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: `build/workspace/today-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole("link", { name: "Read & investigate" }).click();
  await expect(
    page.getByRole("heading", { name: "Source abstract", exact: true }),
  ).toBeVisible();
  const sourceAxe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(sourceAxe.violations).toEqual([]);
  await page.screenshot({
    path: `build/workspace/reader-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole("link", { name: "Your notes", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Your question", exact: true })
    .fill("Does my evaluation keep the document set fixed?");
  await page
    .getByRole("button", { name: "Save question", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("Saved in this browser");
  await page
    .getByRole("link", { name: "Return to Today with this thread" })
    .click();
  await expect(page).toHaveURL(/\/today$/);
  await expect(
    page.getByText("Does my evaluation keep the document set fixed?", {
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Does my evaluation keep the document set fixed?", {
      exact: true,
    }),
  ).toBeVisible();
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(axe.violations).toEqual([]);
  await page.getByRole("link", { name: "Your saved work" }).click();
  await expect(
    page.getByRole("button", { name: "Export notes as Markdown" }),
  ).toBeEnabled();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export notes as Markdown" }).click();
  expect((await download).suggestedFilename()).toBe(
    "research-preview-notes.md",
  );
  await page.getByRole("link", { name: "Resume reading" }).click();
  await expect(page).toHaveURL(/#notes$/);
  await expect(
    page.getByRole("heading", { name: "Keep a question open." }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Keep the useful parts." }),
  ).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/#notes$/);
  expect(api).toEqual([]);
});

test("broad interests remain editable and empty state is honest", async ({
  page,
}) => {
  await page.goto("/interests");
  await page.getByLabel("Search topics").fill("retrieval augmented generation");
  await expect(
    page.getByRole("checkbox", { name: /Retrieval augmented generation/ }),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: /Retrieval augmented generation/ })
    .check();
  await page
    .getByRole("textbox", { name: "Your own topic or question" })
    .fill("Reliable agent memory");
  await page.getByRole("button", { name: "Add custom interest" }).click();
  await expect(
    page.getByRole("button", { name: "Remove Reliable agent memory" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Remove Reliable agent memory" }),
  ).toBeVisible();
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(result.violations).toEqual([]);
});

test("dark theme and metadata-only reading retain the same evidence boundary", async ({page}, testInfo) => {
  await page.goto("/today");
  await page.getByRole("radio", {name: "Dark", exact: true}).focus();
  await page.keyboard.press("Space");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const result = await new AxeBuilder({page}).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(result.violations).toEqual([]);
  await page.screenshot({path: `build/workspace/today-dark-${testInfo.project.name}.png`, fullPage: true});
  await page.goto("/library/items/inference-release#understand");
  await expect(page.getByRole("button", {name: "Generation not enabled"})).toBeDisabled();
  await expect(page.getByText("Metadata only", {exact: true})).toBeVisible();
});

test("the daily reading loop is usable with the keyboard alone", async ({page}) => {
  await page.goto("/today");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", {name: "Skip to main content"})).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  async function tabTo(target: ReturnType<typeof page.getByRole>) {
    for (let i = 0; i < 60; i++) {
      if (await target.evaluate(element => element === document.activeElement)) return;
      await page.keyboard.press("Tab");
    }
    await expect(target).toBeFocused();
  }
  await tabTo(page.getByRole("link", {name: "Read & investigate"}));
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/library\/items\/corpus-shift$/);
  await tabTo(page.getByRole("link", {name: "Your notes", exact: true}));
  await page.keyboard.press("Enter");
  await tabTo(page.getByRole("textbox", {name: "Your question", exact: true}));
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.type("Which evidence would change this conclusion?");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", {name: "Save question", exact: true})).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("Saved in this browser");
  await tabTo(page.getByRole("link", {name: "Return to Today with this thread"}));
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/today$/);
  await expect(page.getByText("Which evidence would change this conclusion?", {exact: true})).toBeVisible();
});
