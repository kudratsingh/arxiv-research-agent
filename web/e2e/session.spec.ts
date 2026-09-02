/**
 * WO-W13 criteria 2 and 4 — the guided-read session in a browser.
 *
 * WHAT IS REAL HERE, AND WHY THAT MATTERS.
 *
 * `GET /api/learn/sessions/{id}` is NOT intercepted. The page reads the
 * seeded stack: through the `web` container's server-side proxy, which
 * injects the API key, into FastAPI with `ENABLE_SESSION_LOOP` on, which
 * assembles `SessionDetail` from two durable sources — the Redis job row for
 * the lifecycle and the parked turn, and the LangGraph checkpoint for the
 * reading margin (`src/api/sessions.py:248-262`). Both are written behind the
 * API by `e2e/fixtures/seed.sh`.
 *
 * That split is the whole of criterion 2. An earlier draft of this file
 * fulfilled the session GET from a route handler, and it proved nothing about
 * rehydration: a reload that re-renders a transcript the *test* supplied is a
 * test asserting against itself. The transcript below exists only in a
 * checkpoint, so if `_checkpoint_values` stopped reading it — or if the
 * surface started reconstructing a margin out of stream frames it happened to
 * still hold — this file goes red.
 *
 * WHAT IS STILL INTERCEPTED, AND WHY IT MUST BE. Both session WRITES. A turn
 * resumes the graph, and the graph calls a model; the stack's key is
 * `local-preview-disabled`, so the call would fail rather than spend — but
 * "it would have failed anyway" is not a cost boundary, it is a coincidence.
 * `support/paid-path.ts` fulfils `POST /api/learn/sessions` and
 * `POST /api/learn/sessions/{id}/turn` in the browser, so neither write
 * reaches the backend at all, and the counts go into
 * `build/e2e/research-post-count.txt` beside the research one.
 *
 * NO SSE STUB. The page attaches to the real `/api/research/{id}/stream`,
 * which is the transport a session shares with a research run (ADR 0057).
 * The reload assertions are about what a *fresh* page reads from the API,
 * which is exactly the case where the stream has replayed nothing yet.
 */

import { expect, test } from "@playwright/test";

import { FIXTURES } from "./support/env";
import { interceptPaidPath } from "./support/paid-path";

const SESSION_URL = `/learn/sessions/${FIXTURES.guidedSession}`;

/**
 * The learner sentence that lives ONLY in the seeded LangGraph checkpoint.
 *
 * It is not in the job row, not in any fixture this suite serves, and not in
 * any SSE frame. Seeing it on screen means `SessionDetail.transcript` was
 * rehydrated. Kept in step with `e2e/fixtures/seed.sh`; if the two drift the
 * assertion fails loudly rather than silently matching nothing.
 */
const CHECKPOINTED_LEARNER_NOTE =
  "I expected attention to replace recurrence as the way a model relates distant tokens.";

const CHECKPOINTED_TUTOR_NOTE =
  "Hold on to that. Read section 3.2 and watch for what the paper claims recurrence cost it.";

/** The parked turn, from the seeded job row rather than the checkpoint. */
const PARKED_PROMPT =
  "You have read the Method section. Which connection between self-attention and the older recurrent approach feels least obvious to you?";

test.describe("WO-W13 guided session", () => {
  test(
    "renders the checkpointed margin, and renders it again after a reload",
    { tag: ["@slice"] },
    async ({ page }) => {
      await page.goto(SESSION_URL, { waitUntil: "domcontentloaded" });

      // The margin, from the checkpoint.
      await expect(page.getByText(CHECKPOINTED_LEARNER_NOTE)).toBeVisible();
      await expect(page.getByText(CHECKPOINTED_TUTOR_NOTE)).toBeVisible();
      // The parked turn, from the job row.
      await expect(
        page.getByRole("heading", { name: PARKED_PROMPT })
      ).toBeVisible();
      // And the surface says so, rather than presenting restored state as if
      // it had just happened.
      await expect(
        page.getByText("Session restored from its durable checkpoint.")
      ).toBeVisible();

      // A reload is the case the criterion names: nothing survives in memory,
      // so everything on screen after this came back over HTTP.
      await page.reload({ waitUntil: "domcontentloaded" });

      await expect(page.getByText(CHECKPOINTED_LEARNER_NOTE)).toBeVisible();
      await expect(page.getByText(CHECKPOINTED_TUTOR_NOTE)).toBeVisible();
      await expect(
        page.getByRole("heading", { name: PARKED_PROMPT })
      ).toBeVisible();
      // The composer is enabled because the SERVER says the session is parked
      // on the learner — not because the machine guessed a stage.
      await expect(
        page.getByRole("textbox", { name: /Write your response/ })
      ).toBeEnabled();
    }
  );

  test(
    "the paper stays the source of record beside the briefing companion",
    { tag: ["@slice"] },
    async ({ page }) => {
      await page.goto(SESSION_URL, { waitUntil: "domcontentloaded" });
      const source = page.getByRole("link", { name: "Open on arXiv" });
      await expect(source).toHaveAttribute(
        "href",
        "https://arxiv.org/abs/1706.03762"
      );
      // Link-out only: the surface never fetches or displays the full text.
      await expect(source).toHaveAttribute("target", "_blank");
    }
  );

  test(
    "one submitted turn is exactly one turn write, and no research write",
    { tag: ["@paid-path", "@slice"] },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);

      await page.goto(SESSION_URL, { waitUntil: "domcontentloaded" });
      const composer = page.getByRole("textbox", {
        name: /Write your response/,
      });
      await expect(composer).toBeEnabled();
      await composer.fill(
        "I would inspect the positional encoding ablation before deciding."
      );

      // Double click on purpose. `POST /learn/sessions/{id}/turn` resumes a
      // graph that calls a model, and it carries no idempotency key — so a
      // second one is a second paid turn, exactly as a second
      // `POST /research` is a second paid run. The interceptor's write
      // latency keeps the duplicate window open long enough for a page with
      // no guard to fail here.
      await page
        .getByRole("button", { name: "Continue the session" })
        .dblclick();

      await expect
        .poll(() => paid.sessionTurns(), { timeout: 10_000 })
        .toBeGreaterThan(0);
      // Give a second write time to arrive before declaring there was none.
      await page.waitForTimeout(1_000);

      paid.expectSessionExactly(0, 1, "guided turn, double-clicked");
      expect(paid.researchPosts()).toBe(0);
      expect(paid.conversationPosts()).toBe(0);
    }
  );

  test(
    "the create route is interdicted too, before any surface issues it",
    { tag: ["@paid-path"] },
    async ({ page }, testInfo) => {
      const paid = await interceptPaidPath(page, testInfo);
      await page.goto(SESSION_URL, { waitUntil: "domcontentloaded" });

      // No surface starts a session yet — the path view's start action is a
      // later card — so this drives the route directly from the page, which
      // is the same origin a surface would drive it from and the same place
      // the interceptor sits. What it proves is the structural claim: with
      // the interceptor installed, `POST /api/learn/sessions` is answered by
      // the harness and never reaches the backend, so a start button landing
      // later cannot spend on this tier by default.
      const body = await page.evaluate(async () => {
        const response = await fetch("/api/learn/sessions", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            path_id: "fixture-guided-read",
            resource_id: "arxiv:1706.03762",
          }),
        });
        return (await response.json()) as { session_id?: string };
      });

      // The harness's id, not a backend one: proof it was fulfilled rather
      // than forwarded. A real create mints a random hex id.
      expect(body.session_id).toBe(paid.acceptedSessionId);
      paid.expectSessionExactly(1, 0, "session create is fulfilled in-browser");
      expect(paid.researchPosts()).toBe(0);
    }
  );
});
