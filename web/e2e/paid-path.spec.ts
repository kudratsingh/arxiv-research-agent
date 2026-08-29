import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { fillComposer } from "./support/composer";
import { DEV_BASE_URL, FIXTURES, SKIP_DEV_SERVER } from "./support/env";
import { interceptPaidPath } from "./support/paid-path";

/**
 * Criterion 3 — the paid-path proof. R-01, MUST-KEEP #3, 05 §2.1 step 1.
 *
 * `POST /research` has no idempotency key, on either side of the wire
 * (`web/lib/api/client.ts:170`, `src/api/routes.py:179-197`). A duplicate is
 * a second paid run and there is no refund, so the only assertion worth
 * making is a count, and the count has to be **exactly** one — not "at most
 * one" and not "at least one". Every scenario below writes its result to
 * `build/e2e/research-post-count.txt`.
 *
 * A note on what the landing page actually does, because the assertions are
 * shaped by it. `web/app/(workspace)/page.tsx` makes TWO writes per intended
 * submission — `POST /conversations`, then `POST /research` — and holds a
 * `busy` boolean in `useState` while they run. It does NOT go through WO-10's
 * `useJobStream`, whose `submitInFlightRef` (`useJobStream.ts:248`) is a
 * synchronous once-guard; that hook is used by the *thread* composer. So the
 * landing page is the weaker of the two paths and is where these scenarios
 * are aimed. WO-13 and WO-20 rewrite it; these assertions are what must still
 * hold afterwards.
 */

const QUESTION = "A local test-only question that never reaches a model";

/** Land on `/` and fill the composer. Hydration-safe; see `fillComposer`. */
async function compose(page: Page) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  return fillComposer(page, QUESTION);
}

/** The handoff `router.push('/c/{id}?job={job_id}')` landed. §4 row A. */
async function expectHandoff(page: Page, jobId: string): Promise<void> {
  await page.waitForURL(
    (url) =>
      url.pathname === `/c/${FIXTURES.populatedConversation}` &&
      url.searchParams.get("job") === jobId,
    // Generous: the RSC payload for `/c/[id]` is fetched over the network, and
    // the seeded stack is one Next container serving every parallel worker.
    { timeout: 30_000 },
  );
}

test.describe("criterion 3 — exactly one POST /api/research per submission", () => {
  test(
    "one deliberate click is one POST",
    { tag: "@paid-path" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      const { submit } = await compose(page);

      await submit.click();
      await expectHandoff(page, paid.acceptedJobId);

      paid.expectExactly(1, "single click");
      expect(
        paid.conversationPosts(),
        "the landing journey is two writes against one hourly bucket " +
          "(routes.py:157 and :545); doubling either one costs the user their budget",
      ).toBe(1);
    },
  );

  test(
    "a double click is still one POST",
    { tag: "@paid-path" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      const { submit } = await compose(page);

      // `dblclick` dispatches two real clicks with no artificial gap, into a
      // window the interceptor deliberately holds open for 250 ms per write.
      await submit.dblclick();
      await expectHandoff(page, paid.acceptedJobId);
      // Give any second submission time to leave the page before counting.
      await page.waitForTimeout(1_000);

      paid.expectExactly(1, "double click");
      expect(paid.conversationPosts()).toBe(1);
    },
  );

  test(
    "keyboard submit is one POST, and a bare Enter is none",
    { tag: "@paid-path" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      const { box } = await compose(page);

      // A bare Enter in a multi-line composer must insert a newline, not
      // spend money. `QueryForm.tsx:26-32` binds Cmd/Ctrl+Enter and nothing
      // else, and this half of the assertion is what keeps that true.
      await box.press("Enter");
      await page.waitForTimeout(500);
      expect(
        paid.researchPosts(),
        "a bare Enter in the composer must not submit — it is a newline",
      ).toBe(0);

      await box.press("ControlOrMeta+Enter");
      await expectHandoff(page, paid.acceptedJobId);
      await page.waitForTimeout(500);

      paid.expectExactly(1, "Enter key (ControlOrMeta+Enter)");
    },
  );

  test(
    "hammering the key repeat is still one POST",
    { tag: "@paid-path" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      const { box } = await compose(page);

      // Three in a row inside the 250 ms write window: what an impatient user
      // holding the chord actually produces.
      await box.press("ControlOrMeta+Enter");
      await box.press("ControlOrMeta+Enter");
      await box.press("ControlOrMeta+Enter");

      // Deliberately NOT gated on the handoff navigation. The claim here is
      // about how many times the page tried to buy a run, and waiting for
      // `/c/[id]?job=` first would make that claim depend on how quickly one
      // Next container can serve an RSC payload to five browser projects at
      // once — which is a property of the fixture stack, not of the app.
      await page.waitForTimeout(3_000);

      paid.expectExactly(1, "repeated keyboard submit");
    },
  );

  /**
   * offline → online.
   *
   * The thing that must not happen is an automatic replay: a submission that
   * failed offline being retried by the app, the client, or a query layer the
   * moment connectivity returns. That would be a paid run the user never
   * asked for a second time.
   *
   * The assertion is written so it holds whichever way the browser reports a
   * request made while offline. Playwright's `setOffline` is implemented
   * below the routing layer in some engines and above it in others, so the
   * offline attempt may or may not be counted; what is asserted is that the
   * count does not move *on its own* once the network returns, and that the
   * next deliberate submission adds exactly one.
   */
  test(
    "offline then online replays nothing, and the retry is one POST",
    { tag: "@paid-path" },
    async ({ page, context }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      const { submit } = await compose(page);

      await context.setOffline(true);
      paid.setOffline(true);
      // WO-08's shell states it (never announces it): `data-workbench-offline`.
      await expect(page.locator("[data-workbench-shell]")).toHaveAttribute(
        "data-workbench-offline",
        "",
      );

      await submit.click();
      // The submission fails and says so IN THE COMPOSER, without navigating.
      //
      // Scoped to the composer's own form rather than `getByRole("alert")`:
      // going offline also fails the rail's conversation list, which raises
      // its own alert, and on Firefox both are present. An unscoped locator
      // would have been satisfied by the rail's message — a pass that says
      // nothing about the submission.
      const composer = page
        .locator("form")
        .filter({ has: page.getByRole("textbox", { name: "Research question" }) });
      await expect(composer.getByRole("alert")).toBeVisible();
      await page.waitForTimeout(1_000);
      const afterOfflineAttempt = paid.researchPosts();

      await context.setOffline(false);
      paid.setOffline(false);
      await expect(page.locator("[data-workbench-shell]")).not.toHaveAttribute(
        "data-workbench-offline",
        "",
      );
      // Nobody touches anything. Two seconds is well past any retry backoff a
      // fetch layer would use.
      await page.waitForTimeout(2_000);
      expect(
        paid.researchPosts(),
        "coming back online must not replay a failed submission: " +
          `count was ${afterOfflineAttempt} offline and moved on its own`,
      ).toBe(afterOfflineAttempt);

      // The user tries again. That is one intentional submission.
      await submit.click();
      await expectHandoff(page, paid.acceptedJobId);
      await page.waitForTimeout(500);

      paid.expectExactly(
        afterOfflineAttempt + 1,
        `offline then online (offline attempt counted as ${afterOfflineAttempt})`,
      );
    },
  );

  /**
   * React StrictMode's double mount.
   *
   * This is the one scenario that cannot be run against the production
   * container. `next.config.mjs` sets `reactStrictMode: true`, but React's
   * double invocation of effects is development-only — in a production build
   * `<StrictMode>` is inert, so asserting it there would assert nothing. So
   * this runs against a real `next dev` (see `playwright.config.ts`
   * `webServer`), where every effect genuinely runs twice on mount.
   *
   * The attach path is what StrictMode threatens: `ConversationThread.tsx:112`
   * calls `attach(adoptJobId)` from an effect. If that effect were not
   * idempotent, a double mount would open two streams — and, in a version of
   * the code that submitted instead of adopting, buy a second run. So the
   * assertion is both halves: `POST /api/research` stays at ZERO on the
   * attach path, and the adopted job id is unchanged.
   */
  test(
    "StrictMode double mount adopts, and never submits",
    { tag: "@paid-path" },
    async ({ page }, testInfo) => {
      test.skip(
        SKIP_DEV_SERVER,
        "E2E_SKIP_DEV_SERVER=1: React StrictMode's double mount only happens " +
          "in a development build, so there is nothing to assert against the " +
          "production container. Skipped rather than passed vacuously.",
      );

      // `next dev` compiles each route on its first request, and this
      // navigation is the first request for `/c/[id]`, for `/api/[...path]`
      // and for two API paths through it. That is tens of seconds of tsc on a
      // cold server, none of it the app's behaviour.
      test.setTimeout(180_000);

      const paid = await interceptPaidPath(page, testInfo);
      const target = `${DEV_BASE_URL}/c/${FIXTURES.populatedConversation}?job=${FIXTURES.running}`;

      // Warm the routes. The interceptor is already installed, so anything
      // this pass submits would still be counted — the warm-up is not a way
      // to hide a first-mount POST.
      await page.goto(target, { waitUntil: "domcontentloaded", timeout: 120_000 });
      await expect(page.getByText("Current turn")).toBeVisible({ timeout: 120_000 });

      // Now a clean mount against a compiled server, where the only thing
      // slow is React itself — and React here is a development build, so the
      // effects run twice.
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.getByText("Current turn")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText(FIXTURES.running)).toBeVisible();
      await page.waitForTimeout(1_500);

      paid.expectExactly(0, "StrictMode double mount (attach path, next dev)");
      expect(
        new URL(page.url()).searchParams.get("job"),
        "the double-mounted thread must re-adopt the SAME job, not start one",
      ).toBe(FIXTURES.running);
    },
  );
});
