/**
 * WO-W17 criteria 2 and 3 — two pilots on one stack, through the real edge.
 *
 * WHAT IS REAL HERE. Everything. Each browser context authenticates against
 * the committed production edge (`deploy/pilot/Caddyfile`, mounted unmodified
 * by `e2e/support/compose.pilot.yml`) with its own `basic_auth` credential;
 * Caddy sets `X-Pilot-User` from the username it authenticated;
 * `web/lib/server/pilot.ts` verifies the edge secret and maps the username to
 * that pilot's API key; the proxy injects it; FastAPI resolves it to a
 * `key_id`; ADR 0036 scopes every row to that `key_id`. Nothing on that path
 * is stubbed, intercepted or faked. The seeded rows
 * (`e2e/fixtures/seed.sh`, the WO-W17 block) are written behind the API, so
 * no model is contacted by the setup either.
 *
 * THE ASSERTION IS SYMMETRIC, ON PURPOSE. Each pilot sees their own row AND
 * does not see the other's. A test that checked only the first half would
 * pass against a stack that showed everything to everyone, which is exactly
 * the failure this card exists to make impossible.
 *
 * THE TOPOLOGY GUARD IS TESTED WHERE IT IS ACTUALLY EXPOSED. The pilot
 * overlay keeps `web` published on loopback — the condition MT-01's threat T6
 * names as the dangerous one, and the condition that is TRUE of base compose
 * and false of the production overlay. So the spoof test posts a forged
 * `X-Pilot-User` straight at the web container, bypassing the edge, which is
 * the attack the guard exists for. A stack that hid the port would make the
 * guard untestable and this test vacuous.
 *
 * SKIPPED WITHOUT `E2E_PILOT=1`, AND THAT IS THE HONEST STATE IN CI. The
 * `web-e2e` job brings up the ordinary two-file stack, and no Phase W card
 * edits a workflow (05-WEDGE-WORK-ORDERS.md §5.4). Under the ordinary stack
 * there is no edge, one principal, and `ARXIV_API_KEY` set — so these
 * assertions have nothing to run against and say so rather than passing
 * vacuously. Run locally with the three commands in
 * `web/playwright.pilot.config.ts`.
 */

import { expect, test } from "@playwright/test";
import type { APIRequestContext, Browser } from "@playwright/test";

import {
  E2E_PILOTS,
  E2E_PILOT_ENABLED,
  E2E_PILOT_EDGE_SECRET,
  E2E_BASE_URL,
} from "./support/env";

/**
 * One pilot, structurally.
 *
 * NOT `(typeof E2E_PILOTS)["a"]`. `E2E_PILOTS` is `as const`, so that alias
 * would be the literal type of pilot A and pilot B would not satisfy it —
 * every helper below takes both.
 */
interface Pilot {
  readonly user: string;
  readonly password: string;
  readonly apiKey: string;
  readonly conversation: string;
  readonly session: string;
}

/** A browser context that authenticates at the edge as one pilot. */
async function contextFor(browser: Browser, pilot: Pilot) {
  return browser.newContext({
    httpCredentials: { username: pilot.user, password: pilot.password },
  });
}

/** Every `/api` surface criterion 3 names, read as one pilot. */
async function readAll(api: APIRequestContext, pilot: Pilot, other: Pilot) {
  return {
    threads: await api.get("/api/conversations"),
    ownThread: await api.get(`/api/conversations/${pilot.conversation}`),
    otherThread: await api.get(`/api/conversations/${other.conversation}`),
    profile: await api.get("/api/learn/profile"),
    ledger: await api.get("/api/learn/progress"),
    ownSession: await api.get(`/api/learn/sessions/${pilot.session}`),
    otherSession: await api.get(`/api/learn/sessions/${other.session}`),
  };
}

test.describe("WO-W17 pilot principals", { tag: ["@pilot"] }, () => {
  test.skip(
    !E2E_PILOT_ENABLED,
    "needs the pilot stack: E2E_PILOT=1 bash e2e/support/stack.sh up && seed, " +
      "then npx playwright test -c playwright.pilot.config.ts. The CI e2e job " +
      "brings up the ordinary two-file stack (no edge, one principal, " +
      "ARXIV_API_KEY set), where these assertions have nothing to run against.",
  );

  test("each pilot sees only their own threads, sessions, profile and ledger", async ({
    browser,
  }) => {
    const contexts = {
      a: await contextFor(browser, E2E_PILOTS.a),
      b: await contextFor(browser, E2E_PILOTS.b),
    };
    try {
      const seen = {
        a: await readAll(contexts.a.request, E2E_PILOTS.a, E2E_PILOTS.b),
        b: await readAll(contexts.b.request, E2E_PILOTS.b, E2E_PILOTS.a),
      };

      for (const [name, side] of Object.entries(seen)) {
        // Own rows: readable.
        expect(side.ownThread.status(), `${name} own thread`).toBe(200);
        expect(side.ownSession.status(), `${name} own session`).toBe(200);
        expect(side.profile.status(), `${name} own profile`).toBe(200);
        expect(side.ledger.status(), `${name} own ledger`).toBe(200);
        // The other pilot's rows: 404, not 403. ADR 0036's `_check_ownership`
        // does not confirm that somebody else's id exists.
        expect(side.otherThread.status(), `${name} other thread`).toBe(404);
        expect(side.otherSession.status(), `${name} other session`).toBe(404);
      }

      // The thread LIST is where a scoping bug shows up as a leak rather than
      // as a 404, so it is checked by content and in both directions.
      const listA = await seen.a.threads.text();
      const listB = await seen.b.threads.text();
      expect(listA).toContain(E2E_PILOTS.a.conversation);
      expect(listA).not.toContain(E2E_PILOTS.b.conversation);
      expect(listB).toContain(E2E_PILOTS.b.conversation);
      expect(listB).not.toContain(E2E_PILOTS.a.conversation);
      // …and neither of them sees the third principal's `baseline-*` rows,
      // which the seed writes under `E2E_PRINCIPAL`.
      expect(listA).not.toContain("baseline-populated");
      expect(listB).not.toContain("baseline-populated");

      // Profile and ledger are per person, and the two differ in a value a
      // leak would show. `academic_level` is seeded `grad` for A and
      // `undergrad` for B.
      const profileA = await seen.a.profile.json();
      const profileB = await seen.b.profile.json();
      expect(profileA["academic_level"]).toBe("grad");
      expect(profileB["academic_level"]).toBe("undergrad");
      const ledgerA = await seen.a.ledger.text();
      const ledgerB = await seen.b.ledger.text();
      expect(ledgerA).toContain("baseline-pilot-a-event");
      expect(ledgerA).not.toContain("baseline-pilot-b-event");
      expect(ledgerB).toContain("baseline-pilot-b-event");
      expect(ledgerB).not.toContain("baseline-pilot-a-event");

      // And the same property observed through the rendered web tier rather
      // than through the API, which is what "through the web tier" means.
      const page = await contexts.a.newPage();
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Pilot A private thread")).toBeVisible();
      await expect(page.getByText("Pilot B private thread")).toHaveCount(0);
    } finally {
      await contexts.a.close();
      await contexts.b.close();
    }
  });

  test("no credential reaches the browser on any pilot page", async ({
    browser,
  }) => {
    const context = await contextFor(browser, E2E_PILOTS.a);
    try {
      const page = await context.newPage();
      const bodies: string[] = [];
      page.on("response", (response) => {
        void response
          .text()
          .then((body) => bodies.push(body))
          .catch(() => undefined);
      });
      await page.goto("/", { waitUntil: "networkidle" });
      const everything = `${bodies.join("\n")}\n${await page.content()}`;
      for (const secret of [
        E2E_PILOTS.a.apiKey,
        E2E_PILOTS.b.apiKey,
        E2E_PILOT_EDGE_SECRET,
        E2E_PILOTS.a.password,
      ]) {
        expect(everything, "a credential reached the browser").not.toContain(
          secret,
        );
      }
    } finally {
      await context.close();
    }
  });

  test("a forged username that did not come through the edge is refused", async ({
    playwright,
  }) => {
    // Straight at the `web` container on loopback — no edge, no basic auth,
    // and therefore no `X-Pilot-Edge-Key`. This is the request the topology
    // guard exists for, and the port it arrives on is the one base compose
    // publishes by default.
    const direct = await playwright.request.newContext({
      baseURL: E2E_BASE_URL,
    });
    try {
      const spoofed = await direct.get("/api/conversations", {
        headers: { "x-pilot-user": E2E_PILOTS.a.user },
      });
      expect(spoofed.status(), "a spoofed username was accepted").toBe(503);
      expect(await spoofed.text()).toContain("pilot_principal_unresolved");

      // A guessed edge key is refused for the same reason a missing one is.
      const guessed = await direct.get("/api/conversations", {
        headers: {
          "x-pilot-user": E2E_PILOTS.a.user,
          "x-pilot-edge-key": `${E2E_PILOT_EDGE_SECRET}x`,
        },
      });
      expect(guessed.status(), "a wrong edge key was accepted").toBe(503);

      // An unknown username WITH the right edge key still resolves to no
      // principal — failing closed rather than to the shared key.
      const unknown = await direct.get("/api/conversations", {
        headers: {
          "x-pilot-user": "pilot-nobody",
          "x-pilot-edge-key": E2E_PILOT_EDGE_SECRET,
        },
      });
      expect(unknown.status(), "an unknown username was accepted").toBe(503);

      // The control: with the right edge key AND a mapped username, the same
      // container answers. Without this line the three assertions above would
      // pass against a stack that 503s everything.
      const allowed = await direct.get("/api/conversations", {
        headers: {
          "x-pilot-user": E2E_PILOTS.a.user,
          "x-pilot-edge-key": E2E_PILOT_EDGE_SECRET,
        },
      });
      expect(allowed.status(), "the control request was refused").toBe(200);
      expect(await allowed.text()).toContain(E2E_PILOTS.a.conversation);
    } finally {
      await direct.dispose();
    }
  });
});
