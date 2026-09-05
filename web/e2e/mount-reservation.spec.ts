import { expect, test, type Page } from "@playwright/test";

import { FIXTURES } from "./support/env";
import { interceptPaidPath } from "./support/paid-path";

/**
 * WO-S2c — the run panel holds its place on a phone.
 *
 * THE DEBT THIS PAYS, AND WHOSE IT IS. WO-S2b closed the review pause's
 * cold-load CLS at 1280x900 — 0.05113 to 0.00002 — by making `PlanEditor`'s
 * Suspense fallback an exact mirror of the form. It deliberately did not
 * absorb what remained at 412x915, and said why: the fallback is a DESCENDANT
 * of the box that moves there, so sizing it cannot help. Two shifts remained,
 * measured on the seeded stack over 16 cold loads at plain 412x915:
 *
 *   0.55191, on 4 of 16 loads — `div.ew-thread__timeline` [y 410, h 435] and
 *   `div.ew-thread__composer` [y 845, h 70] both pushed entirely out of view.
 *   The run panel mounting in a shape it does not keep: `GET /conversations`
 *   answers before `GET /research/{id}` does, so the thread paints with the
 *   row reporting `attached` — the 224px bounded box — about a run nobody has
 *   read, and the read then turns it into the 1,769px review pause.
 *
 *   0.01147, on 9 of 16 loads — `section.flex` [y 506, h 409] -> [y 530,
 *   h 385], the plan editor and a 32px sibling moving down 24px. The spine's
 *   `Live` badge arriving when the socket opens. At 1280 it joins the
 *   announcement line and WO-W13c's `align-self: center` keeps that line 20px;
 *   at 412 the announcement already takes both lines the row wraps to, so the
 *   badge cannot join anything — it wraps onto a third line and the row goes
 *   40px to 64px.
 *
 * Both are reservations, and both are asserted below as EQUALITIES rather
 * than as bounds, for the reason `plan-fallback.spec.ts` gives: a reservation
 * that is too generous swaps a shift down for a shift up, which is the same
 * defect with the sign flipped.
 *
 * WHY EACH TEST HOLDS A RESPONSE RATHER THAN RACING ONE. A CLS number is a
 * measurement of a race — on a fast enough machine both answers land in one
 * commit and nothing is charged, which is exactly why the 0.55191 appeared on
 * only 4 of 16 loads. A gate that fires a quarter of the time is not a gate.
 * So each test below holds the ONE response whose lateness is the subject:
 * `GET /research/{id}` for the panel's shape, the SSE stream for the badge.
 * Holding makes the worst case certain, and the worst case is a superset of
 * the plain cold load's — anything that passes here passes unheld.
 */

/** 04 §8.2's ceiling, the same constant `cls.spec.ts` gates on. */
const LOAD_CLS_CEILING = 0.02;

/** Long enough that the transcript is certain to land first. */
const HOLD = 600;

const REVIEW = `/c/${FIXTURES.populatedConversation}?job=${FIXTURES.planReview}`;

const WIDTHS = [
  { label: "1280x900", width: 1280, height: 900 },
  { label: "412x915", width: 412, height: 915 },
] as const;

interface FirstPaint {
  /** The box's height on the first frame it exists at all, or -1. */
  first: number;
  /** `data-run` on that same frame. */
  dataRun: string | null;
}

interface LoadShift {
  value: number;
  startTime: number;
  sources: { node: string; from: number[]; to: number[] }[];
}

interface LoadBucket {
  supported: boolean;
  total: number;
  entries: LoadShift[];
}

declare global {
  interface Window {
    __mountFirst?: Record<string, FirstPaint>;
    __mountCls?: LoadBucket;
  }
}

/**
 * Record the height of each named box on the first frame it exists.
 *
 * A `requestAnimationFrame` loop and not a `MutationObserver`: the claim is
 * about what the browser PAINTS, and a frame is the unit it paints in. The
 * loop is installed before any page script, so the first frame it sees is the
 * first frame there is.
 */
async function observeFirstPaint(
  page: Page,
  selectors: Record<string, string>,
): Promise<void> {
  await page.addInitScript((named: Record<string, string>) => {
    const seen: Record<string, FirstPaint> = {};
    window.__mountFirst = seen;
    const tick = () => {
      for (const [name, selector] of Object.entries(named)) {
        if (seen[name] !== undefined) continue;
        const element = document.querySelector(selector);
        if (element === null) continue;
        seen[name] = {
          first: Number(element.getBoundingClientRect().height.toFixed(2)),
          dataRun: element.getAttribute("data-run"),
        };
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, selectors);
}

/**
 * The layout-shift accumulator, installed before any page script.
 *
 * `buffered: true` hands over the entries the browser recorded before the
 * observer existed, which is what makes this a cold-load measurement rather
 * than a post-hydration one. Copied in shape from `plan-fallback.spec.ts`,
 * including the sources: "0.55 exceeds 0.02" tells the next reader nothing
 * about which box moved.
 */
async function observeLoadShift(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const supported =
      typeof PerformanceObserver !== "undefined" &&
      (PerformanceObserver.supportedEntryTypes ?? []).includes("layout-shift");
    const bucket: LoadBucket = { supported, total: 0, entries: [] };
    window.__mountCls = bucket;
    if (!supported) return;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const shift = entry as PerformanceEntry & {
          value: number;
          hadRecentInput: boolean;
          sources?: {
            node?: Element | null;
            previousRect: DOMRectReadOnly;
            currentRect: DOMRectReadOnly;
          }[];
        };
        if (shift.hadRecentInput) continue;
        bucket.total += shift.value;
        bucket.entries.push({
          value: Number(shift.value.toFixed(5)),
          startTime: Math.round(shift.startTime),
          sources: (shift.sources ?? []).map((source) => ({
            node:
              source.node === undefined || source.node === null
                ? "(detached)"
                : `${source.node.tagName.toLowerCase()}.${
                    String(source.node.className).trim().split(/\s+/)[0] ?? ""
                  }`,
            from: [
              Math.round(source.previousRect.y),
              Math.round(source.previousRect.height),
            ],
            to: [
              Math.round(source.currentRect.y),
              Math.round(source.currentRect.height),
            ],
          })),
        });
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
}

/**
 * Hold `GET /research/{id}` — and nothing else on that prefix.
 *
 * A URL predicate on `pathname` rather than a glob, for the reason
 * `support/paid-path.ts` gives: `**​/api/research/*` would also catch
 * `/api/research/{id}/stream` and `/api/research/{id}/export`, and holding the
 * stream would be a different experiment. The trailing `[^/]+$` is what keeps
 * it to the one read.
 */
async function holdRunRead(page: Page): Promise<void> {
  await page.route(
    (url) => /\/api\/research\/[^/]+$/.test(url.pathname),
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, HOLD));
      await route.continue();
    },
  );
}

/** The height of one box, or -1 when it is not on the page. */
async function boxHeight(page: Page, selector: string): Promise<number> {
  return page.evaluate((sel) => {
    const element = document.querySelector(sel);
    return element === null
      ? -1
      : Number(element.getBoundingClientRect().height.toFixed(2));
  }, selector);
}

test.describe("WO-S2c — the run panel mounts once, at the height it keeps", () => {
  test(
    "cold-loading the review pause at 412x915 stays inside the CLS budget",
    { tag: "@cls" },
    async ({ page, browserName }, testInfo) => {
      test.skip(
        browserName !== "chromium",
        "`layout-shift` is a Chromium-only performance entry: Firefox and " +
          "WebKit implement neither it nor CLS, so this would collect nothing " +
          "and pass without measuring.",
      );
      const paid = await interceptPaidPath(page, testInfo);

      await page.setViewportSize({ width: 412, height: 915 });
      await observeLoadShift(page);
      // The forced worst case, not a hope: see the header.
      await holdRunRead(page);
      await page.goto(REVIEW, { waitUntil: "domcontentloaded" });

      // The form itself, so nothing is asserted until every late arrival the
      // pause has — the run read, the socket, and the lazy editor chunk — has
      // landed and had its chance to move the page.
      await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible();
      // A shift is reported on the frame after the one that caused it.
      await page.waitForTimeout(1_500);

      const cls = await page.evaluate(
        () => window.__mountCls ?? { supported: false, total: 0, entries: [] },
      );

      expect(
        cls.supported,
        "the `layout-shift` entry type is not available, so nothing was " +
          "measured. This assertion must never pass by default.",
      ).toBe(true);
      expect(
        cls.total,
        `cold-load CLS on the review pause at 412x915 is ${cls.total.toFixed(5)} ` +
          `against 04 §8.2's ${LOAD_CLS_CEILING} ceiling. Before WO-S2c this ` +
          "read 0.56339 with the run read held — 0.55191 from the run panel " +
          "mounting as the 224px `attached` box and then becoming the review " +
          "pause, plus 0.01147 from the spine's `Live` badge wrapping the " +
          "announcement line onto a third row when the socket opened. A " +
          "`div.ew-thread__timeline` in the sources below is the first; a " +
          "`section.flex` moving 24px is the second. Entries: " +
          JSON.stringify(cls.entries),
      ).toBeLessThanOrEqual(LOAD_CLS_CEILING);

      paid.expectExactly(0, "WO-S2c — cold-loading a paused run");
    },
  );

  for (const size of WIDTHS) {
    test(
      `the run row is the height it keeps on the frame it first exists, at ${size.label}`,
      { tag: "@cls" },
      async ({ page }, testInfo) => {
        const paid = await interceptPaidPath(page, testInfo);
        await page.setViewportSize({ width: size.width, height: size.height });

        await observeFirstPaint(page, { row: ".ew-thread__run" });
        await holdRunRead(page);
        await page.goto(REVIEW, { waitUntil: "domcontentloaded" });

        await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible();
        await page.waitForTimeout(500);

        const first = (await page.evaluate(() => window.__mountFirst ?? {})).row;
        const settled = await boxHeight(page, ".ew-thread__run");

        expect(
          first,
          "the run row never appeared, so nothing was measured.",
        ).toBeDefined();
        // THE WHOLE CLAIM, IN ONE COMPARISON. Not "at least as tall":
        // over-reserving would shift the page UP when the real height
        // arrived, which is the same defect with the sign flipped.
        expect(
          first?.first,
          `at ${size.label} the run row first painted at ${first?.first}px and ` +
            `settled at ${settled}px. On \`origin/main\` those are 224 and ` +
            `${size.width === 412 ? "1769" : "995"}: the row paints as the ` +
            "bounded `attached` box while `GET /research/{id}` is still in " +
            "flight, and becomes the review pause when it lands. " +
            "`ThreadTimeline` holds the loading frame until the run behind " +
            "`?job=` has been read, so the row mounts once (`isRunUnread`).",
        ).toBe(settled);
        // The mechanism, so a future change cannot satisfy the equality by
        // deleting the pause's geometry instead of by reserving it: the first
        // painted row is already the review pause's row, not a bounded one
        // that happens to match.
        expect(
          first?.dataRun,
          `the run row first painted with data-run="${first?.dataRun}". At the ` +
            "review pause it must never paint as `attached` — that value " +
            "means \"a run is on this page AND events are arriving\", which " +
            "is a claim about a run that has not been read yet.",
        ).toBe("review");

        paid.expectExactly(0, `WO-S2c — holding the run read at ${size.label}`);
      },
    );
  }

  /**
   * The second reservation, at the width that has it.
   *
   * The STREAM is held rather than the read, because the badge's arrival is
   * the socket opening and nothing else. At 1280 this row measures 20px before
   * and after — that is WO-W13c's rule 4 holding — so the width that needs the
   * assertion is the narrow one, and it is the one 04 §8.3 audits.
   *
   * `p:has(> [data-spine-part="announcement"])` rather than the row's class
   * list: the class list is six utilities long and would pin this test to a
   * styling decision, while the part attribute is the contract `stream.spec.ts`
   * and `cls.spec.ts` already read the line by.
   */
  test(
    "the spine's announcement row is the height it keeps before the socket opens",
    { tag: "@cls" },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      await page.setViewportSize({ width: 412, height: 915 });

      const ROW = 'p:has(> [data-spine-part="announcement"])';
      await observeFirstPaint(page, { line: ROW });
      await page.route(
        (url) => /\/api\/research\/[^/]+\/stream$/.test(url.pathname),
        async (route) => {
          await new Promise((resolve) => setTimeout(resolve, HOLD));
          await route.continue();
        },
      );
      await page.goto(REVIEW, { waitUntil: "domcontentloaded" });

      // `data-live="true"` exists only once the socket is open, which is the
      // frame the badge becomes visible on.
      await expect(
        page.locator('[data-spine-state][data-live="true"]'),
      ).toHaveCount(1);
      await page.waitForTimeout(500);

      const first = (await page.evaluate(() => window.__mountFirst ?? {})).line;
      const settled = await boxHeight(page, ROW);

      expect(
        first,
        "the spine's announcement row never appeared, so nothing was measured.",
      ).toBeDefined();
      expect(
        first?.first,
        `at 412x915 the announcement row first painted at ${first?.first}px and ` +
          `settled at ${settled}px. On \`origin/main\` those are 40 and 64: ` +
          "the `Live` badge cannot join a line the announcement has already " +
          "used both rows of, so it wraps onto a third and takes 24px of " +
          "reading column with it. `TraceSpine` reserves the badge's box " +
          "wherever a socket is expected (`socketExpected`, " +
          "`ew-spine-live--reserved`); a difference here means the reserved " +
          "box and the live one have stopped being the same box.",
      ).toBe(settled);

      paid.expectExactly(0, "WO-S2c — holding the stream");
    },
  );
});
