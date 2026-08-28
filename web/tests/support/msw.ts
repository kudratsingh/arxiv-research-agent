// The integration tier's request layer (04-ARCHITECTURE.md §7.1).
//
// One `setupServer` for the whole suite, opted into per file by
// `setupMswServer()`. It is NOT started globally: a dozen existing tests
// install their own `globalThis.fetch` double, and hijacking fetch underneath
// them would change what they prove.
//
// `onUnhandledRequest: "error"` is not a tunable. A request nobody wrote a
// handler for is a test that has silently stopped exercising the thing it
// claims to, and the only useful outcome is a failure. It is also what keeps
// `POST /research` — unhandled by design, see `handlers.ts` — from ever
// succeeding at this tier.

import { setupServer, type SetupServer } from "msw/node";
import type { RequestHandler } from "msw";
import { afterAll, afterEach, beforeAll } from "vitest";

import { handlers } from "./handlers";

/** The shared server. Prefer `setupMswServer()` over touching this. */
export const server: SetupServer = setupServer(...handlers);

/**
 * Wire the shared server into the calling test file.
 *
 * @param extra Handlers layered over the recorded defaults for this file.
 *              They survive `resetHandlers`; per-test overrides go through
 *              `server.use(...)` and do not.
 */
export function setupMswServer(...extra: RequestHandler[]): SetupServer {
  beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
    if (extra.length > 0) server.use(...extra);
  });
  afterEach(() => {
    server.resetHandlers(...extra);
  });
  afterAll(() => {
    server.close();
  });
  return server;
}

export { handlers } from "./handlers";
export {
  errorFixture,
  fixtureHandler,
  fixtureResponse,
  listFixtures,
  loadFixture,
  JOB_FIXTURES_BY_ID,
  type Fixture,
  type FixtureRecording,
} from "./handlers";
