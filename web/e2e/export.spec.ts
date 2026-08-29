import { expect, test } from "@playwright/test";

import { FIXTURES } from "./support/env";

/**
 * Criterion 7 — export downloads for `md`, `pdf` and `docx`, with
 * `content-disposition` intact through the proxy. 05 §2.1 step 5; R-08.
 *
 * WHY THE HEADER IS THE ASSERTION AND NOT THE BYTES. `ExportDropdown.tsx:78`
 * is a plain `<a download href="/api/research/{id}/export?format=…">`. There
 * is no fetch, no blob, no client-side filename: the browser downloads
 * because the *upstream* set `Content-Disposition: attachment`
 * (`src/api/routes.py:385`) and the Next route handler at
 * `web/app/api/[...path]/route.ts` passed it through unmodified. Strip or
 * rewrite that header anywhere on the path and the link silently starts
 * rendering in the tab instead of saving — a regression no screenshot would
 * catch. So the assertion is made twice, from both ends:
 *
 *   1. the response header, read off the wire through the proxy; and
 *   2. `download.suggestedFilename()`, which the browser derives FROM that
 *      header — so if it is right, the header survived end to end.
 *
 * THE JOB IT DOWNLOADS. `baseline-partial-export` is failed-with-a-result.
 * `src/api/routes.py:364-368` permits the export and 05 §2.1 step 5 requires
 * it, so exporting a *partial* briefing is the case worth pinning: it is the
 * one a naive "only export succeeded jobs" change would break.
 */

const THREAD = `/c/${FIXTURES.populatedConversation}`;

const FORMATS = [
  { format: "md", label: "Markdown (.md)", contentType: /text\/markdown/ },
  { format: "pdf", label: "PDF (.pdf)", contentType: /application\/pdf/ },
  {
    format: "docx",
    label: "Word (.docx)",
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

        await page.goto(THREAD, { waitUntil: "domcontentloaded" });
        // The failed-with-partial-result turn is the last one, and
        // `ConversationThread.tsx:44-50` expands it on load.
        await expect(
          page.getByRole("button", { name: /Turn 2/ }),
        ).toBeVisible();

        const downloadPromise = page.waitForEvent("download");
        await page.getByRole("button", { name: "Export" }).last().click();
        await page.getByRole("menuitem", { name: label }).click();

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
      await page.getByRole("button", { name: "Export" }).last().click();

      const items = page.getByRole("menuitem");
      await expect(items).toHaveCount(3);

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
});
