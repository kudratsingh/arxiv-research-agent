/**
 * Patterns/PlanEditor — WO-17's ten states, on screen (criterion 11).
 *
 * READ `Default` AND `Edited` TOGETHER. They are the whole of criterion 1:
 * the same single control, relabelled by the working copy. The baseline shipped
 * two approve buttons that were never both usable (`PlanReview.tsx:90-106`);
 * neither of its labels exists anywhere in this file.
 *
 * `Conflict409` and `HitlTimedOut` are the two 409s. Both refetch — the
 * `onRefetch` action fires on mount in each — and neither dead-ends; they
 * differ only in what the refetched run turned out to say.
 *
 * EVERY STORY RENDERS INSIDE A `main`. The plan-review state is tied for the
 * worst baseline axe result (5 violations); two of those five — `region` and
 * `landmark-one-main` — are page-level rules that no component can satisfy
 * alone. Rendering in the landmark the shell provides (WO-08) is the honest
 * context for the other three, and it is the context the surface ships in.
 *
 * NO STRING IN THIS FILE IS RENDERED AS TEXT. `copy/no-inline-text` covers
 * `components/patterns/**`, stories included: every word on screen arrives
 * from `@/lib/copy/plan` through the component, and the literals below are
 * accessible names used to FIND controls in a play function, never to write
 * one.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { Plan } from "@/lib/api";
import { PLAN } from "@/lib/copy/plan";
import { MAX_PLAN_ITEMS, MAX_PLAN_ITEM_LEN } from "@/lib/plan/schema";

import { PlanEditor } from "./PlanEditor";

/**
 * The recorded plan from `web/contract/fixtures/job.pending_review.json`.
 *
 * Three sub-questions and three queries, which is what the planner really
 * emits (2-6, `schemas.py:20-27`) — not a shape invented to make a column
 * look balanced.
 */
const PLAN_FIXTURE: Plan = {
  sub_questions: [
    "Which verification architectures are currently used?",
    "How is evidence provenance preserved?",
    "What evaluation methods detect unsupported claims?",
  ],
  search_queries: [
    "retrieval augmented claim verification",
    "evidence provenance language model",
    "unsupported claim detection evaluation",
  ],
};

const meta = {
  title: "Patterns/PlanEditor",
  component: PlanEditor,
  decorators: [
    (Story) => (
      <main className="mx-auto max-w-content p-gutter-narrow">
        <Story />
      </main>
    ),
  ],
  args: {
    plan: PLAN_FIXTURE,
    onReview: fn(),
    onRefetch: fn(),
  },
} satisfies Meta<typeof PlanEditor>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Cross the lazy boundary once, while this file is being evaluated.
 *
 * A test host is not a browser. The first `import()` of `PlanEditorFields`
 * has to transform React Hook Form and put Zod through the module loader,
 * which under a fully parallel `vitest run` costs seconds — and in the
 * Vitest addon those seconds are charged to whichever story happens to
 * render first, which is a flaky timeout rather than a real signal. Awaiting
 * the same import at module scope moves the cost into module evaluation,
 * where it is paid once and belongs to no story.
 *
 * It is deliberately an `import()` rather than a static import: this file
 * must not become the second module in the repository with a static edge to
 * the fields module, and `web/tests/plan/bundle.test.ts` asserts exactly
 * that. In the browser Storybook this line is a warm cache and nothing else;
 * the surface still reaches the module through `React.lazy`.
 */
await import("./PlanEditorFields");

/** The form is behind `React.lazy`; every story waits for its chunk. */
async function form(canvas: ReturnType<typeof within>): Promise<HTMLElement> {
  return waitFor(
    () =>
      canvas.getByRole("button", {
        name: (name: string) => name === PLAN.approve || name === PLAN.revise,
      }),
    { timeout: 4000 },
  );
}

// ---------------------------------------------------------------------------
// Criterion 1 — one control, two labels.
// ---------------------------------------------------------------------------

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Unedited: one control, reading "Approve plan", and no second approve
    // beside it. 03 §7.2's focus-on-removal rule is driven in
    // `web/tests/plan/PlanEditor.test.tsx`, which walks all three of its
    // cases; repeating one of them here would only buy a slower story.
    await expect(await form(canvas)).toHaveAccessibleName(PLAN.approve);
    await expect(canvas.getAllByRole("button", { name: PLAN.approve })).toHaveLength(1);
  },
};

export const Edited: Story = {
  args: {
    initialDraft: {
      subQuestions: [
        "Which verification architectures are currently used?",
        "Which of them have been evaluated outside their own paper?",
      ],
      searchQueries: [
        "retrieval augmented claim verification",
        "evidence provenance language model",
        "unsupported claim detection evaluation",
      ],
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const primary = await form(canvas);
    // The same control, relabelled — and it sends `revise`, with the plan.
    await expect(primary).toHaveAccessibleName(PLAN.revise);
    await userEvent.click(primary);
    await waitFor(() =>
      expect(args.onReview).toHaveBeenCalledWith(
        expect.objectContaining({ action: "revise" }),
      ),
    );
  },
};

// ---------------------------------------------------------------------------
// The bounds.
// ---------------------------------------------------------------------------

export const EmptyLists: Story = {
  args: { plan: { sub_questions: [], search_queries: [] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    await expect(canvas.getByText(PLAN.noSubQuestions)).toBeInTheDocument();
    await expect(canvas.getByText(PLAN.noArxivQueries)).toBeInTheDocument();
  },
};

/**
 * One column at `MAX_PLAN_ITEMS`, beside one that is not.
 *
 * Both columns at the cap would be forty controlled fields plus an axe pass
 * per story, which is slow enough to be flaky and shows nothing the pair
 * below does not: the state is "this list is full", and having the other
 * column open is what proves the refusal is per-list rather than global.
 */
export const MaxItems: Story = {
  args: {
    plan: {
      sub_questions: Array.from(
        { length: MAX_PLAN_ITEMS },
        (_, index) => `Sub-question ${index + 1}`,
      ),
      search_queries: ["retrieval augmented claim verification"],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    // The cap is `MAX_PLAN_ITEMS` (`schemas.py:26`), refused in the form.
    await expect(
      canvas.getByRole("button", { name: "Add sub-question" }),
    ).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Add arXiv query" })).toBeEnabled();
  },
};

/**
 * One character past the bound — the refusal, not a truncation.
 *
 * The pair with `ItemAtMaxLength`: 500 characters submit, 501 do not, and
 * the 501st is still on screen afterwards. Criterion 3 is that the request
 * is never made, and the play below is where that is visible rather than
 * merely asserted in a unit test.
 */
export const OverLimitRefused: Story = {
  args: {
    plan: {
      sub_questions: ["Which verification architectures are currently used?"],
      search_queries: ["retrieval augmented claim verification"],
    },
    initialDraft: {
      subQuestions: ["x".repeat(MAX_PLAN_ITEM_LEN + 1)],
      searchQueries: ["retrieval augmented claim verification"],
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await form(canvas));
    await expect(await canvas.findByText(/1 character over the limit/)).toBeVisible();
    await expect(args.onReview).not.toHaveBeenCalled();
    await expect(
      (canvas.getByLabelText("Sub-question 1") as HTMLTextAreaElement).value,
    ).toHaveLength(MAX_PLAN_ITEM_LEN + 1);
  },
};

export const ItemAtMaxLength: Story = {
  args: {
    plan: {
      sub_questions: ["x".repeat(MAX_PLAN_ITEM_LEN)],
      search_queries: ["arxiv query at a normal length"],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    // Exactly at the bound is valid; the counter states it and refuses
    // nothing. One more character is the refusal, and it truncates neither.
    await expect(
      canvas.getByText(`${MAX_PLAN_ITEM_LEN} / ${MAX_PLAN_ITEM_LEN}`),
    ).toBeInTheDocument();
  },
};

// ---------------------------------------------------------------------------
// In flight.
// ---------------------------------------------------------------------------

export const Submitting: Story = {
  args: { status: "submitting" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const primary = await form(canvas);
    // Busy, not disabled: the control keeps focus and the tab order rather
    // than vanishing under the user's hands mid-submission.
    await expect(primary).toHaveAttribute("aria-busy", "true");
    await expect(primary).toBeEnabled();
  },
};

export const SubmittingCancel: Story = {
  args: { status: "cancelling" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    await expect(canvas.getByRole("button", { name: PLAN.cancel })).toBeDisabled();
  },
};

/**
 * The 200 that does not mean resumed (`schemas.py:141-160`).
 *
 * Not one of the ten the card names, and it is here anyway: `resolving` is
 * the state criterion 6 is about, and a state nobody can look at is a state
 * nobody reviews.
 */
export const Resolving: Story = {
  args: { status: "resolving" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    await expect(canvas.getByTestId("plan-status-line")).toHaveTextContent(
      PLAN.resolving,
    );
  },
};

// ---------------------------------------------------------------------------
// The two 409s and the 422.
// ---------------------------------------------------------------------------

export const Conflict409: Story = {
  args: { status: "stale" },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const alert = await canvas.findByRole("alert");
    await expect(alert).toHaveTextContent(PLAN.conflict);
    // It refetches rather than dead-ending — on arrival, and again on demand.
    await waitFor(() => expect(args.onRefetch).toHaveBeenCalled());
    await expect(canvas.getByRole("button", { name: PLAN.refresh })).toBeEnabled();
  },
};

export const HitlTimedOut: Story = {
  args: { status: "stale", staleCause: "hitl_timeout" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const alert = await canvas.findByRole("alert");
    // The mapped `error_type` sentence, and still no countdown anywhere:
    // `api_hitl_timeout_sec` is server configuration, not an API field.
    await expect(alert).toHaveTextContent(/not reviewed in time/i);
    await expect(alert.textContent ?? "").not.toMatch(
      /\b\d+\s*(?:minutes?|seconds?)\b/i,
    );
  },
};

export const Validation422: Story = {
  args: {
    issues: [
      {
        path: "plan.search_queries.1",
        message: "String should have at most 500 characters",
        type: "string_too_long",
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    // On the row FastAPI named, and on no other — the baseline mapped
    // nothing at all.
    await waitFor(() =>
      expect(canvas.getByLabelText("arXiv query 2")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    await expect(canvas.getByLabelText("arXiv query 1")).not.toHaveAttribute(
      "aria-invalid",
    );
  },
};

// ---------------------------------------------------------------------------
// The typographic risk, on one screen (03 §3.5, D-010 ruling 8).
// ---------------------------------------------------------------------------

/**
 * The two families side by side, which is the decision to look at.
 *
 * Sub-questions are prose in the UI face and may be rewritten freely; arXiv
 * queries are literal strings in the utility (mono) face and are sent
 * verbatim. If the typeface distinction ever falls, the `aria-describedby`
 * hint under the arXiv column is the only thing carrying it — which is why
 * this story asserts the hint as well as the face.
 */
export const TwoFamilies: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await form(canvas);

    const arxiv = canvas.getByLabelText("arXiv query 1");
    const prose = canvas.getByLabelText("Sub-question 1");
    await expect(arxiv).toHaveAccessibleDescription(
      expect.stringContaining("verbatim"),
    );
    await expect(prose).not.toHaveAccessibleDescription(
      expect.stringContaining("verbatim"),
    );
    // The faces really differ in the rendered result, not only in a class.
    await expect(getComputedStyle(arxiv).fontFamily).not.toBe(
      getComputedStyle(prose).fontFamily,
    );
  },
};
