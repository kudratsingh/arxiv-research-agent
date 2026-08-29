import { expect, test } from "@playwright/test";

import { FIXTURES } from "./support/env";
import {
  RACE_FLOOR_MS,
  interruptStream,
  openGaps,
  timeoutThenHold,
} from "./support/intercept";
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

/**
 * The diagnostics note the client synthesises for a browser-managed retry
 * (`web/lib/job/machine.ts`). It lands in the `role="log"` inside the
 * **collapsed** Technical events disclosure, so it is recorded and not shown.
 *
 * WO-27 CHANGED WHICH OF THESE TWO THIS FILE ASSERTS, AND WHY. Both
 * assertions below used to wait for this sentence to be VISIBLE, and it was —
 * because of a defect. `Diagnostics` passes `panelClassName="flex flex-col
 * gap-3"` to `Disclosure`, and an author `display` declaration beats the
 * user-agent's `[hidden] { display: none }` outright (origin is resolved
 * before specificity), so the collapsed panel was on screen the whole time:
 * displayed, tabbable, and with its live region announcing. WO-27's keyboard
 * walk found it and `primitives.css` now closes it properly.
 *
 * So these tests were green on a sentence the product does not show a user.
 * They now assert the narration the user actually gets — the spine's single
 * `role="status"`, `SPINE.reconnecting` — and assert the diagnostics note
 * separately, as a hidden record. That is a strictly stronger pair: the
 * first is the claim §4 row 11 is about ("the UI must NARRATE the browser's
 * retry"), and the second is the evidence trail behind it.
 */
const DIAGNOSTIC_NOTE = /connection interrupted; browser is retrying/;

/** The spine's user-facing reconnect sentence, and its state hook. */
const RECONNECTING = "Reconnecting. Checkpoints during the gap are not replayed.";
const SPINE_STATUS = '[data-spine-part="announcement"]';

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

      // What the USER is told: one sentence, in the product's single
      // `role="status"`, that says the connection is being re-established and
      // what was lost. See DIAGNOSTIC_NOTE above for why this replaced an
      // assertion on the diagnostics wording.
      await expect(page.locator(SPINE_STATUS)).toHaveText(RECONNECTING, {
        timeout: 15_000,
      });
      await expect(page.locator("[data-spine-state]").first()).toHaveAttribute(
        "data-spine-state",
        "reconnecting",
      );

      // …and what is RECORDED: the same event, in the collapsed diagnostics
      // log, where it is available on demand and announces nothing.
      await expect(page.getByText(DIAGNOSTIC_NOTE).first()).toBeAttached();
      await expect(page.getByText(DIAGNOSTIC_NOTE).first()).toBeHidden();

      // The run itself is untouched: nothing claims failure, nothing claims
      // success, and the job id in the URL is still the one being watched.
      await expect(page.locator(RUN_PANEL)).toBeVisible();
      expect(new URL(page.url()).searchParams.get("job")).toBe(FIXTURES.running);

      // WO-27 REPLACED `toBe(1)` HERE, AND THE REASON IS IN
      // `evidence/gate-3/known-gaps.md` §2.
      //
      // The claim this test makes is "the UI must NARRATE the browser's
      // retry, not race it". `opens()` cannot express that: it counts the
      // browser's own reconnection — the behaviour being confirmed — and a
      // client-initiated second connection — the behaviour being forbidden —
      // as the same number. So `toBe(1)` went red whenever the browser's
      // backoff happened to elapse inside the 15 s wait above, which the Gate
      // 3 pack measured at 3 failures in 12 runs and called a harness defect
      // rather than a product one. It was right.
      //
      // The two are separated by TIME, not by count: `EventSource` waits its
      // reconnection interval (≥3 s in every engine this suite runs), and a
      // client racing it would reopen in the same task. So the assertion is
      // now on the GAPS, and it is strictly stronger — it stays true however
      // long the test happens to wait, and it fails on the thing it means to
      // forbid instead of on a stopwatch.
      const gaps = openGaps(stream);
      expect(stream.opens(), "the stream was never opened at all").toBeGreaterThanOrEqual(1);
      expect(
        gaps.filter((gap) => gap < RACE_FLOOR_MS),
        "two opens landed less than " +
          `${RACE_FLOOR_MS}ms apart (gaps: ${gaps.join(", ") || "none"}). The ` +
          "browser's own retry waits its reconnection interval; a gap this " +
          "short is the client opening a second EventSource of its own while " +
          "the browser is already retrying (machine.ts:352).",
      ).toEqual([]);
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
      await expect(page.locator(SPINE_STATUS)).toHaveText(RECONNECTING, {
        timeout: 15_000,
      });
      await page.waitForTimeout(2_000);

      paid.expectExactly(0, "interrupted stream (recovery is never a purchase)");
    },
  );
});
