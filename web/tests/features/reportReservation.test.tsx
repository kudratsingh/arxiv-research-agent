/**
 * WO-S2d — the briefing mounts at the height it keeps, in the half jsdom has.
 *
 * `e2e/mount-reservation.spec.ts` owns the pixels; layout is the one thing
 * jsdom does not have. What is assertable HERE is the mechanism they come out
 * of — WHEN the thread's loading frame is held, and, the half that will
 * actually rot, when it must not be.
 *
 * THE DEFECT. `ReportReader`'s loading state is seven skeleton lines — 216px
 * at 412x915 — and the briefing it holds the place of renders at 844px. Below
 * 767px the thread is a DOCUMENT and not a frame (WO-S2, `workspace.css`), so
 * everything under the reading column moves when it grows: at the Pixel 7
 * profile on `thread-populated`, 8x CPU throttle, `div.ew-thread__composer`
 * went from y792 to off screen and Chromium charged 0.03768 of 04 §8.2's 0.02
 * ceiling, with a second 0.04176 behind it. It is a race — the Markdown
 * pipeline is a dynamic `import()` — which is why it was first reported as a
 * flaky test rather than as a defect (F1, PR 270).
 *
 * THE FIX IS WO-S2c's, APPLIED ONE SURFACE ALONG. A briefing's height is its
 * own document's and there is no number this tree could reserve that would be
 * right for the next report, so nothing is reserved: the loading frame is
 * held until the briefing can be RENDERED, and the reading column then mounts
 * once, already the size it keeps.
 *
 * THE HAZARDS, WHICH ARE WHY THE OTHER TESTS EXIST. A hold on a thread with
 * nothing to render would be a wait for its own sake; a hold that could fire
 * again after the thread has been on screen would take the transcript away
 * mid-read; and a hold keyed on the renderer rather than on the pipeline
 * having SETTLED would never release against a chunk that 404s — that last
 * one is `tests/queries/markdownFailure.test.ts`, because the module-level
 * promise cache makes "the import rejected" a per-file state.
 */

import { createElement, type ReactElement, type ReactNode } from "react";

import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryProvider } from "@/app/providers";
import { ActiveRunPanel } from "@/components/features/ActiveRunPanel";
import {
  FollowUpComposer,
  ThreadTimeline,
} from "@/components/features/ThreadTimeline";
import { API_BASE, type ConversationDetail } from "@/lib/api/index";
import { JobRunProvider } from "@/lib/job/provider";

import {
  installFakeEventSource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture, server, setupMswServer } from "../support/msw";
import { render, screen, user, waitFor } from "../support/render";

/**
 * The Markdown chunk, with its arrival in this file's hands.
 *
 * A real cold load loses this race only on a slow enough client, which is
 * exactly why the defect read as a flake. Holding the import makes the worst
 * case certain, and the worst case is a superset of the plain one: anything
 * that passes here passes unheld.
 */
const pipeline = vi.hoisted(() => {
  let land: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    land = resolve;
  });
  return { held, land: () => land(), imports: 0 };
});

vi.mock("react-markdown", async () => {
  // Incremented before the await, so it counts the IMPORT and not its
  // arrival: a test that asserts nothing was loaded has to fail even while
  // the chunk is still in flight.
  pipeline.imports += 1;
  await pipeline.held;
  return {
    default: ({ children }: { children?: ReactNode }) =>
      createElement("div", { "data-markdown": "true" }, children),
  };
});

const DETAIL = loadFixture("conversations.detail").body as ConversationDetail;
const THREAD_ID = DETAIL.conversation_id;

/** The same thread, with its one turn's briefing empty. */
const NO_BRIEFING: ConversationDetail = {
  ...DETAIL,
  jobs: DETAIL.jobs.map((job) => ({ ...job, report: "" })),
};

setupMswServer(
  http.get(`${API_BASE}/conversations/:conversationId`, () =>
    HttpResponse.json(DETAIL),
  ),
);

beforeEach(() => {
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
});

/** The route's own composition, minus the router. */
function Workspace(): ReactElement {
  return (
    <QueryProvider>
      <JobRunProvider jobId={null} conversationId={THREAD_ID}>
        <ThreadTimeline
          conversationId={THREAD_ID}
          runPanel={<ActiveRunPanel conversationId={THREAD_ID} adoptJobId={null} />}
          composer={<FollowUpComposer conversationId={THREAD_ID} />}
        />
      </JobRunProvider>
    </QueryProvider>
  );
}

const skeleton = () => document.querySelector('[data-recovery-surface="loading"]');
const readerLoading = () => document.querySelector(".ew-report-reader__loading");
const briefing = () => document.querySelector("[data-briefing]");

// ---------------------------------------------------------------------------
// The thread with nothing to render must not wait for a renderer.
// ---------------------------------------------------------------------------

describe("a thread whose open turn has no briefing waits for nothing", () => {
  /**
   * The chunk is never released in this test, so the thread paints or it does
   * not: there is no timing to get lucky with. A turn with no briefing body
   * renders one sentence (`REPORT.empty`), and holding a whole transcript for
   * a document that does not exist would be a wait bought with nothing to
   * spend it on.
   */
  it("paints while the Markdown pipeline is still in flight", async () => {
    server.use(
      http.get(`${API_BASE}/conversations/:conversationId`, () =>
        HttpResponse.json(NO_BRIEFING),
      ),
    );
    render(<Workspace />);

    await screen.findByRole("heading", { level: 1, name: DETAIL.title });
    expect(skeleton()).toBeNull();
    expect(briefing()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The hold itself.
// ---------------------------------------------------------------------------

describe("WO-S2d — the thread waits for the briefing it is about to show", () => {
  it("holds the loading frame after the transcript lands, until the pipeline settles", async () => {
    render(<Workspace />);

    // The transcript has arrived — the read resolved and the chunk it needs
    // has been asked for — and the thread is still the loading frame.
    await waitFor(() => expect(pipeline.imports).toBe(1));
    await waitFor(() => expect(skeleton()).not.toBeNull());
    expect(
      screen.queryByRole("heading", { level: 1, name: DETAIL.title }),
      "the thread painted before the briefing could be rendered. The reading " +
        "column would have mounted at the reader's 216px skeleton and grown " +
        "to 844px under a composer that was already on screen.",
    ).toBeNull();

    // The chunk lands. The thread paints ONCE, with the document already in
    // it — the reader's own loading state is never on screen in the loaded
    // frame, which is the whole reservation.
    pipeline.land();
    await screen.findByRole("heading", { level: 1, name: DETAIL.title });
    expect(skeleton()).toBeNull();
    expect(
      readerLoading(),
      "the loaded thread painted with the reader still showing its skeleton, " +
        "so the frame was released one beat too early.",
    ).toBeNull();
    expect(briefing()).not.toBeNull();
    expect(document.querySelector("[data-markdown]")).not.toBeNull();
  });

  /**
   * The latch, which is the difference between a MOUNT reservation and a
   * permanent one. `painted` is set on the first loaded frame and never
   * cleared, so a turn the reader collapses and reopens — or any later change
   * of which turn is open — moves the reader's own loading state and never
   * the transcript.
   */
  it("never takes the transcript away again once it has been on screen", async () => {
    render(<Workspace />);
    pipeline.land();
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: DETAIL.title,
    });

    const typist = user();
    const turn = screen.getByRole("button", { name: /Turn 1/ });
    await typist.click(turn);
    await waitFor(() => expect(briefing()).toBeNull());
    expect(skeleton()).toBeNull();
    expect(heading).toBeInTheDocument();

    await typist.click(turn);
    await waitFor(() => expect(briefing()).not.toBeNull());
    expect(
      skeleton(),
      "reopening a turn put the thread back into its loading frame. The hold " +
        "is a mount reservation: it holds before the thread has ever been " +
        "painted and never afterwards.",
    ).toBeNull();
    expect(heading).toBeInTheDocument();
  });
});
