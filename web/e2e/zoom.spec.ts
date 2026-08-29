import { expect, test } from "@playwright/test";

import { waitForRailMode, writeArtifact } from "./support/a11y";
import { FIXTURES } from "./support/env";
import { measureReflow } from "./support/measure";
import { REPORT_READER } from "./support/states";

/**
 * WO-27 criterion 4 — reflow and zoom.
 *
 * "`reflow/` covers 320 CSS px, phone landscape, 200% and 400% zoom, and a
 * very long unbroken report."
 *
 * HOW ZOOM IS PRODUCED, AND WHY IT IS NOT A CHEAT. SC 1.4.10 is written in
 * **CSS pixels**: "content can be presented without loss of information or
 * functionality, and without requiring scrolling in two dimensions, for
 * vertical scrolling content at a width equivalent to 320 CSS pixels". The
 * note is explicit that 320 CSS px is "equivalent to a starting viewport
 * width of 1280px wide at 400% zoom". Browser zoom multiplies the CSS pixel,
 * so a 1280px window at 400% and a 320px window at 100% present the same CSS
 * pixel width to the layout, and the second is the one a headless browser can
 * be put in deterministically.
 *
 * So the rows below name the zoom level they are *equivalent to* and set the
 * viewport that produces it, and the evidence file says the same thing rather
 * than implying somebody dragged a zoom control. What this does NOT reproduce
 * is the second half of real zoom — the scaled-up rasterisation of text and
 * the sub-pixel rounding that comes with a `deviceScaleFactor` other than 1 —
 * so `reflow/README.md` records that limit instead of hiding it.
 *
 * WHAT THIS FILE ADDS TO `reflow.spec.ts`. That sweep is WO-08's structural
 * guard: `scrollWidth <= clientWidth` at 320/360/412 on every §4 state. It
 * does not cover landscape (where the constraint is HEIGHT, and a sticky
 * composer plus a sticky header can leave a work surface with no room), the
 * two zoom equivalences above 320, or a report whose content is a single
 * unbroken token — which is the one input a `max-width` reading column cannot
 * defend itself against.
 */

const POPULATED = `/c/${FIXTURES.populatedConversation}`;

/**
 * The four presentations criterion 4 names, as viewports.
 *
 * `phone landscape` is a Pixel-7-class device rotated: 915 × 412. It is in
 * this list rather than in `device.spec.ts` because the failure it looks for
 * is a *vertical* one and nothing else in the suite is short.
 */
const PRESENTATIONS = [
  {
    id: "320-css-px",
    label: "320 CSS px — SC 1.4.10's reflow width (≡ 1280px at 400% zoom)",
    viewport: { width: 320, height: 900 },
  },
  {
    id: "phone-landscape",
    label: "Phone landscape — 915 × 412, a Pixel 7 rotated",
    viewport: { width: 915, height: 412 },
  },
  {
    id: "zoom-200",
    label: "200% zoom — 1280px window, 640 CSS px of layout",
    viewport: { width: 640, height: 512 },
  },
  {
    id: "zoom-400",
    label: "400% zoom — 1280px window, 320 CSS px of layout",
    viewport: { width: 320, height: 256 },
  },
] as const;

/**
 * The four routes with the most to lose at a narrow width, and why each.
 *
 * Not the whole §4 table: `reflow.spec.ts` already sweeps that at three
 * widths, and repeating twenty-two states across four more presentations
 * would be eighty-eight navigations to re-prove one assertion. These four are
 * the ones where the *content* rather than the shell is the risk — a plan
 * editor full of textareas, a briefing with a table, a run panel with a
 * scrollable diagnostics table, and the composer.
 */
const SURFACES = [
  { id: "landing", path: "/", ready: "text=What should the literature settle?" },
  { id: "report", path: POPULATED, ready: REPORT_READER },
  {
    id: "plan-review",
    path: `${POPULATED}?job=${FIXTURES.planReview}`,
    ready: 'button[aria-label="Remove sub-question 1"]',
  },
  {
    id: "running",
    path: `${POPULATED}?job=${FIXTURES.running}`,
    ready: '[data-surface="active-run"]',
  },
] as const;

test.describe("criterion 4 — reflow at the four presentations", () => {
  for (const presentation of PRESENTATIONS) {
    for (const surface of SURFACES) {
      test(
        `${surface.id} @ ${presentation.id} scrolls in one direction only`,
        { tag: "@a11y" },
        async ({ page }, info) => {
          await page.setViewportSize(presentation.viewport);
          await page.goto(surface.path, { waitUntil: "domcontentloaded" });
          await page.locator(surface.ready).first().waitFor();

          const sample = await measureReflow(page);
          writeArtifact(
            info.outputDir,
            `reflow/${presentation.id}.${surface.id}.tsv`,
            [
              `# ${presentation.label}`,
              `# ${surface.path}`,
              "measure\tvalue",
              `viewport\t${presentation.viewport.width}x${presentation.viewport.height}`,
              `scrollWidth\t${sample.scrollWidth}`,
              `clientWidth\t${sample.clientWidth}`,
              `widestOverflow\t${
                sample.widestOverflow === null
                  ? "(none)"
                  : `${sample.widestOverflow.selector} @ ${sample.widestOverflow.width}px`
              }`,
            ].join("\n"),
          );

          expect(
            sample.scrollWidth,
            `${surface.id} @ ${presentation.label}: scrollWidth ` +
              `${sample.scrollWidth} > clientWidth ${sample.clientWidth}` +
              (sample.widestOverflow === null
                ? ""
                : `; the widest overflowing element is ` +
                  `${sample.widestOverflow.selector} reaching ` +
                  `${sample.widestOverflow.width}px`),
          ).toBeLessThanOrEqual(sample.clientWidth);
        },
      );
    }
  }
});

test.describe("criterion 4 — landscape keeps the work surface usable", () => {
  test(
    "at 915 × 412 the composer and some of main are both on screen",
    { tag: "@a11y" },
    async ({ page }, info) => {
      // The failure this looks for is specific and is not caught by any
      // width assertion: `main` is a grid whose bottom row is a sticky
      // composer, so on a 412px-TALL viewport the header, the composer and
      // the composer's own hint text can between them leave the content row
      // with a handful of pixels. That is a loss of functionality at a
      // supported orientation (SC 1.3.4).
      await page.setViewportSize({ width: 915, height: 412 });
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await page.getByText("What should the literature settle?").first().waitFor();

      const geometry = await page.evaluate(() => {
        const main = document.querySelector("main");
        const composer = document.querySelector('[data-variant="landing"]');
        const header = document.querySelector("header");
        const submit = Array.from(document.querySelectorAll("button")).find(
          (button) => button.type === "submit",
        );
        const box = (node: Element | null | undefined) =>
          node === null || node === undefined ? null : node.getBoundingClientRect().height;
        const bottom = (node: Element | null | undefined) =>
          node === null || node === undefined
            ? null
            : Math.round(node.getBoundingClientRect().bottom);
        return {
          viewport: window.innerHeight,
          header: box(header),
          main: box(main),
          composer: box(composer),
          // Where the submit control's bottom edge sits relative to the fold.
          // Vertical scrolling is allowed at any orientation (SC 1.4.10 is
          // about the OTHER axis), so this is recorded as a measurement rather
          // than asserted as a pass or a fail — see reflow/README.md §4.
          submitBottom: bottom(submit),
          scrollable: (main?.scrollHeight ?? 0) > (main?.clientHeight ?? 0),
        };
      });

      writeArtifact(
        info.outputDir,
        "reflow/phone-landscape.geometry.tsv",
        [
          "# Phone landscape — 915 × 412",
          "measure\tCSS px",
          `viewport height\t${geometry.viewport}`,
          `header\t${geometry.header ?? "(absent)"}`,
          `main\t${geometry.main ?? "(absent)"}`,
          `composer\t${geometry.composer ?? "(absent)"}`,
          `submit button bottom edge\t${geometry.submitBottom ?? "(absent)"}`,
          `main scrolls vertically\t${geometry.scrollable}`,
        ].join("\n"),
      );

      expect(geometry.main, "no <main> at landscape").not.toBeNull();
      expect(
        geometry.main ?? 0,
        "at 412 CSS px of height, `main` must still have real room. A shell " +
          "whose header and composer consume the viewport leaves nothing to " +
          "read, which is a loss of functionality at a supported orientation.",
      ).toBeGreaterThan(120);
      // …and the composer is still reachable and on screen, not pushed off.
      await expect(page.getByRole("button", { name: "Generate plan" })).toBeInViewport();
    },
  );
});

test.describe("criterion 4 — a very long unbroken report", () => {
  test(
    "a 4,000-character single token does not pan the page at 320 CSS px",
    { tag: "@a11y" },
    async ({ page }, info) => {
      // The one input a `max-width` reading column cannot defend itself
      // against: a token with no break opportunity in it. Reports are model
      // output containing URLs, DOIs, base64 fragments and arXiv identifiers,
      // so this is a realistic worst case rather than an adversarial one.
      //
      // Injected by rewriting the CONVERSATION READ, not by touching the DOM:
      // the claim is about the Markdown pipeline and the reading column
      // together, and a `textContent` assignment would bypass both.
      const unbroken = "A".repeat(4_000);
      const url = "https://example.org/" + "b".repeat(600);
      await page.route(
        (target) => target.pathname === `/api/conversations/${FIXTURES.populatedConversation}`,
        async (route) => {
          const response = await route.fetch();
          const body = (await response.json()) as {
            jobs?: { report?: string | null }[];
          };
          // The LAST turn, because that is the one the thread expands on
          // load. Rewriting the first would put the token behind a collapsed
          // disclosure and measure a page that never rendered it.
          const target = body.jobs?.[(body.jobs?.length ?? 0) - 1];
          if (target !== undefined) {
            target.report =
              `# A briefing with nothing to break on\n\n${unbroken}\n\n` +
              `See ${url}\n\n` +
              "| Identifier | Note |\n|---|---|\n" +
              `| ${"C".repeat(400)} | one unbreakable cell |\n`;
          }
          await route.fulfill({
            response,
            body: JSON.stringify(body),
            headers: { ...response.headers(), "content-type": "application/json" },
          });
        },
      );

      await page.setViewportSize({ width: 320, height: 900 });
      await page.goto(POPULATED, { waitUntil: "domcontentloaded" });
      await page.locator(REPORT_READER).first().waitFor();
      await expect(page.getByText("A briefing with nothing to break on")).toBeVisible();

      const sample = await measureReflow(page);
      const wrapping = await page.evaluate(() => {
        const article = document.querySelector(".ew-report");
        if (article === null) return null;
        const style = window.getComputedStyle(article);
        return {
          overflowWrap: style.overflowWrap,
          wordBreak: style.wordBreak,
          maxWidth: style.maxWidth,
          widest: Math.max(
            ...Array.from(article.querySelectorAll("*")).map(
              (node) => node.getBoundingClientRect().right,
            ),
            0,
          ),
        };
      });

      writeArtifact(
        info.outputDir,
        "reflow/long-unbroken-report.tsv",
        [
          "# A 4,000-character unbroken token, a 600-character URL and a 400-character table cell",
          "# rendered through the real Markdown pipeline at 320 CSS px",
          "measure\tvalue",
          `scrollWidth\t${sample.scrollWidth}`,
          `clientWidth\t${sample.clientWidth}`,
          `widestOverflow\t${
            sample.widestOverflow === null
              ? "(none)"
              : `${sample.widestOverflow.selector} @ ${sample.widestOverflow.width}px`
          }`,
          `overflow-wrap\t${wrapping?.overflowWrap ?? "(no .ew-report)"}`,
          `word-break\t${wrapping?.wordBreak ?? "(no .ew-report)"}`,
          `max-width\t${wrapping?.maxWidth ?? "(no .ew-report)"}`,
          `widest descendant right edge\t${Math.round(wrapping?.widest ?? 0)}px`,
        ].join("\n"),
      );

      expect(
        sample.scrollWidth,
        "a briefing containing one unbreakable 4,000-character token pans the " +
          `page at 320 CSS px (scrollWidth ${sample.scrollWidth} > clientWidth ` +
          `${sample.clientWidth}). The reading column needs a break-opportunity ` +
          "rule, not a wider max-width.",
      ).toBeLessThanOrEqual(sample.clientWidth);

      // The table is the other half: it is allowed to scroll, but only
      // inside its own labelled region, never by taking the document with it.
      const region = page.getByRole("region", { name: /Table \d+ in this briefing/ }).first();
      await expect(region).toBeVisible();
      const scroller = await region.evaluate((node) => ({
        overflowX: window.getComputedStyle(node).overflowX,
        scrollable: node.scrollWidth > node.clientWidth,
      }));
      expect(
        scroller.overflowX,
        "a table wider than the reading column must scroll inside its own " +
          "region; the document must not.",
      ).toBe("auto");
    },
  );
});

test.describe("criterion 4 — the rail's absence is what makes 320 work", () => {
  test("at 320 the rail is out of the layout and the drawer is the way in", { tag: "@a11y" }, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await waitForRailMode(page, "drawer");
    await expect(page.locator("#workbench-rail")).toHaveCount(0);
    await expect(page.locator("[data-drawer-trigger]").first()).toBeVisible();
  });
});
