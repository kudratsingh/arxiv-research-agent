/**
 * WO-W13b — one whole guided read, from the path view to the close line.
 *
 * THIS IS GATE W1 ROW 1, AND IT IS THE ONLY FILE IN THE TIER THAT LETS A
 * WRITE REACH THE BACKEND.
 *
 * `session.spec.ts` (WO-W13) proves the session view renders and rehydrates
 * from state somebody else seeded. What it could not prove — and says so in
 * its own "Deferred" note — is that a browser can START one, because nothing
 * called `createLearnSession` and because a fulfilled create starts no graph.
 * A run that never runs cannot park on `awaiting_learner`, cannot write a
 * checkpoint, and cannot be resumed; so a suite that fulfils every session
 * write can only ever assert against its own fixtures.
 *
 * So this spec runs `interceptPaidPath` in `mock-pass-through` mode. The two
 * session writes are still counted and still recorded — the same rows, in the
 * same file, with `mode=mock-pass-through` beside them — and then forwarded.
 *
 * WHAT MAKES FORWARDING SAFE, STATED AS A PRECONDITION RATHER THAN A HOPE.
 * `support/mock-mode.ts` refuses to install the pass-through unless the stack
 * pins BOTH `USE_MOCK_DATA=true` and `ANTHROPIC_API_KEY=local-preview-
 * disabled`, checked in the overlay and — when a daemon is reachable — in the
 * running container. Under `use_mock_data` the session graph constructs no
 * model client anywhere: `check_in_agent` returns `_fallback_plan`
 * (`src/agents/tutor.py:159`), `_tutor_prompts` returns two constants
 * (`:248`), `assess_agent`'s judge has its own mock branch
 * (`src/agents/assessment.py:178`). Zero paid calls BY CONSTRUCTION, which is
 * a stronger claim than "the key would not have worked anyway". The
 * assertion is printed into the run log and recorded in
 * `build/e2e/research-post-count.txt`, and the last test here reads
 * `llm_calls` back off the finished session as the outcome-side proof.
 *
 * `POST /api/research` and `POST /api/conversations` keep the posture they
 * have always had: fulfilled in the browser, never forwarded, asserted at
 * zero below.
 *
 * WHAT IS REAL, END TO END. The start POST, the graph, the Redis job row, the
 * LangGraph checkpoint, the SSE stream, the turn POST and the progress write.
 * Nothing on screen after the reload came from this file.
 */

import { expect, test } from "@playwright/test";

import { interceptPaidPath } from "./support/paid-path";

const PATH_ID = "fixture-guided-read";
const PATH_URL = `/learn/paths/${PATH_ID}`;

/** The first entry of the seeded fixture path — the one with a companion. */
const FIRST_RESOURCE = "arxiv:1706.03762";

/** `uuid4().hex[:16]` (`src/api/sessions.py::create_session`). */
const SESSION_URL = /\/learn\/sessions\/[0-9a-f]{16}$/;

/**
 * The tutor's mock feedback, verbatim from `src/agents/tutor.py:248`.
 *
 * Asserted because it is the shortest proof that the graph ran a tutor node
 * on this stack rather than the harness answering: no fixture in this tier
 * contains it, and it only exists once `POST /turn` has resumed the run.
 */
const MOCK_TUTOR_FEEDBACK = "I recorded that as your own observation";

/** The learner's own words. They exist only in the checkpoint after a turn. */
const LEARNER_FIRST_REPLY =
  "I expect it to show why attention replaced recurrence for long-range structure.";
const LEARNER_CLOSING_REPLY =
  "The central move is that attention gives every position direct access to every other one.";

test.describe("WO-W13b — start, read, resume, close", () => {
  test(
    "a session started from the path view runs, survives a reload, and closes",
    { tag: ["@paid-path", "@slice"] },
    async ({ page }, testInfo) => {
      test.slow(); // the graph runs for real; three parks and two resumes.

      const paid = await interceptPaidPath(page, testInfo, {
        sessionMode: "mock-pass-through",
      });

      // ---- 1. Start, from the surface a reader is actually on. -----------
      await page.goto(PATH_URL, { waitUntil: "domcontentloaded" });
      const start = page.locator(`[data-start-session="${FIRST_RESOURCE}"]`);
      await expect(start).toBeVisible();
      await expect(start).not.toHaveAttribute("aria-disabled", "true");
      await start.click();

      // The id is the BACKEND's, not the harness's: a 16-hex id proves the
      // create was forwarded and answered by `create_session`, where the
      // fulfilled mode returns the literal `e2e-guided-session`.
      await page.waitForURL(SESSION_URL, { timeout: 60_000 });
      const sessionId = page.url().split("/").pop() ?? "";
      expect(sessionId).not.toBe(paid.acceptedSessionId);

      // ---- 2. Parked on the learner, because the SERVER says so. ---------
      const surface = page.locator("[data-session-state]");
      await expect(surface).toHaveAttribute(
        "data-session-state",
        "awaiting_learner",
        { timeout: 60_000 }
      );
      const composer = page.getByRole("textbox", { name: /Write your response/ });
      await expect(composer).toBeEnabled();

      // ---- 3. One turn, through the real composer. -----------------------
      await composer.fill(LEARNER_FIRST_REPLY);
      await page.getByRole("button", { name: "Continue the session" }).click();

      // The tutor's own words come back in the MARGIN, so the graph resumed,
      // ran a node, and the checkpoint was re-read. Located by the transcript
      // role rather than by text alone: the same sentence also appears as the
      // parked turn's feedback, and asserting on "somewhere on the page"
      // would pass on either.
      const tutorNotes = page.locator('li[data-role="tutor"]');
      await expect(
        tutorNotes.filter({ hasText: MOCK_TUTOR_FEEDBACK })
      ).toHaveCount(1, { timeout: 60_000 });
      await expect(surface).toHaveAttribute(
        "data-session-state",
        "awaiting_learner"
      );

      // ---- 4. Reload. Everything after this came back over HTTP. ---------
      await page.reload({ waitUntil: "domcontentloaded" });

      // The learner's own sentence lives ONLY in the LangGraph checkpoint —
      // `tutor_agent` writes it as a `HumanMessage` and `_transcript` reads
      // it back out of the snapshot (`src/api/sessions.py`). It is in no
      // fixture, in no SSE frame this page still holds, and in no job row.
      await expect(page.getByText(LEARNER_FIRST_REPLY)).toBeVisible({
        timeout: 60_000,
      });
      await expect(
        page.locator('li[data-role="tutor"]').filter({ hasText: MOCK_TUTOR_FEEDBACK })
      ).toHaveCount(1);
      await expect(
        page.getByText("Session restored from its durable checkpoint.")
      ).toBeVisible();
      await expect(
        page.getByRole("textbox", { name: /Write your response/ })
      ).toBeEnabled();

      // ---- 5. End the session, and read the honest close line. -----------
      await page
        .getByRole("textbox", { name: /Write your response/ })
        .fill(LEARNER_CLOSING_REPLY);
      await page.getByRole("button", { name: "End after this response" }).click();

      await expect(page.locator("[data-session-complete]")).toBeVisible({
        timeout: 60_000,
      });
      await expect(
        page.getByRole("heading", { name: "Session complete" })
      ).toBeVisible();
      await expect(surface).toHaveAttribute("data-session-state", "succeeded");
      // The close line is a statement about what happened, not a claim about
      // what the reader now knows.
      await expect(
        page.getByText(
          "This session advanced one guided reading and preserved your own explain-back as evidence."
        )
      ).toBeVisible();
      // ---- 6. The counts, and the outcome-side cost proof. ---------------
      paid.expectSessionExactly(
        1,
        2,
        "guided read, start to close, mock-mode pass-through"
      );
      expect(paid.researchPosts()).toBe(0);
      expect(paid.conversationPosts()).toBe(0);

      // The precondition said no model client would be constructed. This is
      // the finished run agreeing: `llm_calls` is the runner's own count off
      // the shared cost tracker (`src/api/runner.py`), read back through the
      // same proxy the browser uses.
      const detail = await page.evaluate(async (id: string) => {
        const response = await fetch(`/api/learn/sessions/${id}`);
        return (await response.json()) as {
          status?: string;
          result?: string | null;
          llm_calls?: number | null;
          cost_usd?: number | null;
          transcript?: unknown[];
        };
      }, sessionId);
      expect(detail.status).toBe("succeeded");
      expect(detail.llm_calls, "a model call was made on the e2e stack").toBe(0);
      expect(detail.cost_usd ?? 0).toBe(0);
      // And the durable margin really does hold both sides of the exchange.
      expect((detail.transcript ?? []).length).toBeGreaterThanOrEqual(2);

      // ---- 7. RR-L09, on what the browser actually painted. --------------
      //
      // The copy gate proves no string in `web/lib/copy/` says these things.
      // This proves the rendered page does not either — the half a gate over
      // source strings cannot see, and the same check `ledger.spec.ts` makes
      // for `/learn/progress`.
      //
      // SCOPED TO THE WORDS THIS PRODUCT'S FRONT END CHOSE, and the exclusion
      // is a finding rather than a convenience: the session's own close
      // summary, `progress_update_agent`'s `draft_report`
      // (`src/agents/tutor.py:486`), ends "This is an activity record, not a
      // mastery score." It reaches `SessionDetail.result` and
      // `GuidedSessionView` renders it verbatim, which is RC-16/H11 working
      // as designed — a backend string is shown unedited or not at all.
      // It is also the exact construction WO-W14 removed from the dictionary,
      // one tier down: a denial plants the frame it rejects. Flagged for the
      // coordinator; unfixable from this card without editing WO-W03's agent.
      // Whitespace-collapsed on both sides before the subtraction: the
      // service's `result` carries real newlines and `innerText` renders it
      // as one wrapped paragraph, so a literal replace would silently remove
      // nothing and the assertion would look scoped while being global.
      const collapse = (text: string): string => text.replace(/\s+/g, " ").trim();
      const painted = await page.locator("body").innerText();
      const serviceClose = collapse(detail.result ?? "");
      expect(serviceClose, "the service published no close summary").not.toBe("");
      const ownWords = collapse(painted).replace(serviceClose, "");
      expect(ownWords, "the service's close summary was not subtracted").not.toContain(
        serviceClose
      );
      expect(
        ownWords,
        "a pedagogy scalar reached the rendered session surface"
      ).not.toMatch(/\bmaster(?:ed|y|s)?\b|\bstreaks?\b|\bxp\b|\bunlock(?:ed)?\b/i);
      // No percentage anywhere at all — not even in the service's own words.
      expect(painted).not.toMatch(/\d+\s*%/);
    }
  );

  test(
    "the start action refuses one entry without disturbing the others",
    { tag: ["@slice"] },
    async ({ page }) => {
      // The refusal arrives from the SERVICE, not from a prop: the create is
      // answered with the backend's own 404 body, and the surface maps it.
      // Fulfilling here rather than forwarding is the point — the refused
      // start must reach no graph at all.
      await page.route(
        (url) => url.pathname === "/api/learn/sessions",
        async (route) => {
          if (route.request().method() !== "POST") {
            await route.fallback();
            return;
          }
          await route.fulfill({
            status: 404,
            contentType: "application/json",
            body: JSON.stringify({ detail: "session_loop_disabled" }),
          });
        }
      );

      await page.goto(PATH_URL, { waitUntil: "domcontentloaded" });
      await page.locator(`[data-start-session="${FIRST_RESOURCE}"]`).click();

      const refusal = page.locator(`[data-start-refusal="${FIRST_RESOURCE}"]`);
      await expect(refusal).toBeVisible();
      await expect(refusal).toContainText("This session was not started");
      await expect(refusal).toContainText(
        "This deployment is not running guided sessions."
      );
      // Still on the path: a refused start navigates nowhere.
      await expect(page).toHaveURL(new RegExp(`${PATH_ID}$`));
      // And the other entries are untouched.
      await expect(page.locator("[data-start-session]")).toHaveCount(3);
      await expect(page.locator("[data-start-refusal]")).toHaveCount(1);
    }
  );
});
