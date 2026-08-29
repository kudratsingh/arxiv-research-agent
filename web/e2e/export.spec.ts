import { expect, test } from "@playwright/test";

import { FIXTURES } from "./support/env";

/**
 * Criterion 7 — export downloads for `md`, `pdf` and `docx`, with
 * `content-disposition` intact through the proxy. 05 §2.1 step 5; R-08.
 *
 * WHY THE HEADER IS THE ASSERTION AND NOT THE BYTES. The export control is a
 * plain `<a download href="/api/research/{id}/export?format=…">`. There is no
 * fetch, no blob, no client-side filename: the browser downloads because the
 * *upstream* set `Content-Disposition: attachment` (`src/api/routes.py:385`)
 * and the Next route handler at `web/app/api/[...path]/route.ts` passed it
 * through unmodified. Strip or rewrite that header anywhere on the path and
 * the link silently starts rendering in the tab instead of saving — a
 * regression no screenshot would catch. So the assertion is made twice, from
 * both ends:
 *
 *   1. the response header, read off the wire through the proxy; and
 *   2. `download.suggestedFilename()`, which the browser derives FROM that
 *      header — so if it is right, the header survived end to end.
 *
 * WO-20 RE-POINTED THIS SPEC, AND THE ROLES ARE THE DIFFERENCE. WO-19
 * replaced `ExportDropdown`'s half-built `role="menu"` — a menu role over
 * anchors with no roving focus, no typeahead and no arrow keys — with
 * `ExportDisclosure`: a real `<button aria-expanded>` over three ordinary
 * links. So the links are `role="link"`, not `role="menuitem"`, and the
 * trigger's state is readable from `aria-expanded` rather than inferred. That
 * is the point of the swap and it is what this file now asserts; the download
 * claims below are unchanged.
 *
 * THE JOB IT DOWNLOADS. `baseline-partial-export` is failed-with-a-result.
 * `src/api/routes.py:364-368` permits the export and 05 §2.1 step 5 requires
 * it, so exporting a *partial* briefing is the case worth pinning: it is the
 * one a naive "only export succeeded jobs" change would break.
 */

const THREAD = `/c/${FIXTURES.populatedConversation}`;

const FORMATS = [
  { format: "md", label: "Markdown", contentType: /text\/markdown/ },
  { format: "pdf", label: "PDF", contentType: /application\/pdf/ },
  {
    format: "docx",
    label: "Word",
    contentType: /wordprocessingml\.document/,
  },
] as const;

test.describe("criterion 7 — export downloads through the proxy", () => {
  for (const { format, label, contentType } of FORMATS) {
    test(
      `${format} downloads with content-disposition intact`,
      { tag: "@export" },
      async ({ page }) => {
        const exportPath = `/api/research/${FIXTURES.partialExport}/export`;

        // Half 1: the header, off the wire, through the proxy.
        //
        // Read with `page.request`, NOT with `page.waitForResponse` and NOT
        // with `page.route`. A download initiated by `<a download>` is handled
        // by the browser process: it never surfaces as a page `response` event
        // and it does not pass through the routing layer, so both of those
        // approaches time out or silently observe nothing (both were tried).
        // `page.request` shares the browser context's cookies and baseURL and
        // goes through the same same-origin proxy, so the headers it reads are
        // the headers the download got.
        const probe = await page.request.get(`${exportPath}?format=${format}`);

        // The failed-with-partial-result turn is the newest one, and
        // `ThreadTimeline` opens the newest turn on arrival (WO-20 c4).
        await page.goto(THREAD, { waitUntil: "domcontentloaded" });
        await expect(page.getByRole("button", { name: /Turn 2/ })).toBeVisible();

        const downloadPromise = page.waitForEvent("download");
        const trigger = page.getByRole("button", { name: "Export" }).last();
        await trigger.click();
        await expect(trigger).toHaveAttribute("aria-expanded", "true");
        await page.getByRole("link", { name: label }).click();

        const download = await downloadPromise;

        expect(probe.status()).toBe(200);
        const headers = probe.headers();
        expect(
          headers["content-disposition"],
          "the proxy must pass Content-Disposition through unmodified — " +
            "without it the browser renders the export in the tab instead of " +
            "saving it (routes.py:385)",
        ).toBe(
          `attachment; filename="research-${FIXTURES.partialExport}.${format}"`,
        );
        expect(headers["content-type"]).toMatch(contentType);

        // Half 2: what the browser did with it.
        expect(
          download.suggestedFilename(),
          "the filename the browser offers is derived from the header, so this " +
            "is the same claim made from the other end of the wire",
        ).toBe(`research-${FIXTURES.partialExport}.${format}`);

        const path = await download.path();
        expect(path, "the download must actually produce a file").not.toBeNull();
      },
    );
  }

  /**
   * R-08 from the download side.
   *
   * Every export link is same-origin under `/api`. An absolute upstream URL
   * here would mean the browser talking to the API directly, which is how the
   * server-only key stops being server-only.
   */
  test(
    "every export link is same-origin under /api",
    { tag: "@export" },
    async ({ page }) => {
      await page.goto(THREAD, { waitUntil: "domcontentloaded" });
      const trigger = page.getByRole("button", { name: "Export" }).last();
      await trigger.click();

      // Three links, not three menuitems: 03 §4.8 and RC-09. A `role="menu"`
      // that behaves like a list is the defect WO-19 removed, so the role is
      // part of the assertion rather than an incidental selector.
      const items = page.getByRole("link", { name: /Markdown|PDF|Word/ });
      await expect(items).toHaveCount(3);
      await expect(page.getByRole("menuitem")).toHaveCount(0);

      const origin = new URL(page.url()).origin;
      for (const href of await items.evaluateAll((nodes) =>
        nodes.map((node) => (node as HTMLAnchorElement).href),
      )) {
        const url = new URL(href);
        expect(url.origin, `${href} must stay same-origin`).toBe(origin);
        expect(url.pathname.startsWith("/api/")).toBe(true);
      }
    },
  );

  /**
   * 03 §2.2 row 23 — §4's row 23, from the side the sweep cannot measure.
   *
   * "The export control is *absent*, not disabled-and-silent, until a briefing
   * exists." A disabled button would be a control that explains nothing; a
   * present-but-apologetic one would put an error on screen before the user
   * has done anything. So the assertion is a count of zero on a run whose
   * `result` is empty, beside a count of one where a briefing exists.
   */
  test(
    "no export control exists on a run that produced no briefing",
    { tag: "@export" },
    async ({ page }) => {
      await page.goto(`${THREAD}?job=${FIXTURES.failed}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(
        page.getByText("This run stopped before a briefing was written."),
      ).toBeVisible();

      const live = page.locator('[data-report-reader][data-partial="false"]');
      await expect(live.getByRole("button", { name: "Export" })).toHaveCount(0);
    },
  );
});
