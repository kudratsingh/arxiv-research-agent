import type { Page } from "@playwright/test";

import { FIXTURES } from "./env";

/**
 * The §4 state coverage map, as something a browser can walk.
 *
 * `06-WORK-ORDERS.md` §4 is a 31-row table (1–25 plus A–F) and criterion 5
 * says the reflow sweep runs on "every state in §4". This module is the
 * honest translation of that sentence into what is *reachable in a browser
 * on this commit*, because §4 is a map of the finished product and the
 * finished product does not exist yet: WO-20 composes the new surfaces, and
 * until it does, `/` and `/c/[id]` render WO-08's shell around the legacy
 * `QueryForm`, `ConversationSidebar` and `ConversationThread`.
 *
 * So every row is accounted for in exactly one of two ways:
 *
 *   * `STATES` below — reachable now, swept now.
 *   * `DEFERRED_STATES` below — has no distinct rendered layout on this
 *     commit, with the reason and the work order that creates it. These are
 *     not silently dropped; `reflow.spec.ts` asserts the two lists partition
 *     the whole of §4, so a row cannot go missing when WO-20 lands.
 *
 * Selectors here are WO-08's dedicated hooks (`data-workbench-shell`,
 * `data-rail-mode`, …) and stable ARIA roles, never CSS classes. WO-20 will
 * swap the surfaces underneath; roles and data hooks are what survive that.
 *
 * WO-20 HAS NOW LANDED, AND THIS IS WHAT IT CHANGED. `/` and `/c/[id]` render
 * `LandingComposer`, `ThreadTimeline` and `ActiveRunPanel` instead of
 * `QueryForm` and `ConversationThread`, so the ready conditions below moved
 * from the legacy strings to the designed ones — the approved copy in
 * `lib/copy/`, and two new surface hooks (`data-surface="active-run"`,
 * `data-report-reader`). Row 23 moved out of `DEFERRED_STATES` and into
 * `STATES`, which is the move the partition test exists to force. Nothing
 * about the table's SHAPE changed: same fields, same helpers, same
 * `arrange` contract.
 */

/**
 * WO-20's run panel, by its own hook.
 *
 * Exported because four specs need it and a fourth copy of a selector string
 * is how a rename becomes a silent skip. It replaces `getByText("Current
 * turn")`, which was the legacy `ConversationThread` panel's caption — a
 * sentence rather than a hook, and one the redesign does not print.
 */
export const RUN_PANEL = '[data-surface="active-run"]';

/** WO-18's reading surface, for the specs that count briefings. */
export const REPORT_READER = "[data-report-reader]";

export interface StateEntry {
  /** Stable id, used in test titles and in the evidence table. */
  id: string;
  /** §4 rows this entry covers. */
  rows: readonly string[];
  /** Where to go. */
  path: string;
  /**
   * Route interception applied before navigation, for the states a seeded
   * stack cannot produce on demand.
   */
  arrange?: (page: Page) => Promise<void>;
  /**
   * True for states that live in the thread rail.
   *
   * Below `md` the rail is **not in the layout at all** (04 §8.3 repair step
   * 1) — and `WorkbenchShell.tsx` does not even mount `ThreadRailBridge`
   * until the drawer has been asked for, so at 320/360/412 these states do
   * not exist until the header's disclosure button is pressed. The sweep
   * therefore opens the drawer at narrow widths, which is not a workaround:
   * it is the product's answer to "where did the rail go", and measuring the
   * page with the drawer open is measuring the state a user is actually in.
   */
  inRail?: true;
  /**
   * Something that must be on the page before measuring, so the sweep can
   * never pass against an empty document — "no horizontal scroll" is trivially
   * true of a blank page, which is exactly how a responsive assertion rots.
   * Every entry has one, deliberately.
   */
  ready: ReadyCondition;
}

/**
 * A stable surface hook, visible text, or a control resolved by role and
 * accessible name.
 *
 * Surface hooks are for states whose approved copy is intentionally
 * normalized away from wire details. In particular, the rail never exposes
 * an upstream error body as its user-facing sentence, and the product 404 no
 * longer carries Next's framework-default wording.
 */
export type ReadyCondition =
  | { kind: "selector"; value: string }
  | { kind: "text"; value: string | RegExp }
  | { kind: "role"; role: "textbox" | "button"; name: string };

/** Sugar so the table below reads as a table. */
const selector = (value: string): ReadyCondition => ({ kind: "selector", value });
const text = (value: string | RegExp): ReadyCondition => ({ kind: "text", value });
const textbox = (name: string): ReadyCondition => ({
  kind: "role",
  role: "textbox",
  name,
});

/** Resolve a `ReadyCondition` against a page. */
export function readyLocator(page: Page, ready: ReadyCondition) {
  if (ready.kind === "selector") return page.locator(ready.value).first();
  if (ready.kind === "text") return page.getByText(ready.value).first();
  return page.getByRole(ready.role, { name: ready.name }).first();
}

/** JSON body helper for the interception entries. */
async function fulfilJson(
  page: Page,
  predicate: (url: URL) => boolean,
  status: number,
  body: unknown,
): Promise<void> {
  await page.route(predicate, async (route) => {
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

const CONVERSATIONS = (url: URL): boolean => url.pathname === "/api/conversations";
const POPULATED = `/c/${FIXTURES.populatedConversation}`;

/**
 * Reachable today. Ordered to match §4 so the two can be diffed by eye.
 */
export const STATES: readonly StateEntry[] = [
  {
    id: "landing",
    rows: ["1"],
    path: "/",
    // 03 §1.4's display prompt, which is now the first heading in the
    // document (`LANDING.heading`).
    ready: text("What should the literature settle?"),
  },
  {
    id: "rail-loading",
    inRail: true,
    rows: ["2", "6"],
    path: "/",
    // Held open, never resolved: the loading state IS the state under test.
    // `capture-baseline.spec.ts:32-34` uses the same technique.
    arrange: async (page) => {
      await page.route(CONVERSATIONS, async () => {
        /* deliberately never settled */
      });
    },
    ready: selector('[data-thread-rail-state="loading"]'),
  },
  {
    id: "rail-empty",
    inRail: true,
    rows: ["3"],
    path: "/",
    arrange: async (page) => {
      await fulfilJson(page, CONVERSATIONS, 200, []);
    },
    // The rail's own empty state (`THREAD_RAIL.empty`), which 03 §2.2 row 3
    // requires to be distinct from row 2's skeleton and from row 12.
    ready: text("No threads yet. Your first question starts one."),
  },
  {
    id: "rail-error-upstream",
    inRail: true,
    rows: ["4", "F"],
    path: "/",
    arrange: async (page) => {
      await fulfilJson(page, CONVERSATIONS, 502, {
        detail: "synthetic local upstream failure",
      });
    },
    // The raw upstream body is diagnostics, not product copy. WO-14 maps
    // every failed list read onto one truthful rail-error surface.
    ready: selector('[data-thread-rail-state="error"]'),
  },
  {
    id: "rail-error-proxy-503",
    inRail: true,
    rows: ["F"],
    path: "/",
    arrange: async (page) => {
      await fulfilJson(page, CONVERSATIONS, 503, {
        detail: "API_INTERNAL_BASE is not configured",
      });
    },
    ready: selector('[data-thread-rail-state="error"]'),
  },
  {
    id: "thread-empty",
    rows: ["5", "B"],
    path: `/c/${FIXTURES.emptyConversation}`,
    ready: text("Empty research thread"),
  },
  {
    id: "thread-populated",
    rows: ["7"],
    path: POPULATED,
    ready: text("Scientific claim verification"),
  },
  {
    id: "plan-review",
    rows: ["9"],
    path: `${POPULATED}?job=${FIXTURES.planReview}`,
    // WO-17's `PlanEditor` heading (`PLAN.heading`).
    ready: text("Plan"),
  },
  {
    id: "running",
    rows: ["10"],
    path: `${POPULATED}?job=${FIXTURES.running}`,
    // WO-20's run panel, which replaced the "Current turn" box. A hook
    // rather than a sentence: the spine's status line is legitimately
    // different in each of rows 10-16, and a sentence here would be pinning
    // one of them from a test about layout.
    ready: selector('[data-surface="active-run"]'),
  },
  {
    id: "cancelled",
    rows: ["13"],
    path: `${POPULATED}?job=${FIXTURES.cancelled}`,
    // 03 §3.4's status word for a cancelled run (`RUN_STATUS_WORD.cancelled`),
    // which is a word before it is a mark and a mark before it is a colour.
    ready: text("Cancelled"),
  },
  {
    id: "failed-partial",
    rows: ["14"],
    path: `${POPULATED}?job=${FIXTURES.failedPartial}`,
    // D-010 ruling 2 and H5: the failure is a banner ABOVE a briefing that
    // still renders, so the state is named by `REPORT.partial` rather than
    // by the absence of a report.
    ready: text("Partial briefing from a run that failed."),
  },
  {
    id: "failed-no-result",
    // ROW 23 TOO, AND THAT IS WHY IT LEFT `DEFERRED_STATES`. With no briefing
    // there is nothing to export and `ExportDisclosure` renders NOTHING AT
    // ALL rather than a disabled control (WO-19 criterion 4, 03 §2.2 row 23).
    // That absence is only observable on a run whose `result` is empty, which
    // is this one, so the two rows are one render and are swept as one.
    rows: ["15", "23"],
    path: `${POPULATED}?job=${FIXTURES.failed}`,
    ready: text("This run stopped before a briefing was written."),
  },
  {
    id: "expired",
    rows: ["16"],
    path: `${POPULATED}?job=${FIXTURES.expired}`,
    // H8's sentence, and the only one for an aged-out run
    // (`UNAVAILABLE_COPY`). Never "deleted", never "no permission" — the API
    // answers 404 for both and the client cannot tell which.
    ready: text("This run is no longer available."),
  },
  {
    id: "submission-error-500",
    rows: ["17"],
    path: "/",
    // The landing journey's FIRST write is `POST /conversations`
    // (`app/(workspace)/page.tsx`), so this is where a submission failure
    // surfaces today. `POST /research` is never reached, and never counted.
    arrange: async (page) => {
      await page.route(CONVERSATIONS, async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "synthetic local submission failure" }),
        });
      });
    },
    ready: textbox("Research question"),
  },
  {
    id: "rate-limited-429",
    rows: ["18"],
    path: "/",
    arrange: async (page) => {
      await page.route(CONVERSATIONS, async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        // The wire body `src/api/auth.py:178` emits, verbatim.
        await route.fulfill({
          status: 429,
          contentType: "application/json",
          headers: { "retry-after": "1800" },
          body: JSON.stringify({
            detail: { error: "rate_limited", key_id: "local", limit_per_hour: 60 },
          }),
        });
      });
    },
    ready: textbox("Research question"),
  },
  {
    id: "unauthorized-401",
    rows: ["19"],
    path: "/",
    arrange: async (page) => {
      await page.route(CONVERSATIONS, async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        // `src/api/auth.py:508-516`, verbatim.
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          headers: { "www-authenticate": "ApiKey header=X-API-Key" },
          body: JSON.stringify({ detail: "invalid_api_key" }),
        });
      });
    },
    ready: textbox("Research question"),
  },
  {
    id: "validation-422",
    rows: ["20"],
    path: "/",
    arrange: async (page) => {
      await page.route(CONVERSATIONS, async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({
            detail: [
              {
                type: "string_too_long",
                loc: ["body", "query"],
                msg: "String should have at most 8000 characters",
              },
            ],
          }),
        });
      });
    },
    ready: textbox("Research question"),
  },
  {
    id: "thread-not-found-inline",
    rows: ["21"],
    path: `/c/${FIXTURES.missingConversation}`,
    // H8 again, on the thread rather than the run
    // (`THREAD.notFoundHeading`), and now a real `h1`.
    ready: text("This thread is not available"),
  },
  {
    id: "route-not-found",
    rows: ["22"],
    path: "/baseline-no-such-route",
    ready: selector('[data-recovery-surface="not-found"]'),
  },
  {
    id: "attached-status-unknown",
    rows: ["C"],
    path: `${POPULATED}?job=${FIXTURES.running}`,
    // The detail read fails while the stream stays up: the run is attached
    // but its status cannot be reported. 04 §4.4's "checkpoint unknown"
    // family; a 5xx, not a 404, because a 404 means "gone" (H8).
    arrange: async (page) => {
      await fulfilJson(
        page,
        (url) => url.pathname === `/api/research/${FIXTURES.running}`,
        503,
        { detail: "synthetic detail read failure" },
      );
    },
    ready: selector('[data-surface="active-run"]'),
  },
] as const;

/**
 * §4 rows with no distinct rendered layout on this commit, and why.
 *
 * Each entry names the work order that creates the surface. `reflow.spec.ts`
 * asserts `STATES ∪ DEFERRED = §4`, so this list is a commitment rather than
 * a footnote: when WO-20 lands, a row moved out of here has to be moved into
 * `STATES`, and the partition test fails until it is.
 */
export const DEFERRED_STATES: readonly {
  rows: readonly string[];
  why: string;
}[] = [
  {
    rows: ["8"],
    why:
      "Dark mode is a theme AXIS over every other row, not a row of its own. " +
      "It is swept as a variant inside the reflow sweep and asserted for " +
      "pre-paint correctness in theme.spec.ts (WO-01's deferred proof).",
  },
  {
    rows: ["11", "12", "25"],
    why:
      "Reconnecting / rejoined-after-reload / stream-recycled are transitions, " +
      "not resting layouts. They are asserted for BEHAVIOUR in stream.spec.ts " +
      "(interrupted 200, stream_timeout reopen) and attach.spec.ts (reload and " +
      "bfcache re-adopt). Their resting layout is `running`, which is swept.",
  },
  {
    rows: ["24"],
    why:
      "Delete confirmation is now WO-14's real APG dialog rather than " +
      "`window.confirm`, so it HAS a DOM — but reaching it needs two clicks " +
      "after navigation (the row's overflow menu, then Delete), and a " +
      "`StateEntry` describes a URL plus route interception, not a script. " +
      "Adding a post-navigation hook would change the shape of this table for " +
      "one row; WO-14's own `tests/threads/confirmDialog.test.tsx` holds the " +
      "dialog's behaviour and WO-22's axe sweep covers the rail that opens it.",
  },
  {
    rows: ["A"],
    why:
      "The `router.push('/c/{id}?job=')` handoff is a navigation, and it is " +
      "asserted end-to-end as slice step 1→2 in slice.spec.ts rather than " +
      "measured as a layout.",
  },
  {
    rows: ["D", "E"],
    why:
      "Review-submitted-not-settled and review-conflict-409 are asserted as " +
      "behaviour in slice.spec.ts step 3. WO-17's PlanEditor/Submitting and " +
      "/Conflict409 are now on the route and both have a distinct layout, but " +
      "each is entered by RESOLVING the review — a click that mutates a run — " +
      "so like row 24 they are a script rather than a URL, and the resting " +
      "layout the sweep measures is `plan-review`.",
  },
] as const;

/** §4's full row set, transcribed. The partition test's other half. */
export const SECTION_4_ROWS: readonly string[] = [
  ...Array.from({ length: 25 }, (_, index) => String(index + 1)),
  "A",
  "B",
  "C",
  "D",
  "E",
  "F",
];
