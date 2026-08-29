import { expect, test } from "@playwright/test";

import {
  appendCspRow,
  describeViolations,
  installCspProbe,
  isCspConsoleMessage,
  readCspHeader,
  readCspViolations,
  waitForClientRuntime,
} from "./support/csp";
import type { CspViolation } from "./support/csp";
import { installFirstPaintProbe, readFirstPaint } from "./support/measure";
import { DEFERRED_STATES, SECTION_4_ROWS, STATES, readyLocator } from "./support/states";

/**
 * WO-30 criteria 1, 2 and 3 — the CSP, in a browser, on every §4 state.
 *
 * WHAT THIS SWEEP IS FOR. A CSP is the one control in this repository whose
 * failure mode is *silence*: a policy that is slightly too strict does not
 * throw, it refuses a script, and the page then renders without the thing
 * that script did. The theme flash WO-01 exists to prevent is exactly that
 * failure, one directive away. So the policy is not shipped on the strength
 * of being written correctly — it is shipped on the strength of forty-odd
 * navigations through the composed product with the browser's own violation
 * reporting turned on.
 *
 * CRITERION 1'S TWO RUNS, AND HOW THEY ARE PRODUCED FROM ONE BUILD. C3 says
 * "Ship `Content-Security-Policy-Report-Only` first ... then flip to
 * enforcing", and the card asks for both runs recorded in the same PR.
 * `CSP_MODE` on the `web` service switches the header NAME and nothing else
 * (`lib/server/csp.ts`), so the Report-Only run and the enforcing run observe
 * the *same policy* two ways — which is what makes the first one evidence for
 * the second. Both runs execute this file unchanged:
 *
 *     CSP_MODE=report-only npm run e2e:stack:up && npm run e2e -- --project=chromium
 *     CSP_MODE=enforce     npm run e2e:stack:up && npm run e2e -- --project=chromium
 *
 * Every test below asserts on whichever mode it finds, and `sweep.tsv` in
 * `build/e2e/csp/` records which one it was. The default — and therefore what
 * CI runs and what ships — is enforcing.
 *
 * "EVERY STATE IN §4" MEANS `STATES`, AND THE PARTITION TEST IS WHY THAT IS
 * HONEST. `support/states.ts` is WO-21's translation of the §4 map into what
 * a browser can reach, with `DEFERRED_STATES` carrying the rows that have no
 * distinct rendered layout and the reason for each. The first test below
 * re-asserts that the two lists partition §4 — the same assertion
 * `reflow.spec.ts` makes — so this sweep cannot silently cover less than the
 * matrix by a row quietly disappearing from both lists.
 *
 * CHROMIUM-ONLY, TAGGED `@csp`, FOR THE REASON THE AXE SWEEP IS. Forty
 * navigations run three times would treble the slowest tier for no new
 * evidence: a CSP violation is a property of the policy and the markup, not
 * of the engine. The one place engines genuinely differ — whether
 * `style-src-attr` is honoured — was measured directly across chromium,
 * firefox and webkit while the policy was being chosen, and the result is
 * recorded on the directive in `lib/server/csp.ts`.
 */

/** Rows §4 lists that this sweep does not visit, and why. Same list as the reflow sweep. */
test.describe("§4 coverage", () => {
  test(
    "every §4 row is either swept here or deferred with a reason",
    { tag: "@csp" },
    async () => {
      const swept = new Set(STATES.flatMap((state) => state.rows));
      const deferred = new Set(DEFERRED_STATES.flatMap((entry) => entry.rows));
      expect(
        SECTION_4_ROWS.filter((row) => !swept.has(row) && !deferred.has(row)),
        "a row in neither list is a state this sweep silently does not cover",
      ).toEqual([]);
    },
  );
});

test.describe("criterion 1 — zero CSP violations on every reachable §4 state", () => {
  for (const state of STATES) {
    test(
      `${state.id} (§4 ${state.rows.join(", ")})`,
      { tag: "@csp" },
      async ({ page }, info) => {
        const consoleMessages: string[] = [];
        page.on("console", (message) => {
          if (message.type() === "error" && isCspConsoleMessage(message.text())) {
            consoleMessages.push(message.text());
          }
        });
        page.on("pageerror", (error) => {
          if (isCspConsoleMessage(error.message)) consoleMessages.push(error.message);
        });

        await installCspProbe(page);
        await state.arrange?.(page);
        const response = await page.goto(state.path, { waitUntil: "domcontentloaded" });

        // Never sweep a blank page. The same guard the reflow and axe sweeps
        // use, and it matters more here: a document that never executed a
        // script produces no violations for the happiest possible reason.
        await expect(readyLocator(page, state.ready)).toBeVisible();
        // …and never sweep a page whose scripts were all refused. See
        // `waitForClientRuntime` — under 'strict-dynamic' that failure is
        // silent and looks exactly like a correctly rendered page.
        await waitForClientRuntime(page);
        // Let late chunks and the SSE reconnect settle; a violation that
        // arrives after the assertion is a violation that did not fail.
        await page.waitForTimeout(1_500);

        const header = readCspHeader(response);
        const violations = await readCspViolations(page);
        appendCspRow(info.outputDir, {
          state: state.id,
          rows: state.rows,
          mode: header.mode,
          violations,
          consoleMessages,
        });

        expect(
          header.mode,
          `${state.path} was served with no Content-Security-Policy at all. ` +
            "Either the middleware matcher stopped covering it or CSP_MODE is `off`.",
        ).not.toBe("absent");

        expect(
          violations as CspViolation[],
          `CSP violations on ${state.id} (${header.mode}):\n` +
            describeViolations(violations, consoleMessages),
        ).toEqual([]);
        expect(
          consoleMessages,
          `CSP console errors on ${state.id} (${header.mode})`,
        ).toEqual([]);
      },
    );
  }
});

test.describe("criterion 2 — the header on the wire is the ratified policy", () => {
  test("carries every directive, with a fresh nonce per request", { tag: "@csp" }, async ({
    page,
  }) => {
    const first = readCspHeader(await page.goto("/", { waitUntil: "domcontentloaded" }));
    const second = readCspHeader(await page.goto("/", { waitUntil: "domcontentloaded" }));

    for (const directive of [
      "default-src 'self'",
      "script-src 'self' 'nonce-",
      "'strict-dynamic'",
      "style-src 'self'",
      "img-src 'self' data:",
      "font-src 'self'",
      "connect-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'none'",
      "object-src 'none'",
      "form-action 'self'",
    ]) {
      expect(first.policy, `missing directive: ${directive}`).toContain(directive);
    }
    // The nonce is what the whole policy rests on. A constant one is a
    // nonce-shaped string and no more useful than 'unsafe-inline'.
    expect(first.nonce).not.toBeNull();
    expect(first.nonce).not.toBe(second.nonce);
    expect(first.policy).not.toContain("'unsafe-eval'");
  });

  test(
    "the excluded paths carry the inert policy instead of none",
    { tag: "@csp" },
    async ({ request }) => {
      // RC-07's matcher skips these three so the proxy and the assets take no
      // extra hop. `next.config.mjs` is what keeps that from being a hole.
      for (const path of ["/api/healthz", "/icon.svg"]) {
        const response = await request.get(path);
        expect(response.status(), path).toBe(200);
        expect(response.headers()["content-security-policy"], path).toBe(
          "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        );
        expect(response.headers()["x-content-type-options"], path).toBe("nosniff");
      }
    },
  );

  test(
    "`connect-src 'self'` really does admit the SSE stream",
    { tag: "@csp" },
    async ({ page }) => {
      // C3 justifies `connect-src 'self'` with one sentence — "sufficient
      // because SSE is same-origin" — and that sentence is the load-bearing
      // one for the whole product: every run's progress arrives this way. So
      // it is asserted from INSIDE a document governed by the policy, with a
      // real `EventSource`, rather than from Playwright's request context,
      // which is not subject to CSP at all and would have proved nothing.
      await installCspProbe(page);
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await waitForClientRuntime(page);

      const opened = await page.evaluate(async () => {
        const source = new EventSource("/api/research/baseline-running/stream");
        try {
          return await new Promise<string>((resolve) => {
            const settle = (outcome: string): void => {
              source.close();
              resolve(outcome);
            };
            source.addEventListener("open", () => settle("open"));
            source.addEventListener("message", () => settle("open"));
            source.addEventListener("error", () => settle("error"));
            window.setTimeout(() => settle("timeout"), 10_000);
          });
        } finally {
          source.close();
        }
      });

      expect(
        opened,
        "the EventSource did not connect under the policy — `connect-src` is " +
          "the directive that would have refused it",
      ).toBe("open");
      expect(await readCspViolations(page)).toEqual([]);
    },
  );
});

test.describe("criterion 3 — the pre-paint theme script survives the policy", () => {
  test(
    "the theme script carries the nonce the header advertises",
    { tag: "@csp" },
    async ({ page }) => {
      const header = readCspHeader(await page.goto("/", { waitUntil: "domcontentloaded" }));
      expect(header.nonce).not.toBeNull();

      const nonces = await page.evaluate(() =>
        Array.from(document.querySelectorAll("script")).map((script) => ({
          inline: script.src === "",
          // `getAttribute` rather than `.nonce`: browsers blank the IDL
          // attribute after parsing to keep the value away from CSS
          // exfiltration, so the property would read empty even when the
          // markup carried it. What matters is the markup.
          hasNonce: script.hasAttribute("nonce"),
          text: script.textContent?.slice(0, 40) ?? "",
        })),
      );

      const themeScript = nonces.find((script) => script.text.includes("arxiv-agent.theme"));
      expect(
        themeScript,
        "the pre-paint theme script is not in the document at all",
      ).toBeDefined();
      expect(
        themeScript?.hasNonce,
        "the theme script has no nonce, so 'strict-dynamic' refuses it and the " +
          "theme is applied after hydration instead — which IS the flash",
      ).toBe(true);
      // And every other script too: one un-nonced bundle chunk is a page that
      // never hydrates.
      expect(nonces.filter((script) => !script.hasNonce)).toEqual([]);
    },
  );

  test(
    "a stored dark preference is still painted on the first frame",
    { tag: "@csp" },
    async ({ page }) => {
      // WO-01's deferred proof, re-taken with the enforcing header live. This
      // duplicates `theme.spec.ts`'s first assertion on purpose: that file
      // proves the script works, and this one proves the CSP did not stop it.
      // If the nonce were dropped, `theme.spec.ts` would go red at the same
      // time — and a reviewer reading only this work order's diff would have
      // no reason to look there.
      await page.addInitScript(() => {
        try {
          window.localStorage.setItem("arxiv-agent.theme", "dark");
        } catch {
          // Matches the init script's own posture.
        }
      });
      await installFirstPaintProbe(page);

      const response = await page.goto("/", { waitUntil: "domcontentloaded" });
      expect(readCspHeader(response).mode).not.toBe("absent");

      const firstPaint = await readFirstPaint(page);
      expect(firstPaint?.theme).toBe("dark");
      expect(
        firstPaint?.luminance ?? 1,
        "the first frame painted light with the CSP live, which means the " +
          "pre-paint script was refused",
      ).toBeLessThan(0.2);
    },
  );
});
