/**
 * Features/ThreadTimeline — §4 rows 5 and B, and the rest of the surface's
 * real states (WO-20).
 *
 * WHY THIS FILE EXISTS. The Gate 3 evidence pack
 * (`docs/revamp/evidence/gate-3/storybook-states.md` §3) records **two §4
 * rows with no story at all** — row 5 "Empty thread", which §4 names
 * `ThreadTimeline/Empty`, and row B "No active job (`/c/[id]` without
 * `?job=`)", which §4 names `ThreadTimeline/NoActiveRun` — and that is
 * criterion 1's failure. The pack is precise about the cause: WO-20's card
 * carries no story criterion, so no work order was ever given the rows.
 * `Empty` and `NoActiveRun` below are those two rows; the rest exist so the
 * module cannot pass by absence of the states it really has.
 *
 * THE GROUP NAME. §4 writes `ThreadTimeline/*`; the shipped title is
 * `Features/ThreadTimeline`, which is the layer prefix §2 of the same
 * document already records for `Features/QueryComposer` ("layer prefix
 * only" — expressly not a coverage gap).
 *
 * NO NETWORK, AND THAT IS ENFORCED RATHER THAN HOPED FOR. This is a
 * `features/` component: 04 §5.1's "reachable by passing props" rule does
 * not apply to it, and it reads `useConversationDetail` and `useJobRun`
 * directly. So the two providers are supplied here exactly as
 * `web/tests/features/routeComposition.test.tsx` supplies them, with the
 * seams both layers already expose:
 *
 *   - the QueryClient is **seeded, never fetched**. Data states go in
 *     through `setQueryData`; the two failure states go in as a query state
 *     on the cache. `retryOnMount: false` + `refetchOnMount: false` +
 *     `staleTime: Infinity` is what makes the observer decline to fetch on
 *     mount in every one of those four cases, which is why no handler and
 *     no MSW is needed to keep a story off the wire.
 *   - the job machine gets a `JobClient` (`lib/job/types.ts`, "how every
 *     test avoids `POST /research` entirely") whose `submitResearch`
 *     REJECTS. The follow-up composer is on screen in every story because
 *     it is on screen on the route, and R-01 says the one non-idempotent,
 *     billable call on the surface must be unreachable from a story even by
 *     accident. It is: no story types into the composer, and if one did the
 *     seam refuses it before `lib/api` is reached.
 *
 * Every story below is `jobId: null`, so the machine never attaches, never
 * opens an `EventSource` and never issues `GET /research/{id}`.
 * `Features/ActiveRunPanel` is where the attached run's own states live.
 *
 * THE PLAY FUNCTIONS HOLD AT ALL FIVE WIDTHS AND UNDER REDUCED MOTION, and
 * that is deliberate rather than incidental. `storybook-states.md` §7
 * records 48 play-function assertions in six existing stories that do not:
 * three assert `toBeVisible()` inside a Radix overlay mid-transition (they
 * pass only under reduced motion), and three look for the thread rail below
 * `md`, where WO-08 deliberately does not render it. Nothing below asserts
 * on an overlay, on a transition, or on any element the shell drops at a
 * breakpoint — this surface renders the same DOM at 320 as at 1440, and the
 * assertions are all `findBy*`, which retries.
 *
 * NO STRING IS RENDERED AS TEXT HERE. `copy/no-inline-text` covers
 * `components/features/**`, stories included. The literals below are wire
 * data — a thread title, a question, a Markdown body — which is exactly
 * what arrives from `GET /conversations/{id}`.
 */

import { useState, type ReactElement } from "react";

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, within } from "storybook/test";

import { ApiError, type ConversationDetail } from "@/lib/api";
import { THREAD, THREAD_RAIL, turnCount } from "@/lib/copy/threads";
import { JobRunProvider } from "@/lib/job/provider";
import type { JobClient } from "@/lib/job/types";
import { queryKeys } from "@/lib/queries/keys";
import { loadReportRenderer } from "@/lib/report/renderer";

import { ActiveRunPanel } from "./ActiveRunPanel";
import {
  FollowUpComposer,
  ThreadTimeline,
  type ThreadTimelineProps,
} from "./ThreadTimeline";

// ---------------------------------------------------------------------------
// The thread, as `GET /conversations/{id}` returns it.
//
// Transcribed from `web/contract/fixtures/conversations.detail.json` — the
// same recording `routeComposition.test.tsx` loads through `loadFixture` —
// with the second turn that file adds so "the newest one is expanded" is a
// real distinction. It is inlined rather than read, because `loadFixture`
// reaches for `node:fs` and a story has to bundle for a browser.
// ---------------------------------------------------------------------------

const CONVERSATION_ID = "baseline-populated";

const FIRST_REPORT = [
  "# Retrieval-augmented verification for scientific claims",
  "",
  "## Executive summary",
  "",
  "Recent systems combine retrieval, claim decomposition and post-generation",
  "verification to reduce unsupported statements. The strongest pattern is to",
  "preserve source provenance throughout synthesis rather than adding",
  "citations after generation.",
  "",
  "## Findings",
  "",
  "- Evidence retrieval works best when queries are decomposed into",
  "  independently verifiable claims.",
  "- Verification models should be calibrated separately from generation",
  "  models.",
].join("\n");

const SECOND_REPORT = [
  "# Which findings are contested",
  "",
  "Two of the eleven papers disagree with the retrieval-first conclusion, and",
  "both disagree on the same ground: recall, not provenance.",
].join("\n");

const POPULATED: ConversationDetail = {
  conversation_id: CONVERSATION_ID,
  title: "Scientific claim verification",
  created_at: 1787883362,
  updated_at: 1787883424,
  jobs: [
    {
      job_id: "baseline-succeeded",
      ordinal: 1,
      query: "How should scientific research agents verify claims?",
      report: FIRST_REPORT,
      created_at: 1787883424,
    },
    {
      job_id: "baseline-second",
      ordinal: 2,
      query: "Which of those findings are contested?",
      report: SECOND_REPORT,
      created_at: 1787883500,
    },
  ],
};

/** The same thread before its first question. §4 row 5's whole input. */
const EMPTY: ConversationDetail = { ...POPULATED, jobs: [] };

// ---------------------------------------------------------------------------
// The two seams, closed.
// ---------------------------------------------------------------------------

/**
 * The network seam, refusing.
 *
 * `submitResearch` is the R-01 guard: it is the only billable call this
 * surface can make, and here it cannot be made at all. `getJob` and
 * `reviewPlan` reject too — no story attaches a run, so neither is ever
 * called, and a 404-shaped rejection is the one shape that opens no
 * `EventSource` if a future edit ever does call it (`useJobStream.ts`:
 * "only a 404 is proof the run is gone", every other status still gets a
 * stream).
 */
const REFUSED = (): Promise<never> =>
  Promise.reject(new ApiError(404, "stories reach no network"));

const OFFLINE_CLIENT: Partial<JobClient> = {
  getJob: REFUSED,
  submitResearch: REFUSED,
  reviewPlan: REFUSED,
  streamUrl: () => "",
};

type Seed = "empty" | "populated" | "not-found" | "load-error";

/**
 * A QueryClient holding the answer already, so the observer never fetches.
 *
 * The two failure seeds go in as a query STATE rather than as data, because
 * that is what the two branches read: `notFound` is
 * `error instanceof ApiError && error.status === 404`, and the load-error
 * branch is `detail === undefined` with the query no longer pending. A
 * `queryFn` that threw would be a request; a seeded error is not.
 */
function seededClient(seed: Seed): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        // The one option that keeps an ERRORED seed off the wire: without
        // it the observer treats a mount as a retry opportunity.
        retryOnMount: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        staleTime: Number.POSITIVE_INFINITY,
        gcTime: Number.POSITIVE_INFINITY,
      },
      mutations: { retry: false },
    },
  });

  const queryKey = queryKeys.conversations.detail(CONVERSATION_ID);

  if (seed === "empty" || seed === "populated") {
    client.setQueryData(queryKey, seed === "empty" ? EMPTY : POPULATED);
    return client;
  }

  const error =
    seed === "not-found"
      ? new ApiError(404, "conversation not found")
      : new ApiError(503, "upstream unavailable");

  client.getQueryCache().build(client, { queryKey }).setState({
    status: "error",
    fetchStatus: "idle",
    error,
    errorUpdatedAt: POPULATED.updated_at * 1000,
    errorUpdateCount: 1,
    fetchFailureCount: 1,
    fetchFailureReason: error,
  });

  return client;
}

/**
 * The route's own composition, minus the router — the same three-part tree
 * `routeComposition.test.tsx` renders, with the run panel and the follow-up
 * composer in the slots WO-20 gives them.
 */
function Thread({ seed }: { seed: Seed }): ReactElement {
  const [client] = useState(() => seededClient(seed));
  return (
    <QueryClientProvider client={client}>
      <JobRunProvider
        jobId={null}
        conversationId={CONVERSATION_ID}
        client={OFFLINE_CLIENT}
        poll={{ enabled: false }}
      >
        <ThreadTimeline
          conversationId={CONVERSATION_ID}
          runPanel={<ActiveRunPanel conversationId={CONVERSATION_ID} adoptJobId={null} />}
          composer={<FollowUpComposer conversationId={CONVERSATION_ID} />}
        />
      </JobRunProvider>
    </QueryClientProvider>
  );
}

/**
 * The component's own props plus the one thing that varies.
 *
 * `conversationId` is the timeline's real prop and the story's; `seed` is
 * what the query cache is holding for it, because what distinguishes these
 * states is the cache rather than a prop, and `render` is what puts the two
 * providers around the component.
 *
 * `.ew-thread` is `height: 100%` (workspace.css) because on the route it is
 * a track of `.ew-shell__surface`'s grid. A story that let it size itself
 * from its content would document a layout the product never renders, so
 * the decorator supplies the definite height the shell supplies.
 */
interface TimelineArgs extends ThreadTimelineProps {
  seed: Seed;
}

const meta = {
  title: "Features/ThreadTimeline",
  component: ThreadTimeline,
  parameters: { nextjs: { appDirectory: true } },
  args: { conversationId: CONVERSATION_ID, seed: "empty" },
  render: ({ seed }) => <Thread seed={seed} />,
  decorators: [
    (Story) => (
      <div className="h-[34rem] border border-border-subtle bg-canvas">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<TimelineArgs>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * **§4 row 5 — "Empty thread".** The story the state coverage map has been
 * naming since before the component existed.
 *
 * Two things are true here at once and the story exists to show both: the
 * thread loaded fine, and it has nothing in it. The heading is an `h2`, not
 * `EmptyState`'s default `h3` — on a thread with no run there is no spine
 * between the thread's `h1` and this heading to supply the level in
 * between, and axe's `heading-order` caught the skip on exactly this state
 * (`ThreadTimeline.tsx`, above the `EmptyState` call).
 *
 * It is also, unavoidably, row B: a thread with no turns has no run either,
 * so `data-run` is `none` and the panel is one sentence high. The
 * evidence pack's e2e state `thread-empty` claims both rows for the same
 * reason.
 */
export const Empty: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    await expect(
      await canvas.findByRole("heading", { level: 1, name: POPULATED.title }),
    ).toBeVisible();
    await expect(canvas.getByText(turnCount(0))).toBeVisible();

    // The row-5 assertion: the empty state, at the level the heading order
    // requires, with the sentence that says what a turn IS.
    await expect(
      await canvas.findByRole("heading", { level: 2, name: THREAD.emptyHeading }),
    ).toBeVisible();
    await expect(canvas.getByText(THREAD.emptyBody)).toBeVisible();
    await expect(canvasElement.querySelector("[data-empty-state]")).not.toBeNull();

    // Not the loading state and not the error state: no skeleton, no alert.
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
};

/**
 * **§4 row B — "No active job (`/c/[id]` without `?job=`)".**
 *
 * The distinction from row 5 is the one this story is for: the thread has
 * briefings to read and there is no run attached to the page. That is not
 * an error and not an empty state, and 04's variant table gives it its own
 * row because the obvious rendering — an inert spine — is wrong. WO-20
 * measured it: `TraceSpine` with `inputs: null` costs 428px of a 669px
 * surface and squeezes the reading column to zero. So the panel says the
 * sentence the dictionary has for it and gives the column back, and
 * `data-run="none"` keeps the row one sentence high (`workspace.css`).
 *
 * `hasActiveRun` is the single predicate behind both halves, which is why
 * the two attributes below cannot disagree.
 */
export const NoActiveRun: Story = {
  args: { seed: "populated" },
  loaders: [async () => ({ renderer: await loadReportRenderer() })],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    await expect(await canvas.findByText(THREAD.noRun)).toBeVisible();

    // The panel's own state, and the row it is rendered into. One predicate
    // (`hasActiveRun`) answers for both.
    const panel = canvasElement.querySelector('[data-surface="active-run"]');
    await expect(panel).toHaveAttribute("data-run-phase", "idle");
    await expect(panel).toHaveAttribute("data-run-job", "");
    await expect(canvasElement.querySelector("[data-run]")).toHaveAttribute(
      "data-run",
      "none",
    );

    // No run, but the thread is not empty — that is the whole of row B.
    await expect(await canvas.findAllByRole("button", { name: /^Turn \d/ })).toHaveLength(
      POPULATED.jobs.length,
    );
    await expect(canvasElement.querySelector("[data-empty-state]")).toBeNull();
  },
};

/**
 * §4 row 7, composed — the state `Patterns/ReportReader` documents as a
 * component and this documents as a thread.
 *
 * Criterion 4 is what to look at: the newest turn is open and every other
 * turn is a question row, and a collapsed turn is never Markdown-parsed.
 * The report bodies all arrived in the same response
 * (`schemas.py:184-191`), so a ten-turn thread would otherwise parse ten
 * documents to show one — `useReportRenderer(expanded)` returns `null`
 * while collapsed and the dynamic `import()` never happens.
 */
export const Populated: Story = {
  args: { seed: "populated" },
  loaders: [async () => ({ renderer: await loadReportRenderer() })],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    const turns = await canvas.findAllByRole("button", { name: /^Turn \d/ });
    await expect(turns).toHaveLength(2);
    await expect(turns[0]).toHaveAttribute("aria-expanded", "false");
    await expect(turns[1]).toHaveAttribute("aria-expanded", "true");

    // One open turn, one rendered briefing. The collapsed one's body came
    // down the wire and was never touched.
    await expect(canvasElement.querySelectorAll("[data-report-reader]")).toHaveLength(1);
    await expect(canvas.getByText(turnCount(2))).toBeVisible();
  },
};

/**
 * §4 row 21 — the 404 the PRODUCT raises, inline, in the thread's place.
 *
 * H8 is the reason the copy reads the way it does: `GET /conversations/{id}`
 * answers 404 both for a thread that never existed and for one belonging to
 * another principal (`_check_ownership`, `src/api/routes.py:59`), and the
 * client cannot tell them apart. `Shell/NotFoundProduct` documents the
 * surface; this documents the branch — that a 404 from the thread query,
 * and only a 404, takes it.
 */
export const NotFound: Story = {
  args: { seed: "not-found" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", { name: THREAD.notFoundHeading }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("link", { name: THREAD.notFoundBackToStart }),
    ).toBeVisible();
  },
};

/**
 * The other half of the failed read: a status that is NOT 404.
 *
 * A 503 says nothing about whether the thread exists, so the surface keeps
 * its own heading and offers the read again — `Retry` re-runs
 * `GET /conversations/{id}` and can reach no mutation at all (H6, R-01).
 * The story never clicks it; that the control exists and says what it
 * re-runs is the claim.
 */
export const LoadError: Story = {
  args: { seed: "load-error" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", { level: 1, name: THREAD.loadErrorHeading }),
    ).toBeVisible();
    await expect(canvas.getByText(THREAD.loadErrorBody)).toBeVisible();
    await expect(canvas.getByText(THREAD.loadErrorRecovery)).toBeVisible();
    await expect(canvas.getByRole("button", { name: THREAD_RAIL.retry })).toBeVisible();
  },
};

/** §4 row 8, as an explicit render of row 5 rather than only a toolbar axis. */
export const EmptyDark: Story = {
  globals: { theme: "dark" },
};

/**
 * RC-17's question on this surface: with every `--color-*` role collapsed
 * onto system colours, is the difference between "no turns" and "no run"
 * still carried? Both are sentences, so it is.
 */
export const EmptyForcedColours: Story = {
  globals: { theme: "forced-colors" },
};
