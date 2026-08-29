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
 */

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

/** Either visible text, or a control resolved by role and accessible name. */
export type ReadyCondition =
  | { kind: "text"; value: string | RegExp }
  | { kind: "role"; role: "textbox" | "button"; name: string };

/** Sugar so the table below reads as a table. */
const text = (value: string | RegExp): ReadyCondition => ({ kind: "text", value });
const textbox = (name: string): ReadyCondition => ({
  kind: "role",
  role: "textbox",
  name,
});

/** Resolve a `ReadyCondition` against a page. */
export function readyLocator(page: Page, ready: ReadyCondition) {
  return ready.kind === "text"
    ? page.getByText(ready.value).first()
    : page.getByRole(ready.role, { name: ready.name }).first();
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
    ready: text("arxiv-research-agent"),
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
    ready: text("Loading…"),
  },
  {
    id: "rail-empty",
    inRail: true,
    rows: ["3"],
    path: "/",
    arrange: async (page) => {
      await fulfilJson(page, CONVERSATIONS, 200, []);
    },
    ready: text("arxiv-research-agent"),
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
    ready: text(/synthetic local upstream failure/),
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
    ready: text(/API_INTERNAL_BASE is not configured/),
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
    ready: text("Plan review"),
  },
  {
    id: "running",
    rows: ["10"],
    path: `${POPULATED}?job=${FIXTURES.running}`,
    ready: text("Current turn"),
  },
  {
    id: "cancelled",
    rows: ["13"],
    path: `${POPULATED}?job=${FIXTURES.cancelled}`,
    ready: text(/cancelled/),
  },
  {
    id: "failed-partial",
    rows: ["14"],
    path: `${POPULATED}?job=${FIXTURES.failedPartial}`,
    ready: text("Job failed"),
  },
  {
    id: "failed-no-result",
    rows: ["15"],
    path: `${POPULATED}?job=${FIXTURES.failed}`,
    ready: text("Job failed"),
  },
  {
    id: "expired",
    rows: ["16"],
    path: `${POPULATED}?job=${FIXTURES.expired}`,
    ready: text(/stream unavailable for job/),
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
    ready: text("Conversation not found."),
  },
  {
    id: "route-not-found",
    rows: ["22"],
    path: "/baseline-no-such-route",
    ready: text("This page could not be found."),
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
    ready: text("Current turn"),
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
    rows: ["23"],
    why:
      "Export refused (409) has no rendered state today: ExportDropdown.tsx:78 " +
      "is a plain <a download>, so a 409 produces a failed browser download and " +
      "no DOM. WO-19's ExportDisclosure/UnavailableNoReport is the surface; " +
      "export.spec.ts asserts what exists now — content-disposition through the " +
      "proxy for md/pdf/docx.",
  },
  {
    rows: ["24"],
    why:
      "Delete confirmation is `window.confirm` today " +
      "(ConversationSidebar.tsx:74), a native dialog with no DOM to measure. " +
      "WO-14's ThreadRail/DeleteConfirm replaces it with a real dialog.",
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
      "behaviour in slice.spec.ts step 3. Neither has a distinct layout in the " +
      "legacy PlanReview; WO-17's PlanEditor/Submitting and /Conflict409 are " +
      "the surfaces that will.",
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
