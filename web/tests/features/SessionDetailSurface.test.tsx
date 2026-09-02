/**
 * WO-W13 — the feature that wires the session view to the API and the shared
 * job machine.
 *
 * WHAT IS REAL AND WHAT IS NOT. The machine, `useJobStream`, the typed client
 * and the query layer all run for real; only the two boundaries the browser
 * owns are replaced — `fetch` and `EventSource`. That is deliberate: the
 * behaviours worth testing here are exactly the ones that live *between*
 * those two, and a test that mocked `useJobStream` would assert that this
 * file calls a function it was written to call.
 *
 * The `SessionDetail` bodies come from the recorded fixture, so no test can
 * pass against a shape the API does not produce.
 */

import { QueryClient } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryProvider } from "@/app/providers";
import { SessionDetailSurface } from "@/components/features/SessionDetailSurface";
import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import sessionFixture from "@/contract/fixtures/learn.session.awaiting.json";
import { LEARN } from "@/lib/copy/learn";
import type { LearnPathDetail, SessionDetail } from "@/lib/api";

import {
  installFakeEventSource,
  onlySource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { fireEvent, render, screen, waitFor } from "../support/render";

const SESSION_ID = "baseline-guided-session";
const awaiting = sessionFixture.body as SessionDetail;
const path = detailFixture.body as LearnPathDetail;

const originalFetch = globalThis.fetch;

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Route by URL rather than by call order.
 *
 * The surface issues three different reads (the session, the path, the
 * renderer's chunk) and re-issues the first one whenever the machine
 * refreshes, so a queue of responses would depend on an ordering this file
 * has no business pinning.
 */
function routeFetch(handlers: {
  session: () => Response | Promise<Response>;
  path?: () => Response | Promise<Response>;
  turn?: (body: unknown) => Response | Promise<Response>;
}) {
  const turns: unknown[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : String(input);
    if (url.endsWith("/turn")) {
      const body: unknown = JSON.parse(String(init?.body ?? "{}"));
      turns.push(body);
      return handlers.turn === undefined
        ? response({ session_id: SESSION_ID, status: "awaiting_learner", accepted: true })
        : await handlers.turn(body);
    }
    if (url.includes("/learn/sessions/")) return handlers.session();
    if (url.includes("/learn/paths/")) {
      return handlers.path === undefined ? response(path) : await handlers.path();
    }
    return response({});
  }) as unknown as typeof fetch;
  return { turns };
}

function renderSurface() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryProvider client={client}>
      <SessionDetailSurface sessionId={SESSION_ID} />
    </QueryProvider>
  );
}

beforeEach(() => {
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
  globalThis.fetch = originalFetch;
});

describe("the guided session surface", () => {
  it("says it is reattaching rather than showing an empty session", () => {
    routeFetch({ session: () => new Promise<Response>(() => undefined) as never });
    renderSurface();
    expect(screen.getByText(LEARN.sessionLoading)).toHaveAttribute(
      "aria-busy",
      "true"
    );
  });

  it("renders the parked turn and the paper the session is about", async () => {
    routeFetch({ session: () => response(awaiting) });
    renderSurface();

    await screen.findByRole("textbox", { name: /Write your response/ });
    // The entry is matched by `resource_id` against the path, so the arXiv
    // link is the session's paper rather than the path's first one.
    expect(
      await screen.findByRole("link", { name: LEARN.openPaper })
    ).toHaveAttribute("href", path.entries[0]!.canonical_url);
  });

  it("announces a restored session only when there is something restored", async () => {
    // A fresh check-in has an empty margin and turn 1: nothing was restored,
    // so claiming a restore would be a small lie about durable state.
    routeFetch({ session: () => response(awaiting) });
    const { unmount } = renderSurface();
    await screen.findByRole("textbox", { name: /Write your response/ });
    expect(screen.queryByText(LEARN.resumed)).toBeNull();
    unmount();

    routeFetch({
      session: () =>
        response({
          ...awaiting,
          transcript: [{ role: "learner", text: "My saved note" }],
        }),
    });
    renderSurface();
    expect(await screen.findByText(LEARN.resumed)).toBeVisible();
    expect(screen.getByText("My saved note")).toBeVisible();
  });

  it("submits one turn and refuses a second while the first is in flight", async () => {
    const user = userEvent.setup();
    const { turns } = routeFetch({ session: () => response(awaiting) });
    renderSurface();

    const composer = await screen.findByRole("textbox", {
      name: /Write your response/,
    });
    await user.type(composer, "Attention removes the recurrence bottleneck.");
    const submit = screen.getByRole("button", { name: LEARN.submitTurn });
    await user.click(submit);
    await user.click(submit);

    // `POST /learn/sessions/{id}/turn` resumes a graph that calls a model and
    // has no idempotency key, so the guard is not a nicety.
    await waitFor(() => expect(turns).toHaveLength(1));
    expect(turns[0]).toEqual({
      message: "Attention removes the recurrence bottleneck.",
      end_session: false,
    });
  });

  it("carries the end-session intent on the turn it is submitted with", async () => {
    const user = userEvent.setup();
    const { turns } = routeFetch({ session: () => response(awaiting) });
    renderSurface();

    const composer = await screen.findByRole("textbox", {
      name: /Write your response/,
    });
    await user.type(composer, "I would like to stop here.");
    await user.click(screen.getByRole("button", { name: LEARN.endSession }));

    await waitFor(() => expect(turns).toHaveLength(1));
    expect(turns[0]).toEqual({
      message: "I would like to stop here.",
      end_session: true,
    });
  });

  it("reports a refused turn without losing what the learner wrote", async () => {
    const user = userEvent.setup();
    routeFetch({
      session: () => response(awaiting),
      turn: () =>
        response({ detail: "session_not_awaiting_learner (status=running)" }, 409),
    });
    renderSurface();

    const composer = await screen.findByRole("textbox", {
      name: /Write your response/,
    });
    await user.type(composer, "A reply the server will not take yet.");
    await user.click(screen.getByRole("button", { name: LEARN.submitTurn }));

    // The composer keeps the text: a rejected write must never silently eat
    // the learner's own words.
    await waitFor(() =>
      expect(composer).toHaveValue("A reply the server will not take yet.")
    );
    expect(screen.getByRole("button", { name: LEARN.submitTurn })).toBeEnabled();
  });

  it("re-reads the session when the stream says a turn is ready", async () => {
    let body: SessionDetail = { ...awaiting, turn: null, status: "running" };
    routeFetch({ session: () => response(body) });
    renderSurface();

    expect(await screen.findByText(LEARN.workingHeading)).toBeVisible();

    // `turn_ready` is a pause SIGNAL. The surface re-reads the durable
    // snapshot rather than rendering the frame's payload, which is what makes
    // a live turn and a reloaded one identical.
    body = awaiting;
    onlySource().emit("turn_ready", {
      job_id: SESSION_ID,
      turn: { turn_number: 1, kind: "reflection" },
    });

    expect(
      await screen.findByRole("textbox", { name: /Write your response/ })
    ).toBeEnabled();
  });

  it("unlocks the composer when the server publishes the next turn", async () => {
    const user = userEvent.setup();
    let body: SessionDetail = awaiting;
    const { turns } = routeFetch({ session: () => response(body) });
    renderSurface();

    const composer = await screen.findByRole("textbox", {
      name: /Write your response/,
    });
    await user.type(composer, "My first answer.");
    await user.click(screen.getByRole("button", { name: LEARN.submitTurn }));
    await waitFor(() => expect(turns).toHaveLength(1));

    // The graph advanced: the parked turn is a DIFFERENT turn now. That, and
    // not the write's own 200, is what clears the in-flight lock — the write
    // only says the reply was accepted, while the snapshot says the session
    // actually moved.
    body = {
      ...awaiting,
      turn: { ...(awaiting.turn as object), turn_number: 2, kind: "guided_question" },
    };
    onlySource().emit("turn_ready", { job_id: SESSION_ID, turn: { turn_number: 2 } });

    // Wait on the BUSY flag, not on the empty composer: the composer is
    // cleared the moment the write resolves, which is before the refreshed
    // snapshot has said the session moved. Only the second of those unlocks
    // the surface, and it is the one under test.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: LEARN.submitTurn })
      ).not.toHaveAttribute("aria-busy")
    );

    const next = screen.getByRole("textbox", { name: /Write your response/ });
    expect(next).toHaveValue("");
    await user.type(next, "My second answer.");
    await user.click(screen.getByRole("button", { name: LEARN.submitTurn }));
    await waitFor(() => expect(turns).toHaveLength(2));
  });

  it("refuses a second click that lands before React has re-rendered", async () => {
    const user = userEvent.setup();
    const { turns } = routeFetch({ session: () => response(awaiting) });
    renderSurface();

    const composer = await screen.findByRole("textbox", {
      name: /Write your response/,
    });
    await user.type(composer, "One reply, however many clicks.");

    // `fireEvent` twice in the same tick, deliberately: the primitive refuses
    // clicks once `busy` renders, but the SECOND half of a real fast double
    // click can land before React has re-rendered at all. The surface's own
    // synchronous ref guard is the one that catches that, and it is the only
    // guard that can — so it gets its own test rather than sharing the
    // `userEvent` one, which is slow enough to be caught by the button.
    const submit = screen.getByRole("button", { name: LEARN.submitTurn });
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(turns).toHaveLength(1));
  });

  it("offers one honest unavailable surface for a 404, and a retry", async () => {
    const user = userEvent.setup();
    let status = 404;
    routeFetch({
      session: () =>
        status === 404
          ? response({ detail: "session_not_found" }, 404)
          : response(awaiting),
    });
    renderSurface();

    expect(
      await screen.findByRole("heading", { name: LEARN.sessionUnavailableHeading })
    ).toBeVisible();

    status = 200;
    await user.click(screen.getByRole("button", { name: LEARN.retrySession }));
    expect(
      await screen.findByRole("textbox", { name: /Write your response/ })
    ).toBeEnabled();
  });
});
