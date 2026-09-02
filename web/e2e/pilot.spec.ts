/**
 * WO-W17 criteria 2 and 3 — two pilots on one stack, through the real edge.
 *
 * WO-W17b ADDED THE HEADER'S HALF (its criterion 4). ADR 0063 shipped the
 * mapping with one thing it could not fix: the shell still called this a
 * shared workspace with no separate accounts, which is false here and was
 * recorded as a prerequisite to inviting anyone. Two tests below are about the
 * sentence rather than the credential — that each pilot's header names them
 * and not the other, and that a document route the topology guard refuses
 * renders "Principal not resolved" rather than the shared sentence. They run
 * against the same stack, the same edge and the same guard.
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

  /**
   * WO-W17b criterion 4 — the header says whose workspace this is.
   *
   * THE ASSERTION IS SYMMETRIC FOR THE SAME REASON THE ONE ABOVE IS. Each
   * pilot's header names them and does NOT name the other, in the same run, so
   * a shell that printed a build-time constant or served a cached document
   * fails rather than passing on the half that happens to be right.
   *
   * IT RUNS ON BOTH ROUTE GROUPS. `app/(workspace)/layout.tsx` and
   * `app/(learn)/layout.tsx` resolve the descriptor independently, through the
   * same function; a change to one of them that missed the other is a thing
   * this catches and no unit test can.
   *
   * THE `shared` SENTENCE IS ASSERTED ABSENT, BY ITS TEXT. "There are no
   * separate accounts" is what ADR 0063 recorded as a blocking issue: false
   * under this overlay, and shown to the people the separation is for. Its
   * absence here is what this work order is.
   */
  test("the identity slot names the pilot the edge authenticated, and only them", async ({
    browser,
  }) => {
    const contexts = {
      a: await contextFor(browser, E2E_PILOTS.a),
      b: await contextFor(browser, E2E_PILOTS.b),
    };
    try {
      for (const [name, side, other] of [
        ["a", E2E_PILOTS.a, E2E_PILOTS.b],
        ["b", E2E_PILOTS.b, E2E_PILOTS.a],
      ] as const) {
        const page = await contexts[name].newPage();
        for (const route of ["/", "/learn"]) {
          await page.goto(route, { waitUntil: "domcontentloaded" });
          const slot = page.locator("[data-workspace-identity]");
          await expect(slot, `${name} ${route}`).toHaveAttribute(
            "data-workspace-identity",
            "pilot",
          );
          await expect(slot, `${name} ${route}`).toContainText("Pilot workspace");
          await expect(slot, `${name} ${route}`).toContainText(side.user);
          await expect(slot, `${name} ${route}`).not.toContainText(other.user);
          await expect(slot, `${name} ${route}`).not.toContainText(
            "There are no separate accounts",
          );
          await expect(
            page.getByText("Shared workspace"),
            `${name} ${route}`,
          ).toHaveCount(0);
        }
        await page.close();
      }
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

  /**
   * WO-W17b criterion 4, second half — what the PAGE says when the guard fires.
   *
   * WHAT THIS PROVES AND WHAT IT DOES NOT. The three assertions above are about
   * `/api`, where the answer is a 503. This one is about a DOCUMENT route, where
   * there is no 503 to give: `app/(workspace)/layout.tsx` must render the page,
   * because a layout that threw would replace it with an error boundary and say
   * nothing at all. So the same forged request that gets a 503 from the proxy
   * gets a 200 from `/` — carrying "Principal not resolved", carrying neither
   * the shared sentence nor any username, and with a rail that is about to be
   * refused by the API. That is exactly the state a stranger on the loopback
   * port sees, and the header is the only part of it that says why.
   *
   * IT ALSO PROVES THE LAYOUT READS THE SAME HEADERS THE PROXY DOES, because the
   * last request forges the *complete* set — edge key and username — and the
   * header names that pilot. Without that control the three refusals above
   * would pass against a shell that always said "Principal not resolved".
   */
  test("a document route refused by the topology guard says so in the header", async ({
    playwright,
  }) => {
    const direct = await playwright.request.newContext({ baseURL: E2E_BASE_URL });
    try {
      for (const [label, headers] of [
        ["no headers at all", {}],
        ["a forged username with no edge key", { "x-pilot-user": E2E_PILOTS.a.user }],
        [
          "a forged username with a guessed edge key",
          {
            "x-pilot-user": E2E_PILOTS.a.user,
            "x-pilot-edge-key": `${E2E_PILOT_EDGE_SECRET}x`,
          },
        ],
        [
          "a username nobody was issued, from the real edge key",
          {
            "x-pilot-user": "pilot-nobody",
            "x-pilot-edge-key": E2E_PILOT_EDGE_SECRET,
          },
        ],
      ] as const) {
        const page = await direct.get("/", { headers });
        expect(page.status(), label).toBe(200);
        const html = await page.text();
        expect(html, label).toContain("Principal not resolved");
        // Never the sentence that is false here, and never a name.
        expect(html, label).not.toContain("Shared workspace");
        expect(html, label).not.toContain("There are no separate accounts");
        expect(html, label).not.toContain(E2E_PILOTS.a.user);
        expect(html, label).not.toContain(E2E_PILOTS.b.user);
        // No fault, no key material, no configuration.
        for (const leak of [
          "untrusted_topology",
          "unknown_username",
          E2E_PILOTS.a.apiKey,
          E2E_PILOTS.b.apiKey,
          E2E_PILOT_EDGE_SECRET,
          "PILOT_PRINCIPAL_MAP",
        ]) {
          expect(html, `${label}: ${leak}`).not.toContain(leak);
        }
      }

      // THE CONTROL. Same container, same route, the complete forged header
      // set — which is what the edge itself sends — and the header names the
      // pilot. Without this the four refusals above would pass against a shell
      // that had been hardcoded to the unresolved sentence.
      const asPilot = await direct.get("/", {
        headers: {
          "x-pilot-user": E2E_PILOTS.a.user,
          "x-pilot-edge-key": E2E_PILOT_EDGE_SECRET,
        },
      });
      expect(asPilot.status(), "the control request was refused").toBe(200);
      const controlHtml = await asPilot.text();
      expect(controlHtml).toContain("Pilot workspace");
      expect(controlHtml).toContain(E2E_PILOTS.a.user);
      expect(controlHtml).not.toContain("Principal not resolved");
      expect(controlHtml).not.toContain(E2E_PILOTS.a.apiKey);
    } finally {
      await direct.dispose();
    }
  });
});
