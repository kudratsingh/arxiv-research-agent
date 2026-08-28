/**
 * WO-13 — `LandingComposer`, the wiring `web/app/page.tsx:33-40` does by
 * hand today.
 *
 * IT MIRRORS `web/tests/HomePage.test.tsx` DELIBERATELY. That file pins
 * the ADR 0053 hand-off against the hand-rolled page, and every one of its
 * assertions is reproduced here against the composer that replaces it —
 * the accepted `job_id` reaching the URL, exactly one `POST /research` and
 * one `POST /conversations` per click, a second click refused while the
 * first is in flight, the percent-encoding of both ids, and a failed
 * submit that does not navigate. The technique is unchanged too: `fetch`
 * is mocked rather than `lib/api`, so what is counted is the HTTP POST
 * that costs money and not a JavaScript function nobody is billed for.
 * When WO-20 composes the route against this component, the two files can
 * be diffed rather than argued about.
 *
 * On top of that it covers what the hand-rolled page cannot do at all:
 * H7's orphan thread, a thread-creation failure (which has no orphan to
 * offer), the manual resubmit that reuses the thread already paid for
 * rather than buying a second one, React StrictMode's double-invoked
 * mount, and criterion 10 asserted on the wire — the `POST /research`
 * body is read back and checked for the field 03 §8.4 forbids.
 *
 * THE PAGE ITSELF IS NOT WIRED IN THIS WORK ORDER. `npm run budgets` says
 * why: the composer stack is +10,333 B gzip on `/`, and `/` has 4,611 B of
 * headroom now that WO-08's shell is on the route. Measured both ways in
 * the PR body; the mount is WO-20's.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";

import {
  LandingComposer,
  handoffHref,
  threadHref,
} from "@/components/features/LandingComposer";
import { COMPOSER } from "@/lib/copy/composer";
import { FAILURE_COPY } from "@/lib/copy/errors";
import { LANDING } from "@/lib/copy/run";
import type { ConversationDetail } from "@/lib/api";
import { JobRunProvider } from "@/lib/job/provider";

import {
  installFakeEventSource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { render, screen, user, waitFor } from "../support/render";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
}));

// ---------------------------------------------------------------------------
// The wire.
// ---------------------------------------------------------------------------

const originalFetch = globalThis.fetch;

/** Every request the composer made, in order, as `METHOD path`. */
let calls: string[] = [];
/** Every request body, keyed the same way. */
let bodies: Array<{ key: string; body: unknown }> = [];

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const THREAD = {
  conversation_id: "conv-1",
  title: "untitled",
  created_at: 0,
  updated_at: 0,
  jobs: [],
};

type Answer = () => Response | Promise<Response>;

function installFetch(overrides: Record<string, Answer> = {}): void {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const apiPath = url.pathname.replace(/^\/api/, "") || "/";
    const key = `${method} ${apiPath}`;
    calls.push(key);
    if (typeof init?.body === "string") {
      bodies.push({ key, body: JSON.parse(init.body) as unknown });
    }
    const override = overrides[key];
    if (override) return override();
    if (key === "GET /conversations") return jsonResp([]);
    if (key === "POST /conversations") return jsonResp(THREAD);
    if (key === "POST /research") {
      return jsonResp({
        job_id: "job-1",
        status: "pending",
        status_url: "/research/job-1",
        stream_url: "/research/job-1/stream",
      });
    }
    if (key.startsWith("GET /research/")) {
      // The GET-first attach reads this the moment a submission is
      // accepted, and `detailSignature()` walks every field, so the stub
      // is a whole `JobDetail` rather than the two fields the test reads.
      return jsonResp({
        // The path segment is percent-encoded on the wire; the body is not.
        job_id: decodeURIComponent(key.slice("GET /research/".length)),
        status: "pending",
        result: null,
        error: null,
        error_type: null,
        cost_usd: null,
        llm_calls: null,
        iterations: null,
        quality_score: null,
        plan: null,
        created_at: 0,
        started_at: null,
        completed_at: null,
        elapsed_sec: null,
      });
    }
    throw new Error(`unexpected request: ${key}`);
  }) as unknown as typeof fetch;
}

function countOf(key: string): number {
  return calls.filter((entry) => entry === key).length;
}

beforeEach(() => {
  calls = [];
  bodies = [];
  push.mockClear();
  installFetch();
  // `submit` attaches to the accepted job, which opens a stream. jsdom has
  // no EventSource, so the stub stands in for the browser's.
  installFakeEventSource();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  uninstallFakeEventSource();
});

/** The composer, inside the one provider that owns `POST /research`. */
function mount(
  props: Parameters<typeof LandingComposer>[0] = {},
  provider: Partial<Parameters<typeof JobRunProvider>[0]> = {},
) {
  return render(
    <JobRunProvider {...provider}>
      <LandingComposer {...props} />
    </JobRunProvider>,
  );
}

function askButton(): HTMLElement {
  return screen.getByRole("button", {
    name: new RegExp(`^(${LANDING.submit}|${LANDING.submitPending})$`),
  });
}

async function ask(question = "retrieval augmented verification"): Promise<void> {
  const typist = user();
  await typist.type(screen.getByLabelText(LANDING.questionLabel), question);
  await typist.click(askButton());
}

// ---------------------------------------------------------------------------
// The hand-off (MUST-KEEP #1, ADR 0053) — mirrored from HomePage.test.tsx.
// ---------------------------------------------------------------------------

describe("the landing hand-off", () => {
  it("carries the accepted job_id into the run page URL", async () => {
    mount();
    await ask();

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith("/c/conv-1?job=job-1");
  });

  it("performs the two writes in order, once each", async () => {
    mount();
    await ask();

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(countOf("POST /conversations")).toBe(1);
    expect(countOf("POST /research")).toBe(1);
    expect(calls.indexOf("POST /conversations")).toBeLessThan(
      calls.indexOf("POST /research"),
    );
  });

  it("percent-encodes the ids it puts in the URL", async () => {
    installFetch({
      "POST /conversations": () =>
        jsonResp({ ...THREAD, conversation_id: "conv/1 2" }),
      "POST /research": () =>
        jsonResp({
          job_id: "job 1",
          status: "pending",
          status_url: "/research/job%201",
          stream_url: "/research/job%201/stream",
        }),
    });
    mount();
    await ask();

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith("/c/conv%2F1%202?job=job%201");
  });

  it("hands off at most once per accepted run", async () => {
    // WO-20 criterion 1 is "`?job=` is written at most once per job id", and
    // the hand-off here is an effect keyed on the machine's `jobId`. A
    // parent that passes an inline arrow re-runs that effect on every one
    // of its own renders with the same job still attached, so the guard has
    // to be a ref on the id rather than an empty dependency list.
    const first = vi.fn();
    const { rerender } = render(
      <JobRunProvider>
        <LandingComposer onHandoff={first} />
      </JobRunProvider>,
    );
    await ask();
    await waitFor(() => expect(first).toHaveBeenCalledTimes(1));

    const second = vi.fn();
    rerender(
      <JobRunProvider>
        <LandingComposer onHandoff={second} />
      </JobRunProvider>,
    );

    expect(second).not.toHaveBeenCalled();
    expect(first).toHaveBeenCalledTimes(1);
    expect(countOf("POST /research")).toBe(1);
  });

  it("builds both hrefs from the same encoder", () => {
    expect(handoffHref("conv/1 2", "job 1")).toBe("/c/conv%2F1%202?job=job%201");
    expect(threadHref("conv/1 2")).toBe("/c/conv%2F1%202");
  });

  it("refuses a second click while the first submission is in flight", async () => {
    let release = (): void => undefined;
    // A `POST /research` that does not answer until the test says so.
    const held = new Promise<Response>((resolve) => {
      release = () =>
        resolve(
          jsonResp({
            job_id: "job-1",
            status: "pending",
            status_url: "/research/job-1",
            stream_url: "/research/job-1/stream",
          }),
        );
    });
    installFetch({ "POST /research": () => held });

    mount();
    await ask();
    await waitFor(() => expect(countOf("POST /research")).toBe(1));

    const button = askButton();
    expect(button).toHaveTextContent(LANDING.submitPending);
    expect(button).toHaveAttribute("aria-busy", "true");
    await user().click(button);
    await user().click(button);
    expect(countOf("POST /research")).toBe(1);

    release();
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
  });

  it("reports a failed submit, keeps the question and does not navigate", async () => {
    installFetch({
      "POST /research": () => jsonResp({ detail: "rate limited" }, 429),
    });
    mount();
    await ask();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.rate_limited.sentence);
    expect(alert).toHaveTextContent(COMPOSER.noAutoRetry);
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByLabelText(LANDING.questionLabel)).toHaveValue(
      "retrieval augmented verification",
    );
    // Re-enabled, because there is no run to watch on the other page.
    expect(askButton()).not.toHaveAttribute("aria-disabled");
  });

  it("survives React StrictMode's double-invoked mount", async () => {
    render(
      <StrictMode>
        <JobRunProvider>
          <LandingComposer />
        </JobRunProvider>
      </StrictMode>,
    );
    // Mounting buys nothing: no effect on this route submits.
    expect(countOf("POST /research")).toBe(0);
    expect(countOf("POST /conversations")).toBe(0);

    await ask();
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(countOf("POST /research")).toBe(1);
    expect(countOf("POST /conversations")).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Criterion 10, on the wire.
// ---------------------------------------------------------------------------

describe("criterion 10 — the forbidden field never reaches the request", () => {
  it("sends only the query and the thread id", async () => {
    mount();
    await ask();
    await waitFor(() => expect(countOf("POST /research")).toBe(1));

    const submitted = bodies.find((entry) => entry.key === "POST /research");
    expect(submitted).toBeDefined();
    const body = (submitted as { body: Record<string, unknown> }).body;
    // The exhaustive form: two keys, and no third one of any name. The
    // field H12 forbids is spelled from parts for the same reason
    // `web/tests/api.test.ts` does it — that file's containment scan reads
    // this one.
    expect(Object.keys(body).sort()).toEqual(["conversation_id", "query"]);
    expect(body).not.toHaveProperty(["hitl", "bypass"].join("_"));
  });
});

// ---------------------------------------------------------------------------
// H7, and the two failures that are not the same failure.
// ---------------------------------------------------------------------------

describe("H7 — a submission that failed after the thread was created", () => {
  it("offers the empty thread", async () => {
    installFetch({
      "POST /research": () => jsonResp({ detail: "rate limited" }, 429),
    });
    mount();
    await ask();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(COMPOSER.orphanSentence);
    expect(
      screen.getByRole("link", { name: COMPOSER.orphanAction }),
    ).toHaveAttribute("href", threadHref("conv-1"));
  });

  it("offers nothing when the thread is what failed to exist", async () => {
    installFetch({
      "POST /conversations": () => jsonResp({ detail: "rate limited" }, 429),
    });
    mount();
    await ask();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.rate_limited.sentence);
    expect(screen.queryByRole("link", { name: COMPOSER.orphanAction })).toBeNull();
    // Nothing was submitted, so nothing was billed.
    expect(countOf("POST /research")).toBe(0);
    expect(push).not.toHaveBeenCalled();
  });

  it("a manual resubmit reuses the thread already paid for", async () => {
    let attempt = 0;
    installFetch({
      "POST /research": () => {
        attempt += 1;
        return attempt === 1
          ? jsonResp({ detail: "rate limited" }, 429)
          : jsonResp({
              job_id: "job-2",
              status: "pending",
              status_url: "/research/job-2",
              stream_url: "/research/job-2/stream",
            });
      },
    });
    mount();
    await ask();
    await screen.findByRole("alert");

    // The same single control is the manual resubmit (criterion 6).
    await user().click(askButton());
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));

    expect(push).toHaveBeenCalledWith("/c/conv-1?job=job-2");
    expect(countOf("POST /research")).toBe(2);
    // A landing submission spends two rate-limit slots; a resubmit must
    // spend one, and must not leave a second empty thread behind.
    expect(countOf("POST /conversations")).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// The two injection seams WO-20 uses.
// ---------------------------------------------------------------------------

describe("the composition seams", () => {
  it("takes an injected thread creator — WO-20 passes the mutation here", async () => {
    const createThread = vi.fn(
      async (): Promise<ConversationDetail> =>
        ({ ...THREAD, conversation_id: "conv-9" }) as ConversationDetail,
    );
    const onHandoff = vi.fn();
    mount({ createThread, onHandoff });
    await ask();

    await waitFor(() => expect(onHandoff).toHaveBeenCalledTimes(1));
    expect(createThread).toHaveBeenCalledTimes(1);
    // The default `POST /conversations` was not used.
    expect(countOf("POST /conversations")).toBe(0);
    expect(onHandoff).toHaveBeenCalledWith(handoffHref("conv-9", "job-1"));
    expect(push).not.toHaveBeenCalled();
  });

  it("refuses to submit at all while the service is unreachable", async () => {
    mount({
      unreachable: {
        kind: "upstream_unavailable",
        status: 502,
        message: "",
        raw: null,
      },
    });
    const typist = user();
    await typist.type(screen.getByLabelText(LANDING.questionLabel), "anything");
    await typist.click(askButton());

    expect(askButton()).toHaveAttribute("aria-disabled", "true");
    expect(countOf("POST /conversations")).toBe(0);
    expect(countOf("POST /research")).toBe(0);
  });

  it("renders a banner even when the throw could not be normalized", async () => {
    // The machine reports `submit_rejected` with `failure: null` when what
    // was thrown was not an `ApiError` — a bug in this bundle rather than
    // an answer from the server. The banner has to render anyway: a
    // failure with no sentence is indistinguishable on screen from a
    // submission that never happened.
    mount(
      { createThread: async () => ({ ...THREAD }) as ConversationDetail },
      {
        client: {
          submitResearch: () => Promise.reject(new Error("not an ApiError")),
        },
      },
    );

    const typist = user();
    await typist.type(screen.getByLabelText(LANDING.questionLabel), "anything");
    await typist.click(askButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      FAILURE_COPY.unknown.sentence,
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("a thread-creation throw that is not an ApiError still lands", async () => {
    mount({
      createThread: async () => {
        throw new Error("network is a lie");
      },
    });
    const typist = user();
    await typist.type(screen.getByLabelText(LANDING.questionLabel), "anything");
    await typist.click(askButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      FAILURE_COPY.unknown.sentence,
    );
    expect(countOf("POST /research")).toBe(0);
  });
});
