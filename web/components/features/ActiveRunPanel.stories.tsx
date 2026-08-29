/**
 * Features/ActiveRunPanel — the run that is on screen (WO-20).
 *
 * WHY THIS FILE EXISTS. The Gate 3 evidence pack
 * (`docs/revamp/evidence/gate-3/storybook-states.md` §3) records
 * `ActiveRunPanel/*` as one of three RC-10 union-table modules with **no
 * story**, which is criterion 1's failure. It also records the cause
 * exactly: "WO-20's card has no story criterion at all". `NoActiveRun`
 * below is §4 row B — the state the panel exists to render differently from
 * every other one — and the rest are the states the panel really has, so it
 * cannot pass by absence of them.
 *
 * THE GROUP NAME. The pack writes `ActiveRunPanel/*`; the shipped title is
 * `Features/ActiveRunPanel`, the layer prefix §2 of the same document
 * records for `Features/QueryComposer` ("layer prefix only").
 *
 * WHAT THIS PANEL OWNS AND WHAT IT DOES NOT. The spine, the plan editor at
 * the review pause, one banner for the two states the spine cannot carry
 * alone, and the diagnostics disclosure. It does NOT render the briefing —
 * `selectBriefings` inside `ThreadTimeline` is the one source of truth for
 * which run is on screen (03 §4.7), and a report rendered here as well
 * would be WO-18's double-render defect with a new file name. So there is
 * no report in any story below, and that absence is part of the claim.
 *
 * NO NETWORK, AND NO STREAM — WHICH IS ALSO THE SET'S BOUNDARY. The machine
 * is driven through `JobClient`, the seam `lib/job/types.ts` documents as
 * "how every test in web/tests/job/ avoids POST /research entirely". Each
 * story supplies a `getJob` that answers from a recorded fixture, and
 * `useJobStream`'s GET-first attach then decides whether a stream is needed
 * at all: a job whose status is already terminal settles from its
 * `JobDetail` and opens no connection, and a 404 opens none either ("only a
 * 404 is proof the run is gone"). Every story below is one of those two, so
 * no `EventSource` is ever constructed — which is what makes them
 * renderable in jsdom and in a static build with nothing behind them.
 *
 * THE ONE STATE THAT IS NOT HERE, AND WHY. `awaiting_review` — 03 §5.4's
 * review pause, where this panel composes `PlanEditor` — is reached from a
 * NON-terminal `JobDetail` (`status: "pending_review"`), and a non-terminal
 * detail is exactly the case where GET-first goes on to open the stream. It
 * is unreachable from a story without an `EventSource` stub, and the only
 * one in this repository (`web/tests/support/FakeEventSource.ts`) reads its
 * recordings with `node:fs` and cannot be bundled for a browser. The editor
 * itself has 13 stories of its own (`Patterns/PlanEditor`, covering §4 rows
 * 9, 20, D and E) and `planStatusOf` — the panel's whole contribution to
 * that state — is unit-tested. This is recorded as a finding rather than
 * worked around with a second stub.
 *
 * THE PLAY FUNCTIONS HOLD AT ALL FIVE WIDTHS AND UNDER REDUCED MOTION.
 * `storybook-states.md` §7 records 48 assertions in six existing stories
 * that do not — three race a Radix enter transition, three look for the
 * thread rail below `md` where WO-08 does not render it. Nothing below
 * asserts on an overlay or on anything the shell drops at a breakpoint, and
 * every one of these states is settled, so no story here has the spine's
 * `Live` pulse in it — the product's only ambient motion — and none of them
 * renders differently with animations off.
 *
 * NO STRING IS RENDERED AS TEXT HERE. `copy/no-inline-text` covers
 * `components/features/**`, stories included; the literals below are wire
 * data off `web/contract/fixtures/job.*.json`.
 */

import { useMemo, type ReactElement } from "react";

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { ApiError, type JobDetail } from "@/lib/api";
import { SPINE } from "@/lib/copy/spine";
import { THREAD } from "@/lib/copy/threads";
import { JobRunProvider } from "@/lib/job/provider";
import type { JobClient } from "@/lib/job/types";

import { ActiveRunPanel, type ActiveRunPanelProps } from "./ActiveRunPanel";

// ---------------------------------------------------------------------------
// Recorded runs. Transcribed from web/contract/fixtures/job.*.json — the
// same recordings `tests/support/handlers.ts` serves — because `loadFixture`
// reaches for `node:fs` and a story has to bundle for a browser.
// ---------------------------------------------------------------------------

const CONVERSATION_ID = "baseline-populated";

/** Everything a `JobDetail` carries, so each fixture states only what differs. */
const BLANK: JobDetail = {
  job_id: "",
  status: "succeeded",
  query: "",
  created_at: 1787883362,
  started_at: 1787883364,
  completed_at: null,
  elapsed_sec: null,
  result: null,
  error: null,
  error_type: null,
  cost_usd: null,
  llm_calls: null,
  iterations: null,
  quality_score: null,
  plan: null,
  conversation_id: CONVERSATION_ID,
};

/** `job.succeeded.json`. */
const SUCCEEDED: JobDetail = {
  ...BLANK,
  job_id: "baseline-succeeded",
  status: "succeeded",
  query: "How should scientific research agents verify claims?",
  completed_at: 1787883424,
  elapsed_sec: 60,
  result: "# Retrieval-augmented verification for scientific claims\n",
  cost_usd: 0.42,
  llm_calls: 11,
  iterations: 2,
  quality_score: 0.86,
};

/** `job.failed_partial.json` — D-010 ruling 2's run: failed, with a body. */
const FAILED: JobDetail = {
  ...BLANK,
  job_id: "baseline-failed-partial",
  status: "failed",
  query: "How can ML teams detect unsupported scientific claims?",
  completed_at: 1787883400,
  elapsed_sec: 36,
  result: "# Partial briefing\n",
  error: "Verification stopped before all claims could be checked.",
  error_type: "verification_incomplete",
  cost_usd: 0.18,
  llm_calls: 4,
  iterations: 1,
};

/** `job.cancelled.json` — cancelled at the review pause, nothing searched. */
const CANCELLED: JobDetail = {
  ...BLANK,
  job_id: "baseline-cancelled",
  status: "cancelled",
  query: "Compare retrieval strategies for scientific agents",
  completed_at: 1787883380,
  elapsed_sec: 16,
  cost_usd: 0.03,
  llm_calls: 1,
};

/** H8's 404. It means "missing" and "not yours" and never says which. */
const EXPIRED_ID = "baseline-expired";

// ---------------------------------------------------------------------------
// The harness.
// ---------------------------------------------------------------------------

/**
 * The panel's real props, plus the one thing that actually varies.
 *
 * `adoptJobId` is the route's `?job=` and it is doing double duty here on
 * purpose: it is what the panel is told, AND what the provider is given as
 * the job to attach. That is exactly the reload case — `/c/{id}?job={id}`,
 * where "a job that is already the route's `adoptJobId` is never written
 * back", so criterion 1's `router.replace` never fires and no story is
 * asserting a navigation that has no router. `null` is §4 row B.
 *
 * `detail` is the only addition: what `GET /research/{id}` answers for that
 * id, or `null` for the 404.
 */
interface PanelArgs extends ActiveRunPanelProps {
  detail: JobDetail | null;
}

/**
 * One provider, one panel, and a network seam that can reach nothing.
 *
 * `submitResearch` rejects because R-01 says the one billable call on this
 * surface must be unreachable from a story even by accident — this panel
 * never calls it, and now it could not succeed if it did. `poll: false` is
 * the option `LivenessPollOptions.enabled` documents for exactly this
 * ("`false` disables the poll entirely (Storybook, some tests)"), so a
 * story left open on a screen issues nothing on a timer.
 */
function Panel({ detail, ...props }: PanelArgs): ReactElement {
  const client = useMemo<Partial<JobClient>>(
    () => ({
      getJob: (requested: string) =>
        detail === null
          ? Promise.reject(new ApiError(404, "job not found"))
          : Promise.resolve({ ...detail, job_id: requested }),
      submitResearch: () => Promise.reject(new ApiError(404, "stories reach no network")),
      reviewPlan: () => Promise.reject(new ApiError(404, "stories reach no network")),
      streamUrl: () => "",
    }),
    [detail],
  );

  return (
    <JobRunProvider
      jobId={props.adoptJobId}
      conversationId={props.conversationId}
      client={client}
      poll={{ enabled: false }}
    >
      <div className="border border-border-subtle bg-surface p-4">
        <ActiveRunPanel {...props} />
      </div>
    </JobRunProvider>
  );
}

/**
 * `component` is the panel and the args are the panel's, so the docs page
 * and the story ids are the module's; `render` is what puts the provider
 * around it, because the machine is a provider rather than a prop and the
 * states below are distinguished by what the machine learned.
 */
const meta = {
  title: "Features/ActiveRunPanel",
  component: ActiveRunPanel,
  args: {
    conversationId: CONVERSATION_ID,
    adoptJobId: null,
    detail: null,
    legend: "disclosure",
  },
  render: (args) => <Panel {...args} />,
} satisfies Meta<PanelArgs>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The panel's own section, whatever it is rendering. */
function panelOf(canvasElement: HTMLElement): Element | null {
  return canvasElement.querySelector('[data-surface="active-run"]');
}

/**
 * **§4 row B — "No active job (`/c/[id]` without `?job=`)".**
 *
 * ONE SENTENCE, NOT AN INERT SPINE, AND THAT IS A MEASUREMENT. `TraceSpine`
 * will happily draw its four segment names with nothing observed, on the
 * reasonable ground that the shape the reader is about to meet is already
 * on screen. Composed into this row it cost 428px of a 669px surface —
 * measured in a browser on WO-20's branch — and squeezed the reading column
 * to ZERO on a thread that has briefings to read and no run at all. So the
 * absence of a run is stated in the words the dictionary has for it, the
 * diagnostics disclosure is not rendered either, and the column is given
 * back. The spine returns the moment there is a run to trace, which is
 * every other story in this file.
 *
 * Nothing is fetched here: with `adoptJobId: null` the provider has no job
 * to adopt, so `getJob` is not called even once.
 */
export const NoActiveRun: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(THREAD.noRun)).toBeVisible();

    const panel = panelOf(canvasElement);
    await expect(panel).toHaveAttribute("data-run-phase", "idle");
    await expect(panel).toHaveAttribute("data-run-job", "");

    // The three things row B is defined by NOT having: no spine, no
    // diagnostics disclosure — so no control of any kind — and no alert.
    await expect(canvasElement.querySelector("[data-spine-state]")).toBeNull();
    await expect(canvas.queryAllByRole("button")).toHaveLength(0);
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
};

/**
 * A finished run, attached and reconciled — 03 §5.4's `historic` row.
 *
 * `historic`, not `succeeded`, and the difference is the honest one: this
 * browser adopted the run after it had already finished, so it observed no
 * checkpoints and the spine says so rather than drawing a walk it did not
 * see. The state is reached with no stream at all — GET-first reads the
 * detail, finds a terminal status, and returns without opening one.
 *
 * What is deliberately missing from the spine is 03 §5.4's cost line:
 * quality, dollars and calls are none of §5.2's four inputs, so the spine
 * says "Complete" and `Patterns/MetricsStrip` says what it cost.
 */
export const SucceededFromHistory: Story = {
  args: { adoptJobId: SUCCEEDED.job_id, detail: SUCCEEDED },
  play: async ({ canvasElement }) => {
    const panel = panelOf(canvasElement);
    await expect(panel).not.toBeNull();

    const canvas = within(canvasElement);
    // `findBy*` because the detail arrives a microtask after mount; the
    // assertion is on the settled state, not on a race.
    const spine = await canvas.findByRole("region", { name: SPINE.regionLabel });
    await expect(spine).toHaveAttribute("data-spine-state", "historic");
    await expect(panelOf(canvasElement)).toHaveAttribute("data-run-phase", "settled");
    await expect(panelOf(canvasElement)).toHaveAttribute(
      "data-run-job",
      SUCCEEDED.job_id,
    );

    // The panel never renders the briefing — that is `ThreadTimeline`'s,
    // through `selectBriefings`, and a second copy here is the WO-18
    // double-render defect.
    await expect(canvasElement.querySelector("[data-report-reader]")).toBeNull();
  },
};

/**
 * §4 row 15's spine half — a run the server reported as `failed`, adopted
 * after the fact.
 *
 * `failed_unobserved` rather than `failed_observed`, for the same reason as
 * above: no checkpoint was seen on any connection this browser opened. 03
 * §5.4's rule is that the sentence never names a stage — no terminal
 * payload carries a node, so "failed at the verifier" would be invented.
 *
 * The failure BANNER is not here and that is correct: this panel announces
 * only a failed submission, because that is something the user just did.
 * A run that merely became failed is the spine's to state, and
 * `ReportReader/PartialFromFailedRun` renders the body it retained.
 */
export const FailedFromHistory: Story = {
  args: { adoptJobId: FAILED.job_id, detail: FAILED },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const spine = await canvas.findByRole("region", { name: SPINE.regionLabel });
    await expect(spine).toHaveAttribute("data-spine-state", "failed_unobserved");
    await expect(panelOf(canvasElement)).toHaveAttribute("data-run-phase", "settled");
    // No `role="alert"`: nothing the user just did failed. See
    // `StatusBanner`'s header — `userTriggered` is the only thing that
    // renders one, product-wide.
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
};

/**
 * §4 row 13 — cancelled.
 *
 * The review pause is the only cancellation point there is, so the Plan
 * segment carries the cancellation and the two segments after it stay
 * un-drawn. "Cancelled at plan review. Nothing was searched." is the
 * dictionary's sentence for it, and it is a claim the contract supports.
 */
export const Cancelled: Story = {
  args: { adoptJobId: CANCELLED.job_id, detail: CANCELLED },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const spine = await canvas.findByRole("region", { name: SPINE.regionLabel });
    await expect(spine).toHaveAttribute("data-spine-state", "cancelled");
    await expect(panelOf(canvasElement)).toHaveAttribute(
      "data-run-job",
      CANCELLED.job_id,
    );
  },
};

/**
 * §4 row 16 — the expired run, and the half of it that is this panel's.
 *
 * H8: `GET /research/{id}` answers 404 both for a run that aged out of
 * `api_job_retention_sec` and for one belonging to another principal, and
 * the client must never try to tell them apart. The spine's own status line
 * carries `UNAVAILABLE_COPY`; this panel adds only the RECOVERY, because
 * WO-20's first browser run of it showed the same words on screen twice —
 * a strict-mode locator violation before it was a design problem. And the
 * recovery is a SENTENCE naming the composer below, never a button: one
 * click must not start a billable run.
 */
export const Unavailable: Story = {
  args: { adoptJobId: EXPIRED_ID, detail: null },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const spine = await canvas.findByRole("region", { name: SPINE.regionLabel });
    await expect(spine).toHaveAttribute("data-spine-state", "expired");
    await expect(panelOf(canvasElement)).toHaveAttribute("data-run-phase", "unavailable");

    await expect(canvas.getByText(THREAD.askAgain)).toBeVisible();
    // The recovery is text, not a control. Nothing in this panel can start
    // a run — the only button here belongs to the diagnostics disclosure.
    await expect(
      canvas.queryByRole("button", { name: THREAD.askAgain }),
    ).toBeNull();
  },
};

/**
 * 03 §5.3's other legend mode: shown once per session, then folded away.
 *
 * The composing route owns that decision, so it is a prop rather than
 * state; this is the "first visit" rendering, with the mark vocabulary
 * open. Worth its own story because the legend is what makes the spine
 * readable in forced colours, where the hue is the first thing lost.
 */
export const LegendOpen: Story = {
  args: { adoptJobId: SUCCEEDED.job_id, detail: SUCCEEDED, legend: "open" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("region", { name: SPINE.regionLabel });
    await expect(canvasElement.querySelector('[data-spine-part="legend"]')).not.toBeNull();
  },
};

/** §4 row 8 as an explicit render rather than only as a toolbar axis. */
export const Dark: Story = {
  args: { adoptJobId: SUCCEEDED.job_id, detail: SUCCEEDED },
  globals: { theme: "dark" },
};

/**
 * RC-17's question of the surface that has the most to lose from it: with
 * every `--color-*` role collapsed onto system colours, the spine's marks
 * and the status word have to carry the state on their own.
 */
export const ForcedColours: Story = {
  args: { adoptJobId: SUCCEEDED.job_id, detail: SUCCEEDED, legend: "open" },
  globals: { theme: "forced-colors" },
};
