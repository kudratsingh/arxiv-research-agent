// MSW request handlers backed by the recorded fixtures in
// `web/contract/fixtures/` (04-ARCHITECTURE.md §3.3, §7.1 "Integration").
//
// Nothing here invents a response body. Every handler reads a checked-in
// recording — status, statusText, headers and body — and replays it verbatim,
// so an integration test and the contract drift checks in
// `web/tests/contract/fixtures.test.ts` are looking at the same bytes.
//
// **`POST /research` has no handler, deliberately.** It is the one
// non-idempotent, potentially billable call on the surface (MUST-KEEP #3,
// R-01), and the fixtures record none. With `onUnhandledRequest: "error"` —
// which `setupMswServer()` always passes — a test that submits a job fails
// loudly at the interceptor instead of silently passing. That absence IS the
// cost gate at this tier.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { http, HttpResponse, type RequestHandler } from "msw";

import { API_BASE } from "@/lib/api";

/** Vitest runs from `web/`, where its config lives. */
export const FIXTURE_DIR = join(process.cwd(), "contract", "fixtures");

/** The `x-recording` header key every fixture opens with. */
export interface FixtureRecording {
  note: string;
  case: string;
  commit: string;
  request: string;
  transport: string;
  stack: string;
  authored: boolean;
  authored_reason?: string;
  volatile?: string;
}

export interface Fixture {
  name: string;
  recording: FixtureRecording;
  status: number;
  statusText: string;
  headers: Record<string, string>;
  body: unknown;
}

/** Fixture names on disk, sorted. */
export function listFixtures(): string[] {
  return readdirSync(FIXTURE_DIR)
    .filter((file) => file.endsWith(".json"))
    .map((file) => file.replace(/\.json$/, ""))
    .sort();
}

export function loadFixture(name: string): Fixture {
  const parsed = JSON.parse(
    readFileSync(join(FIXTURE_DIR, `${name}.json`), "utf8")
  ) as Record<string, unknown>;
  return {
    name,
    recording: parsed["x-recording"] as FixtureRecording,
    status: parsed.status as number,
    statusText: parsed.statusText as string,
    headers: parsed.headers as Record<string, string>,
    body: parsed.body,
  };
}

/**
 * The fixture as it came off the wire: status, statusText, headers, body.
 *
 * Built from the raw JSON rather than `HttpResponse.json`, because the
 * recordings carry their own `content-type` (and `www-authenticate`,
 * `retry-after`) and replaying them verbatim is the whole point.
 */
export function fixtureResponse(fixture: Fixture): Response {
  return new HttpResponse(JSON.stringify(fixture.body), {
    status: fixture.status,
    statusText: fixture.statusText,
    headers: fixture.headers,
  });
}

/**
 * Job fixtures keyed by the `job_id` inside them.
 *
 * Derived from the recordings rather than hard-coded, so renaming a seeded
 * job in `web/contract/record.sh` cannot leave a stale map behind.
 */
export const JOB_FIXTURES_BY_ID: Record<string, Fixture> = Object.fromEntries(
  listFixtures()
    .filter((name) => name.startsWith("job."))
    .map((name) => loadFixture(name))
    .map((fixture) => [
      String((fixture.body as { job_id?: string }).job_id),
      fixture,
    ])
);

/** Serve one recorded fixture at one route. */
export function fixtureHandler(
  method: "get" | "post" | "put" | "delete" | "patch",
  path: string,
  name: string
): RequestHandler {
  const fixture = loadFixture(name);
  return http[method](path, () => fixtureResponse(fixture));
}

/**
 * The read-only happy path: five job states, the conversation list, and one
 * conversation detail. An unrecognised job id gets the recorded 404 — the
 * same answer the backend gives for "missing" and for "someone else's"
 * (`routes.py:59-84`).
 */
export const handlers: RequestHandler[] = [
  http.get(`${API_BASE}/research/:jobId`, ({ params }) => {
    const fixture = JOB_FIXTURES_BY_ID[String(params.jobId)];
    return fixtureResponse(fixture ?? loadFixture("error.404"));
  }),
  http.get(`${API_BASE}/conversations`, () =>
    fixtureResponse(loadFixture("conversations.list"))
  ),
  http.get(`${API_BASE}/conversations/:conversationId`, () =>
    fixtureResponse(loadFixture("conversations.detail"))
  ),
];

/**
 * Override a route with one of the seven recorded error envelopes.
 *
 * ```ts
 * server.use(errorFixture("error.429", "get", `${API_BASE}/conversations`));
 * ```
 */
export function errorFixture(
  name:
    | "error.401"
    | "error.404"
    | "error.409"
    | "error.422"
    | "error.429"
    | "error.502"
    | "error.503",
  method: "get" | "post" | "put" | "delete" | "patch",
  path: string
): RequestHandler {
  return fixtureHandler(method, path, name);
}
