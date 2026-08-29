import { expect, test } from "@playwright/test";

import { FIXTURES } from "./support/env";
import { interruptStream, timeoutThenHold } from "./support/intercept";
import { interceptPaidPath } from "./support/paid-path";
import { RUN_PANEL } from "./support/states";

/**
 * Criterion 4 — the two stream failures a seeded stack cannot produce on
 * demand. 04 §7.2, last paragraph; 05 §2.1 step 4; §4 rows 11 and 25.
 *
 * Everything else in this suite streams from the real backend. These two do
 * not, and `web/e2e/support/intercept.ts` explains why for each.
 */

const THREAD = `/c/${FIXTURES.populatedConversation}`;

test.describe("criterion 4 — interrupted 200 stream and stream_timeout", () => {
  /**
   * §4 row 11. The technique is `capture-baseline.spec.ts:63-76`'s, and the
   * sentence asserted is WO-10's, from `web/lib/job/machine.ts:352-358`.
   *
   * What makes this the right assertion rather than a nicer-looking one: the
   * UI must NARRATE the browser's retry, not race it. `EventSource` owns
   * reconnection; a client that opened its own second connection on `error`
   * would double the load and still not know more. So the observable is a
   * `stream_note` in the log, and the stream open count staying at one while
   * the browser waits out its own backoff.
   */
  test(
    "an interrupted 200 stream is narrated, not raced",
    { tag: "@stream" },
    async ({ page }) => {
      const stream = await interruptStream(page, FIXTURES.running);

      await page.goto(`${THREAD}?job=${FIXTURES.running}`, {
        waitUntil: "domcontentloaded",
      });

      await expect(
        page.getByText(/connection interrupted; browser is retrying/),
      ).toBeVisible({ timeout: 15_000 });

      // The run itself is untouched: nothing claims failure, nothing claims
      // success, and the job id in the URL is still the one being watched.
      await expect(page.locator(RUN_PANEL)).toBeVisible();
      expect(new URL(page.url()).searchParams.get("job")).toBe(FIXTURES.running);

      expect(
        stream.opens(),
        "the client must not open a second EventSource of its own while the " +
          "browser is already retrying (machine.ts:352)",
      ).toBe(1);
    },
  );

  /**
   * §4 row 25. `stream_timeout` means the RESPONSE hit
   * `api_sse_max_duration_sec`, not that the run stopped
   * (`src/api/streaming.py:295-309`). So the only correct response is an
   * immediate reopen, and the only way to observe a reopen from outside is to
   * count connections.
   *
   * This is also the gap WO-10 closed: `useResearchStream.ts:59-66` did not
   * even register the event name, so the frame was dropped and the stream sat
   * closed until the browser's own retry timer fired.
   */
  test(
    "a stream_timeout frame reopens the stream immediately",
    { tag: "@stream" },
    async ({ page }) => {
      const stream = await timeoutThenHold(page, FIXTURES.streamTimeout);

      await page.goto(`${THREAD}?job=${FIXTURES.streamTimeout}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(page.locator(RUN_PANEL)).toBeVisible();

      await expect
        .poll(() => stream.opens(), {
          message:
            "stream_timeout must trigger a reopen (useJobStream.ts:387). One " +
            "open means the frame was dropped and the stream is sitting closed.",
          timeout: 15_000,
        })
        .toBeGreaterThanOrEqual(2);

      // A reopen is not a restart. The run is the same run.
      expect(new URL(page.url()).searchParams.get("job")).toBe(
        FIXTURES.streamTimeout,
      );
    },
  );

  /**
   * The rule underneath both of the above, stated once as its own assertion:
   * **no reconnection is ever a resubmission.**
   *
   * Neither of the two failures above is a reason to buy a new run, and
   * neither the browser's retry nor the client's reopen may become one. This
   * is R-01 seen from the stream side rather than the composer side, and it
   * is cheap to assert here where both interceptors are already installed.
   */
  test(
    "neither failure ever produces a POST /api/research",
    { tag: "@stream" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      await interruptStream(page, FIXTURES.running);

      await page.goto(`${THREAD}?job=${FIXTURES.running}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(
        page.getByText(/connection interrupted; browser is retrying/),
      ).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(2_000);

      paid.expectExactly(0, "interrupted stream (recovery is never a purchase)");
    },
  );
});
