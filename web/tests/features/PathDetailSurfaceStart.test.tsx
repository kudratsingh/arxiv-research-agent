/**
 * WO-W13b — the feature that turns a click on the path view into one guided
 * session and one navigation.
 *
 * WHAT IS REAL HERE. The typed client, the query layer, the copy mapper and
 * the pattern all run for real; only `fetch` and `next/navigation` are
 * replaced, because those are the two boundaries the browser owns. A test
 * that mocked `createLearnSession` would assert that this file calls a
 * function it was written to call, and would say nothing about the request
 * body — which is the half that a backend contract can actually reject.
 *
 * THE BODIES COME FROM THE RECORDED FIXTURE, so no assertion here can pass
 * against a path shape the API does not produce.
 */

import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryProvider } from "@/app/providers";
import {
  PathDetailSurface,
  SESSION_MINUTES_MAX,
  sessionCreateRequest,
} from "@/components/features/PathDetailSurface";
import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import type { LearnPathDetail } from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";

import { render, screen, user, waitFor } from "../support/render";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
}));

const path = detailFixture.body as LearnPathDetail;
const first = path.entries[0]!;
const PATH_ID = path.path_id;

const originalFetch = globalThis.fetch;

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Route by URL, not by call order: the surface issues the path read, the
 * progress read and (later) the create, and react-query decides when.
 */
function routeFetch(create: () => Response | Promise<Response>) {
  const creates: unknown[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : String(input);
    if (url.endsWith("/api/learn/sessions") && init?.method === "POST") {
      creates.push(JSON.parse(String(init.body ?? "{}")));
      return await create();
    }
    if (url.includes("/learn/paths/")) return response(path);
    if (url.includes("/learn/progress")) {
      return response({ detail: "learner_profile_not_found" }, 404);
    }
    return response({});
  }) as unknown as typeof fetch;
  return { creates };
}

function renderSurface() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryProvider client={client}>
      <PathDetailSurface pathId={PATH_ID} />
    </QueryProvider>
  );
}

/** Wait for the path to render, then return the first entry's start control. */
async function startControl(): Promise<HTMLElement> {
  const buttons = await screen.findAllByRole("button", {
    name: LEARN.startSession,
  });
  return buttons[0]!;
}

beforeEach(() => {
  push.mockClear();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("sessionCreateRequest", () => {
  it("sends the entry's identity and the path's declared minutes", () => {
    expect(sessionCreateRequest(PATH_ID, first)).toEqual({
      path_id: PATH_ID,
      resource_id: first.resource_id,
      available_minutes: first.est_minutes,
    });
  });

  it("omits the budget rather than inventing one the contract would reject", () => {
    // `available_minutes` is `ge=5, le=180`. A manifest may declare more, and
    // the honest answer is the endpoint's own fallback, not a clamped number.
    const long = { ...first, est_minutes: SESSION_MINUTES_MAX + 1 };
    expect(sessionCreateRequest(PATH_ID, long)).toEqual({
      path_id: PATH_ID,
      resource_id: first.resource_id,
    });
    const short = { ...first, est_minutes: 1 };
    expect(sessionCreateRequest(PATH_ID, short)).toEqual({
      path_id: PATH_ID,
      resource_id: first.resource_id,
    });
    // `available_minutes` is an `int`; a fractional manifest value is not one
    // and is not rounded into one here either.
    const fractional = { ...first, est_minutes: 12.5 };
    expect(sessionCreateRequest(PATH_ID, fractional)).toEqual({
      path_id: PATH_ID,
      resource_id: first.resource_id,
    });
  });

  it("sends no field the request schema does not declare", () => {
    // `SessionCreateRequest` is `extra="forbid"`: an unknown key is a 422,
    // so the body's key set is part of the contract rather than cosmetic.
    expect(Object.keys(sessionCreateRequest(PATH_ID, first)).sort()).toEqual([
      "available_minutes",
      "path_id",
      "resource_id",
    ]);
  });
});

describe("PathDetailSurface — starting a session", () => {
  it("issues exactly one create and routes to the session it minted", async () => {
    const { creates } = routeFetch(() =>
      response(
        {
          session_id: "9f3a2c1d4e5b6a70",
          status: "queued",
          status_url: "/learn/sessions/9f3a2c1d4e5b6a70",
          stream_url: "/research/9f3a2c1d4e5b6a70/stream",
        },
        202
      )
    );
    renderSurface();
    await user().click(await startControl());

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith("/learn/sessions/9f3a2c1d4e5b6a70");
    expect(creates).toEqual([
      {
        path_id: PATH_ID,
        resource_id: first.resource_id,
        available_minutes: first.est_minutes,
      },
    ]);
  });

  it("issues ONE create for a double click — the synchronous guard", async () => {
    // `POST /learn/sessions` has no idempotency key and starts a graph run,
    // so a second one is a second session that cannot be taken back. The
    // create is held open across both clicks; a `useState` guard would let
    // the second one through, because both clicks in one frame read the
    // pre-update value.
    let release = (): void => undefined;
    const held = new Promise<void>((resolve) => {
      release = () => resolve();
    });
    const { creates } = routeFetch(async () => {
      await held;
      return response(
        {
          session_id: "aaaaaaaaaaaaaaaa",
          status: "queued",
          status_url: "/learn/sessions/aaaaaaaaaaaaaaaa",
          stream_url: "/research/aaaaaaaaaaaaaaaa/stream",
        },
        202
      );
    });
    renderSurface();
    const control = await startControl();
    const click = user();
    await click.click(control);
    await click.click(control);
    await click.click(control);

    expect(creates).toHaveLength(1);
    release();
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(creates).toHaveLength(1);
  });

  it("marks the entry as starting while the create is outstanding", async () => {
    let release = (): void => undefined;
    const held = new Promise<void>((resolve) => {
      release = () => resolve();
    });
    routeFetch(async () => {
      await held;
      return response({ session_id: "b", status: "queued", status_url: "", stream_url: "" }, 202);
    });
    renderSurface();
    await user().click(await startControl());

    const started = await screen.findByRole("button", {
      name: LEARN.startingSession,
    });
    expect(started).toHaveAttribute("aria-busy", "true");
    release();
    await waitFor(() => expect(push).toHaveBeenCalled());
  });

  // Every refusal `POST /learn/sessions` can produce, driven through the real
  // client and the real normalizer rather than through a hand-made failure.
  const REFUSALS: Array<[string, number, string, string]> = [
    ["the session loop is off", 404, "session_loop_disabled", LEARN.startRefusedDisabled],
    ["no principal", 404, "session_loop_requires_auth", LEARN.startRefusedPrincipal],
    ["no learner profile", 404, "learner_profile_required", LEARN.startRefusedPrincipal],
    ["the path is not published", 404, "learn_path_not_found", LEARN.startRefusedContent],
    ["the entry is not served", 404, "learn_resource_not_found", LEARN.startRefusedContent],
    ["the content tree is invalid", 503, "learn_content_invalid", LEARN.startRefusedContent],
    [
      "the entry has no briefing companion",
      409,
      "briefing_companion_required",
      LEARN.startRefusedContent,
    ],
  ];

  for (const [name, status, detail, sentence] of REFUSALS) {
    it(`renders the mapped refusal when ${name}`, async () => {
      routeFetch(() => response({ detail }, status));
      renderSurface();
      await user().click(await startControl());

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(LEARN.startRefusedHeading);
      expect(alert).toHaveTextContent(sentence);
      expect(push).not.toHaveBeenCalled();
      // The wire code is not shown for a refusal that has a sentence.
      expect(screen.queryByText(LEARN.startRefusedDetail)).toBeNull();
    });
  }

  it("renders the rate-limit refusal without a wire code", async () => {
    routeFetch(
      () =>
        new Response(
          JSON.stringify({ detail: { error: "rate_limited", limit_per_hour: 20 } }),
          {
            status: 429,
            headers: { "content-type": "application/json", "retry-after": "60" },
          }
        )
    );
    renderSurface();
    await user().click(await startControl());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(LEARN.startRefusedRateLimited);
    expect(screen.queryByText(LEARN.startRefusedDetail)).toBeNull();
  });

  it("renders the unreachable refusal when the request never arrives", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : String(input);
      if (url.endsWith("/api/learn/sessions") && init?.method === "POST") {
        throw new TypeError("Failed to fetch");
      }
      if (url.includes("/learn/paths/")) return response(path);
      return response({ detail: "learner_profile_not_found" }, 404);
    }) as unknown as typeof fetch;
    renderSurface();
    await user().click(await startControl());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(LEARN.startRefusedUnreachable);
    expect(push).not.toHaveBeenCalled();
  });

  it("falls through to the generic sentence and quotes the service (RC-16)", async () => {
    routeFetch(() => response({ detail: "a_refusal_nobody_has_mapped" }, 409));
    renderSurface();
    await user().click(await startControl());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(LEARN.startRefusedGeneric);
    expect(alert).toHaveTextContent(LEARN.startRefusedDetail);
    expect(alert).toHaveTextContent("a_refusal_nobody_has_mapped");
  });

  it("refuses honestly when the failure is not an ApiError at all", async () => {
    // A 202 whose body is truncated: `json<SessionAccepted>` throws a
    // `SyntaxError`, which the normalizer never saw and which carries no
    // failure to map. The surface must still say something true rather than
    // leave the button spinning.
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : String(input);
      if (url.endsWith("/api/learn/sessions") && init?.method === "POST") {
        return new Response("{not json", {
          status: 202,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.includes("/learn/paths/")) return response(path);
      return response({ detail: "learner_profile_not_found" }, 404);
    }) as unknown as typeof fetch;
    renderSurface();
    await user().click(await startControl());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(LEARN.startRefusedGeneric);
    expect(screen.queryByText(LEARN.startRefusedDetail)).toBeNull();
    expect(push).not.toHaveBeenCalled();
    // And every control is armed again rather than stuck on "Starting".
    expect(
      await screen.findAllByRole("button", { name: LEARN.startSession })
    ).toHaveLength(path.entries.length);
    expect(
      screen.queryByRole("button", { name: LEARN.startingSession })
    ).toBeNull();
  });

  it("re-arms after a refusal, so a refused start is recoverable", async () => {
    let attempt = 0;
    const { creates } = routeFetch(() => {
      attempt += 1;
      return attempt === 1
        ? response({ detail: "learn_content_invalid" }, 503)
        : response(
            {
              session_id: "cccccccccccccccc",
              status: "queued",
              status_url: "",
              stream_url: "",
            },
            202
          );
    });
    renderSurface();
    await user().click(await startControl());
    await screen.findByRole("alert");

    await user().click(await startControl());
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(creates).toHaveLength(2);
    // The refusal clears when a new attempt begins rather than lingering
    // beside a session that has just started.
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
