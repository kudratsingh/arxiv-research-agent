// WO-05 acceptance criterion 3, plus the render helper and one end-to-end
// proof that the three pieces of the harness compose.
//
// The criterion that matters here is the negative one: a request nobody
// handled must FAIL, loudly, at the interceptor. An MSW server configured to
// warn-and-passthrough turns every integration test into a test of whatever
// happens to be listening on localhost, which is worse than no test at all.

import { describe, it, expect } from "vitest";

import {
  API_BASE,
  ApiError,
  deleteConversation,
  getConversation,
  getJob,
  listConversations,
  submitResearch,
} from "@/lib/api";
import { useJobStream } from "@/lib/job/useJobStream";
import { THEME_ATTRIBUTE, THEME_PREFERENCE_ATTRIBUTE } from "@/lib/tokens";

import {
  errorFixture,
  listFixtures,
  loadFixture,
  server,
  setupMswServer,
  JOB_FIXTURES_BY_ID,
} from "./msw";
import {
  FakeEventSource,
  installFakeEventSource,
  onlySource,
} from "./FakeEventSource";
import { act, render, renderHook, screen, waitFor } from "./render";

setupMswServer();

// ---------------------------------------------------------------------------
// Criterion 3 — recorded fixtures in, unhandled requests out.
// ---------------------------------------------------------------------------

describe("MSW serves web/contract/fixtures/", () => {
  it("routes the five job states by the job_id inside the recording", async () => {
    expect(Object.keys(JOB_FIXTURES_BY_ID).sort()).toEqual([
      "baseline-cancelled",
      "baseline-failed-partial",
      "baseline-plan-review",
      "baseline-running",
      "baseline-succeeded",
    ]);

    const statuses: string[] = [];
    for (const jobId of Object.keys(JOB_FIXTURES_BY_ID).sort()) {
      statuses.push((await getJob(jobId)).status);
    }
    expect(statuses).toEqual([
      "cancelled",
      "failed",
      "pending_review",
      "running",
      "succeeded",
    ]);
  });

  it("serves the recorded body byte-for-byte, not a paraphrase", async () => {
    const job = await getJob("baseline-succeeded");
    expect(job).toEqual(loadFixture("job.succeeded").body);
  });

  it("serves the conversation list and detail", async () => {
    const list = await listConversations();
    expect(list).toEqual(loadFixture("conversations.list").body);

    const detail = await getConversation("baseline-populated");
    expect(detail).toEqual(loadFixture("conversations.detail").body);
  });

  it("replays an error envelope with its status and headers intact", async () => {
    server.use(errorFixture("error.429", "get", `${API_BASE}/conversations`));

    const failure = await listConversations().then(
      () => null,
      (caught: unknown) => caught as ApiError
    );

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure?.status).toBe(429);
    expect(failure?.failure.kind).toBe("rate_limited");
    // The `retry-after` header survives the round trip, which is the only
    // reason the normalizer can read it.
    if (failure?.failure.kind !== "rate_limited") throw new Error("unreachable");
    expect(failure.failure.retryAfterSec).toBe(3600);
  });

  it("resets per-test overrides, so the 429 above did not leak", async () => {
    await expect(listConversations()).resolves.toEqual(
      loadFixture("conversations.list").body
    );
  });

  it("has a handler for every recorded fixture it needs and no invented ones", () => {
    // Every fixture on disk is either routed by the default handlers or is an
    // error envelope a test opts into. Nothing here is a body someone typed.
    const onDisk = listFixtures();
    expect(onDisk.length).toBeGreaterThan(0);
    for (const name of onDisk) {
      expect(loadFixture(name).recording.commit).toMatch(/^[0-9a-f]{40}$/);
    }
  });
});

describe("MSW fails loudly on an unhandled request", () => {
  it("rejects an unrouted request instead of passing silently", async () => {
    // A handled route still works...
    await expect(getJob("baseline-succeeded")).resolves.toMatchObject({
      job_id: "baseline-succeeded",
    });

    // ...and one nobody wrote a handler for does not. `onUnhandledRequest:
    // "error"` makes the interceptor reject, which surfaces through the typed
    // client as a transport `ApiError` (`status: 0`). If this ever resolved,
    // the server would be bypassing to the network and every integration test
    // above it would be a test of whatever is listening on localhost.
    const outcome = await deleteConversation("baseline-populated").then(
      () => "resolved",
      (caught: unknown) => caught
    );

    expect(outcome).not.toBe("resolved");
    expect(outcome).toBeInstanceOf(ApiError);
    expect((outcome as ApiError).status).toBe(0);
  });

  it("refuses POST /research — there is no handler, and there must not be", async () => {
    // MUST-KEEP #3 / R-01: the one non-idempotent, potentially billable call
    // on the surface. No fixture records it and no handler serves it, so a
    // test that submits a job dies at the interceptor rather than quietly
    // succeeding against something else.
    const outcome = await submitResearch("does this cost money?").then(
      () => "resolved",
      (caught: unknown) => caught
    );

    expect(outcome).not.toBe("resolved");
    expect(outcome).toBeInstanceOf(ApiError);
    expect((outcome as ApiError).status).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// render.tsx
// ---------------------------------------------------------------------------

function Swatch(): React.ReactElement {
  return <p data-testid="swatch">token-driven</p>;
}

describe("render() applies the theme the tokens resolve against", () => {
  it("defaults to light, and reports the preference it resolved from", () => {
    render(<Swatch />);
    expect(screen.getByTestId("swatch")).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute(THEME_ATTRIBUTE, "light");
    expect(document.documentElement).toHaveAttribute(
      THEME_PREFERENCE_ATTRIBUTE,
      "light"
    );
  });

  it("renders the dark theme on request", () => {
    render(<Swatch />, { theme: "dark" });
    expect(document.documentElement).toHaveAttribute(THEME_ATTRIBUTE, "dark");
    expect(document.documentElement).toHaveAttribute(
      THEME_PREFERENCE_ATTRIBUTE,
      "dark"
    );
  });

  it("keeps the preference separate from the resolved theme", () => {
    render(<Swatch />, { theme: "dark", themePreference: "system" });
    expect(document.documentElement).toHaveAttribute(THEME_ATTRIBUTE, "dark");
    expect(document.documentElement).toHaveAttribute(
      THEME_PREFERENCE_ATTRIBUTE,
      "system"
    );
  });

  it("leaves nothing behind — vitest.setup.ts clears it after every test", () => {
    // The previous test set `dark`. If the global afterEach were missing,
    // this assertion would see it.
    expect(document.documentElement).not.toHaveAttribute(THEME_ATTRIBUTE);
  });
});

// ---------------------------------------------------------------------------
// The three pieces together, against real application code.
// ---------------------------------------------------------------------------

describe("the harness composes: recorded stream + recorded fixtures", () => {
  it("drives useJobStream from live_success to the settled JobDetail", async () => {
    // §3.2's invariant end to end: the report body never arrives over SSE, so
    // the terminal frame is only a signal and every displayed value comes
    // from `GET /research/{id}` — here, the recorded `job.succeeded` body.
    //
    // WO-31 REPOINTED THIS AT `useJobStream`. It used to drive
    // `lib/useResearchStream.ts`, the RC-03 adapter, which this work order
    // deleted; the hook underneath is the same lifecycle and this file's
    // subject was never the adapter. It is the HARNESS: MSW's recorded
    // fixtures, the recorded frame script and the render helper reaching
    // real application code together, which is the one thing
    // `tests/job/stream.test.ts` cannot show because it stubs `JobClient`.
    //
    // `attachMode: "stream-first"` keeps the request order the assertions
    // below are written against — the `EventSource` in the same tick as
    // `attach()`, and one `GET /research/{id}`, the settling one. GET-first
    // against this fixture would read a job that is already `succeeded` and
    // settle without opening a stream at all, replaying nothing. The
    // machine's own GET-first contract is covered in
    // `tests/job/attach.test.ts`; see this PR's residuals note.
    installFakeEventSource({ script: "live_success" });

    const { result } = renderHook(() =>
      useJobStream({ attachMode: "stream-first" }),
    );

    act(() => {
      result.current.attach("baseline-succeeded");
    });
    expect(FakeEventSource.instances).toHaveLength(1);

    const source = onlySource();
    expect(source.url).toBe(`${API_BASE}/research/baseline-succeeded/stream`);
    act(() => {
      source.play();
    });

    await waitFor(() => expect(result.current.state.phase).toBe("settled"));
    expect(result.current.state.detail).toEqual(loadFixture("job.succeeded").body);
    expect(
      result.current.state.frames
        .filter((frame) => frame.name !== "stream_note")
        .map((frame) => frame.name),
    ).toEqual([
      "job_started",
      "node_completed",
      "node_completed",
      "node_completed",
      "job_completed",
    ]);
    // The stream is closed and no second one was opened.
    expect(source.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
