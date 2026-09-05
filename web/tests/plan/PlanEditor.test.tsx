/**
 * WO-17 criteria 1, 2, 3, 4, 7, 8 and 9, on the rendered surface.
 *
 * Every state is reached by passing props (04 §5.1), so nothing here mocks a
 * network: `onReview` is the surface's ONLY route to one, which is what makes
 * "no request is made" assertable as "this function was not called". The
 * integration half — a real `POST /research/{id}/review` through MSW, the
 * 409 and the 200 — is `web/tests/plan/review.test.tsx`.
 *
 * The fields are behind `React.lazy`, so every test starts by awaiting a row
 * label. That await is not incidental: it is the dynamic-import boundary of
 * criterion 10 being exercised for real in every single case below.
 */

import { beforeAll, describe, expect, it, vi } from "vitest";

import {
  PlanEditor,
  type PlanEditorStatus,
} from "@/components/patterns/PlanEditor";
import {
  normalizeFailure,
  type ApiFailure,
  type FieldIssue,
  type Plan,
} from "@/lib/api";
import { FAILURE_COPY, describeErrorType } from "@/lib/copy/errors";
import { PLAN } from "@/lib/copy/plan";
import { MAX_PLAN_ITEMS, MAX_PLAN_ITEM_LEN } from "@/lib/plan/schema";

import { render, screen, user, waitFor, within } from "../support/render";

const PLAN_FIXTURE: Plan = {
  sub_questions: [
    "Which verification architectures are currently used?",
    "How is evidence provenance preserved?",
  ],
  search_queries: ["retrieval augmented claim verification", "evidence provenance"],
};

interface Options {
  plan?: Plan;
  status?: PlanEditorStatus;
  issues?: readonly FieldIssue[];
  initialDraft?: { subQuestions: string[]; searchQueries: string[] };
  staleCause?: "resolved_elsewhere" | "hitl_timeout";
  failure?: ApiFailure | null;
}

function mount(options: Options = {}) {
  const onReview = vi.fn();
  const onRefetch = vi.fn();
  const result = render(
    <main>
      <PlanEditor
        plan={options.plan ?? PLAN_FIXTURE}
        {...(options.status === undefined ? {} : { status: options.status })}
        {...(options.issues === undefined ? {} : { issues: options.issues })}
        {...(options.initialDraft === undefined
          ? {}
          : { initialDraft: options.initialDraft })}
        {...(options.staleCause === undefined
          ? {}
          : { staleCause: options.staleCause })}
        {...(options.failure === undefined ? {} : { failure: options.failure })}
        onReview={onReview}
        onRefetch={onRefetch}
      />
    </main>,
  );
  return { onReview, onRefetch, ...result };
}

/**
 * The form is behind `React.lazy`; wait for the chunk before asserting.
 *
 * The primary control is what is awaited rather than a row, because a plan
 * with an empty column has no row 1 and the form is still fully rendered.
 */
/**
 * Load the lazy chunk once, before the first test needs it.
 *
 * The boundary is real, so somebody has to pay for crossing it, and under a
 * fully parallel `vitest run` the first transform of React Hook Form and Zod
 * costs seconds — enough to exhaust whichever test happened to go first.
 * Paying it here, in a hook with its own budget, keeps every assertion below
 * about the surface rather than about a module loader.
 */
beforeAll(async () => {
  await import("@/components/patterns/PlanEditorFields");
});

async function awaitForm(): Promise<void> {
  await screen.findByRole(
    "button",
    { name: (name) => name === PLAN.approve || name === PLAN.revise },
    { timeout: 5000 },
  );
}

async function mountLoaded(options: Options = {}) {
  const handle = mount(options);
  await awaitForm();
  return handle;
}

const primary = () => document.querySelectorAll('[data-primary="true"]');

// ---------------------------------------------------------------------------
// Criterion 1 — one primary action.
// ---------------------------------------------------------------------------

describe("criterion 1 — exactly one enabled primary control, in every state", () => {
  const STATES: { name: string; options: Options }[] = [
    { name: "editing, unedited", options: {} },
    {
      name: "editing, edited",
      options: {
        initialDraft: { subQuestions: ["Changed"], searchQueries: ["changed query"] },
      },
    },
    {
      name: "empty lists",
      options: { plan: { sub_questions: [], search_queries: [] } },
    },
    {
      name: "at the item cap",
      options: {
        plan: {
          sub_questions: Array.from({ length: MAX_PLAN_ITEMS }, (_, i) => `q${i}`),
          search_queries: Array.from({ length: MAX_PLAN_ITEMS }, (_, i) => `s${i}`),
        },
      },
    },
    { name: "submitting", options: { status: "submitting" } },
    { name: "cancelling", options: { status: "cancelling" } },
    { name: "resolving", options: { status: "resolving" } },
    {
      name: "a 422 on a row",
      options: {
        issues: [{ path: "plan.sub_questions.0", message: "String is too long" }],
      },
    },
    { name: "a 409 (resolved elsewhere)", options: { status: "stale" } },
    {
      name: "a 409 (the review window closed)",
      options: { status: "stale", staleCause: "hitl_timeout" },
    },
  ];

  it.each(STATES)("$name", async ({ options }) => {
    const handle = mount(options);
    if (options.status === "stale") await screen.findByRole("alert");
    else await awaitForm();

    const controls = primary();
    expect(controls).toHaveLength(1);
    // "Enabled" is the DOM's own word: `busy` leaves the control focusable
    // and announced (WO-07's Button) rather than dropping it out of the tab
    // order mid-submission, so an in-flight primary is still enabled here.
    expect(controls[0]).toBeEnabled();
    handle.unmount();
  });

  it("no other control is styled or marked as primary", async () => {
    await mountLoaded();
    const buttons = screen.getAllByRole("button");
    const marked = buttons.filter(
      (button) => button.getAttribute("data-primary") === "true",
    );
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveAccessibleName(PLAN.approve);
    // The baseline shipped two approve buttons, one always disabled
    // (`PlanReview.tsx:90-106`). Neither of its labels survives.
    expect(screen.queryByRole("button", { name: /approve as-is/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /save edits & approve/i })).toBeNull();
  });

  /**
   * WO-31's RC-03 equivalence table, discharging a retirement nothing pinned.
   *
   * `PlanReview.tsx` shipped a fourth control — Reset — and
   * `tests/PlanReview.test.tsx › Reset restores the original plan after edits`
   * asserted it restored the server's plan and then disabled itself. WO-17's
   * control set is the relabelling primary plus Cancel, and Reset is not in
   * it: 03 §4.6 gives the surface one primary and one destructive escape, and
   * a third "undo" control competing with them is exactly the ambiguity
   * criterion 1 above exists to prevent. The browser's own per-field undo
   * (⌘Z in a textarea) is what a typo needs.
   *
   * That is a deliberate REMOVAL, not an oversight — but until this
   * assertion it was the only one of the three retired controls whose
   * absence nothing recorded, so a later PR could have added it back without
   * any test noticing. Now it cannot.
   */
  it("has no Reset control — the third legacy button, retired with the other two", async () => {
    await mountLoaded();
    for (const name of [/^reset$/i, /^discard$/i, /^revert$/i, /^undo$/i]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });
});

describe("criterion 1 — the label follows the working copy", () => {
  it("reads 'Approve plan' until something changes", async () => {
    await mountLoaded();
    expect(primary()[0]).toHaveAccessibleName(PLAN.approve);
  });

  it("relabels to 'Save edits and approve' on an edit, and back again", async () => {
    const typist = user();
    await mountLoaded();
    const row = screen.getByLabelText("Sub-question 1");

    await typist.type(row, "!");
    await waitFor(() => expect(primary()[0]).toHaveAccessibleName(PLAN.revise));

    await typist.type(row, "{backspace}");
    await waitFor(() => expect(primary()[0]).toHaveAccessibleName(PLAN.approve));
  });

  it("does not relabel for a blank row nobody typed in", async () => {
    const typist = user();
    await mountLoaded();
    await typist.click(screen.getByRole("button", { name: "Add sub-question" }));
    await screen.findByLabelText("Sub-question 3");
    expect(primary()[0]).toHaveAccessibleName(PLAN.approve);
  });

  it("sends approve — with no plan — when nothing changed", async () => {
    const typist = user();
    const { onReview } = await mountLoaded();
    await typist.click(screen.getByRole("button", { name: PLAN.approve }));
    expect(onReview).toHaveBeenCalledTimes(1);
    expect(onReview).toHaveBeenCalledWith({ action: "approve" });
  });

  it("sends revise — with the plan — when something changed", async () => {
    const typist = user();
    const { onReview } = await mountLoaded();
    const row = screen.getByLabelText("arXiv query 1");
    await typist.clear(row);
    await typist.type(row, "faithfulness evaluation");

    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));
    expect(onReview).toHaveBeenCalledWith({
      action: "revise",
      plan: {
        sub_questions: PLAN_FIXTURE.sub_questions,
        search_queries: ["faithfulness evaluation", "evidence provenance"],
      },
    });
  });
});

// ---------------------------------------------------------------------------
// Criterion 2 — cancel.
// ---------------------------------------------------------------------------

describe("criterion 2 — cancel is separated, destructive, and states the cost", () => {
  it("carries the consequence in its own description", async () => {
    await mountLoaded();
    const cancel = screen.getByRole("button", { name: PLAN.cancel });
    expect(cancel).toHaveAccessibleDescription(PLAN.cancelConsequence);
  });

  it("is the last control in the actions row", async () => {
    await mountLoaded();
    const actions = screen.getByRole("button", { name: PLAN.cancel }).parentElement;
    const buttons = within(actions as HTMLElement).getAllByRole("button");
    expect(buttons[buttons.length - 1]).toHaveAccessibleName(PLAN.cancel);
    expect(buttons[0]).toHaveAttribute("data-primary", "true");
  });

  it("is destructive-secondary: critical colour, secondary weight", async () => {
    await mountLoaded();
    const cancel = screen.getByRole("button", { name: PLAN.cancel });
    expect(cancel.className).toContain("border-critical");
    expect(cancel.className).toContain("text-critical-text");
    // Not the filled destructive variant — that is reserved for the primary
    // action of a destructive flow, which this is not.
    expect(cancel.className).not.toContain("bg-critical ");
  });

  it("sends cancel without touching the working copy", async () => {
    const typist = user();
    const { onReview } = await mountLoaded();
    await typist.type(screen.getByLabelText("Sub-question 1"), " edited");
    await typist.click(screen.getByRole("button", { name: PLAN.cancel }));
    expect(onReview).toHaveBeenCalledWith({ action: "cancel" });
  });
});

// ---------------------------------------------------------------------------
// Criterion 3 — the bounds are enforced in the form.
// ---------------------------------------------------------------------------

describe("criterion 3 — 501 characters make no request", () => {
  it("refuses the submission and names the overage on the row", async () => {
    const typist = user();
    const { onReview } = await mountLoaded();
    const row = screen.getByLabelText("Sub-question 1");

    await typist.clear(row);
    await typist.click(row);
    await typist.paste("x".repeat(MAX_PLAN_ITEM_LEN + 1));

    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));

    expect(onReview).not.toHaveBeenCalled();
    expect(await screen.findByText(/1 character over the limit/)).toBeInTheDocument();
    // Refused, not truncated: every character the user pasted is still there.
    expect((row as HTMLTextAreaElement).value).toHaveLength(MAX_PLAN_ITEM_LEN + 1);
  });

  it("accepts exactly the bound", async () => {
    const typist = user();
    const { onReview } = await mountLoaded();
    const row = screen.getByLabelText("Sub-question 1");

    await typist.clear(row);
    await typist.click(row);
    await typist.paste("y".repeat(MAX_PLAN_ITEM_LEN));

    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));
    await waitFor(() => expect(onReview).toHaveBeenCalledTimes(1));
  });

  it("shows the counter without truncating (WO-07's refuse-not-truncate)", async () => {
    const typist = user();
    await mountLoaded();
    const row = screen.getByLabelText("Sub-question 1");
    await typist.clear(row);
    await typist.click(row);
    await typist.paste("z".repeat(MAX_PLAN_ITEM_LEN + 3));
    expect(
      screen.getByText(`${MAX_PLAN_ITEM_LEN + 3} / ${MAX_PLAN_ITEM_LEN}`),
    ).toBeInTheDocument();
  });

  it("refuses a working copy that is already past the cap", async () => {
    // Reachable only from a pre-filled draft — the add control refuses at
    // the cap — so this is the list-level half of the bound, and it lands on
    // the list rather than on any one row.
    const typist = user();
    const { onReview } = await mountLoaded({
      initialDraft: {
        subQuestions: Array.from({ length: MAX_PLAN_ITEMS + 1 }, (_, i) => `q${i}`),
        searchQueries: ["one query"],
      },
    });

    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));
    expect(onReview).not.toHaveBeenCalled();
    expect(
      screen.getAllByText(/This list holds 20 entries at most/).length,
    ).toBeGreaterThan(0);
  });

  it("closes the add control at the item cap and says why", async () => {
    await mountLoaded({
      plan: {
        sub_questions: Array.from({ length: MAX_PLAN_ITEMS }, (_, i) => `question ${i}`),
        search_queries: ["one query"],
      },
    });
    expect(screen.getByRole("button", { name: "Add sub-question" })).toBeDisabled();
    expect(screen.getByText(/This list holds 20 entries at most/)).toBeInTheDocument();
    // The other column is untouched.
    expect(screen.getByRole("button", { name: "Add arXiv query" })).toBeEnabled();
  });
});

// ---------------------------------------------------------------------------
// Criterion 4 — a 422 lands on the row.
// ---------------------------------------------------------------------------

describe("criterion 4 — a 422 maps to the offending row", () => {
  it("puts the message on that row's control, not in a banner", async () => {
    await mountLoaded({
      issues: [
        {
          path: "plan.search_queries.1",
          message: "String should have at most 500 characters",
          type: "string_too_long",
        },
      ],
    });

    const offending = await screen.findByLabelText("arXiv query 2");
    await waitFor(() =>
      expect(offending).toHaveAccessibleDescription(
        expect.stringContaining("String should have at most 500 characters"),
      ),
    );
    expect(offending).toHaveAttribute("aria-invalid", "true");

    // The innocent row is untouched, and no page-level alert appeared.
    expect(screen.getByLabelText("arXiv query 1")).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("states a field it has no row for rather than swallowing it", async () => {
    await mountLoaded({
      issues: [{ path: "plan", message: "revise_requires_plan" }],
    });
    expect(await screen.findByText("revise_requires_plan")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Criterion 7 — revise needs a plan.
// ---------------------------------------------------------------------------

describe("criterion 7 — an emptied list cannot be saved", () => {
  it("refuses and says what is missing, with no request", async () => {
    const typist = user();
    const { onReview } = await mountLoaded();

    await typist.click(screen.getByRole("button", { name: "Remove arXiv query 1" }));
    await typist.click(screen.getByRole("button", { name: "Remove arXiv query 1" }));

    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));
    expect(onReview).not.toHaveBeenCalled();
    expect(screen.getByText(PLAN.emptyPlan)).toBeInTheDocument();
  });

  it("describes the primary control with the reason it refused", async () => {
    const typist = user();
    await mountLoaded({
      plan: { sub_questions: ["only one"], search_queries: ["only one"] },
    });
    await typist.click(screen.getByRole("button", { name: "Remove sub-question 1" }));
    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));
    // `stringContaining` rather than an equality, since WO-S3: the control
    // now also carries `PLAN.cancelHint`, the irreversibility warning that
    // was written by WO-17 and rendered by nothing. The refusal is still
    // there, and is still read first — see `PlanEditorFields`.
    expect(primary()[0]).toHaveAccessibleDescription(
      expect.stringContaining(PLAN.emptyPlan),
    );
  });
});

// ---------------------------------------------------------------------------
// Criterion 8 — the status line.
// ---------------------------------------------------------------------------

describe("criterion 8 — two true facts, and no countdown", () => {
  it("states the pause and the self-stop", async () => {
    await mountLoaded();
    const line = screen.getByTestId("plan-status-line");
    expect(line).toHaveTextContent("paused and not spending");
    expect(line).toHaveTextContent("stops on its own");
  });

  it("shows no clock, no duration and no deadline anywhere on the surface", async () => {
    await mountLoaded();
    const text = document.body.textContent ?? "";
    for (const pattern of [
      /\bcountdown\b/i,
      /\bdeadline\b/i,
      /\b\d+\s*(?:minutes?|seconds?|hours?)\b/i,
      /\b\d{1,2}:\d{2}\b/,
    ]) {
      expect(text).not.toMatch(pattern);
    }
  });

  it("is not a live region — 03 §7.3 allows exactly two, and neither is this", async () => {
    await mountLoaded();
    const line = screen.getByTestId("plan-status-line");
    expect(line).not.toHaveAttribute("role");
    expect(line).not.toHaveAttribute("aria-live");
  });

  it("says the decision was sent, and claims no resumption, on a 200", async () => {
    await mountLoaded({ status: "resolving" });
    expect(screen.getByTestId("plan-status-line")).toHaveTextContent(PLAN.resolving);
    expect(document.body.textContent).not.toMatch(/\bresumed\b/i);
  });
});

// ---------------------------------------------------------------------------
// Criterion 5's surface half — the 409 does not dead-end.
// ---------------------------------------------------------------------------

describe("criterion 5 — a 409 refetches and re-renders", () => {
  it("refetches once on arrival and offers the control again", async () => {
    const { onRefetch } = mount({ status: "stale" });
    await screen.findByRole("alert");
    expect(onRefetch).toHaveBeenCalledTimes(1);

    await user().click(screen.getByRole("button", { name: PLAN.refresh }));
    expect(onRefetch).toHaveBeenCalledTimes(2);
  });

  it("says the truth moved, not that something broke", async () => {
    mount({ status: "stale" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(PLAN.conflict);
    expect(alert).toHaveTextContent(PLAN.conflictRecovery);
  });

  it("names the review window closing when that is what happened", async () => {
    mount({ status: "stale", staleCause: "hitl_timeout" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(describeErrorType("hitl_timeout").sentence);
    // Still no countdown, even in the state the timeout produced.
    expect(alert.textContent ?? "").not.toMatch(/\b\d+\s*(?:minutes?|seconds?)\b/i);
  });

  it("removes the editor rather than leaving a form nobody can submit", async () => {
    mount({ status: "stale" });
    await screen.findByRole("alert");
    expect(screen.queryByLabelText("Sub-question 1")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// WO-S3 — the approval that failed says what failed and what to do.
//
// The composition half — the real machine, the real request layer, and the
// proof that the panel reads `failureSource` at all — is
// `web/tests/features/approveFailure.test.tsx`. This half is the surface's
// own contract: one banner per failure KIND, branched on the code and never
// on a message string, with the fields still mounted underneath it.
// ---------------------------------------------------------------------------

/** One `ApiFailure`, produced by the real normalizer over a real envelope. */
async function failureOf(
  status: number,
  body: unknown,
  headers: Record<string, string> = { "content-type": "application/json" },
): Promise<ApiFailure> {
  return normalizeFailure(new Response(JSON.stringify(body), { status, headers }));
}

describe("WO-S3 — a failed review is stated, one code at a time", () => {
  it("says the workspace is rate limited, with the wait and the ceiling", async () => {
    const failure = await failureOf(
      429,
      { detail: { error: "rate_limited", key_id: "web", limit_per_hour: 1 } },
      { "content-type": "application/json", "retry-after": "3600" },
    );
    await mountLoaded({ failure });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.rate_limited.word);
    expect(alert).toHaveTextContent(FAILURE_COPY.rate_limited.sentence);
    // Both numbers come off the envelope: the wait from `Retry-After`, the
    // ceiling from the body. Neither is invented when the other is missing.
    expect(alert).toHaveTextContent(/about 1 hour/i);
    expect(alert).toHaveTextContent(/1 request an hour/i);
  });

  it("says the server could not complete it, without quoting the server", async () => {
    const failure = await failureOf(500, { detail: "internal_error" });
    await mountLoaded({ failure });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.server_error.sentence);
    expect(alert).toHaveTextContent(FAILURE_COPY.server_error.recovery);
    // RC-16: the raw string is never the primary message.
    expect(alert.textContent ?? "").not.toContain("internal_error");
  });

  it("tells a 502 and a 503 apart, because the remedies differ", async () => {
    const unreachable = await failureOf(502, { detail: "api_upstream_unavailable" });
    const { unmount } = await mountLoaded({ failure: unreachable });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      FAILURE_COPY.upstream_unavailable.sentence,
    );
    unmount();

    const misconfigured = await failureOf(503, { detail: "api_proxy_misconfigured" });
    await mountLoaded({ failure: misconfigured });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.proxy_misconfigured.sentence);
    expect(alert).toHaveTextContent(FAILURE_COPY.proxy_misconfigured.recovery);
  });

  it("keeps the fields — and the working copy — under the banner", async () => {
    const failure = await failureOf(500, { detail: "internal_error" });
    const typist = user();
    await mountLoaded({ failure });

    await screen.findByRole("alert");
    const row = screen.getByLabelText("Sub-question 1");
    expect(row).not.toHaveAttribute("readonly");
    await typist.type(row, "!");
    // Still editable, still submittable: the server never heard the decision,
    // so nothing about the plan has been decided.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: PLAN.revise })).toBeEnabled(),
    );
  });

  it("carries the kind as data, so a sweep need not read copy", async () => {
    const failure = await failureOf(500, { detail: "internal_error" });
    await mountLoaded({ failure });
    await screen.findByRole("alert");
    expect(document.querySelector('[data-surface="plan-editor"]')).toHaveAttribute(
      "data-review-failure",
      "server_error",
    );
  });

  it("does not throw on a severity that may not interrupt", async () => {
    // `role="alert"` is reserved for `warning` and `critical` (03 §7.3) and
    // `StatusBanner` throws otherwise. A review that 404s is `info`, so an
    // unguarded `userTriggered` here would be a thrown render.
    const failure = await failureOf(404, { detail: "job_not_found" });
    await mountLoaded({ failure });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(FAILURE_COPY.not_found.sentence)).toBeVisible();
  });

  it("says nothing extra in the stale state, which has its own banner", async () => {
    const failure = await failureOf(409, {
      detail: "job_not_awaiting_review (status=running)",
    });
    mount({ status: "stale", failure });

    // One banner, not two wordings of one click.
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent(PLAN.conflict);
  });

  it("leaves a field-bearing 422 to the rows (WO-17 criterion 4)", async () => {
    const failure = await failureOf(422, {
      detail: [
        {
          type: "string_too_long",
          loc: ["body", "plan", "search_queries", 1],
          msg: "String should have at most 500 characters",
        },
      ],
    });
    await mountLoaded({
      failure,
      issues: failure.kind === "validation" ? failure.fields : [],
    });

    await waitFor(() =>
      expect(screen.getByLabelText("arXiv query 2")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    // The baseline mapped nothing and shouted; this maps and does not.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("still speaks for a 422 that names no field at all", async () => {
    const failure = await failureOf(422, { detail: "revise_requires_plan" });
    await mountLoaded({ failure });
    // No row to land on is exactly where the silence used to be.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      FAILURE_COPY.validation.sentence,
    );
  });
});

// ---------------------------------------------------------------------------
// WO-S3 — the irreversibility warning, before the commitment.
// ---------------------------------------------------------------------------

describe("WO-S3 — approving is told that it cannot be undone", () => {
  it("puts the hint on screen", async () => {
    await mountLoaded();
    expect(screen.getByText(PLAN.cancelHint)).toBeVisible();
  });

  it("describes the PRIMARY control, which is the act it warns about", async () => {
    await mountLoaded();
    expect(primary()[0]).toHaveAccessibleDescription(
      expect.stringContaining(PLAN.cancelHint),
    );
  });

  it("keeps the cancel control's own consequence separate", async () => {
    await mountLoaded();
    // Criterion 2's description is unchanged: the cancel button still says
    // only what cancelling costs, not what approving costs.
    expect(screen.getByRole("button", { name: PLAN.cancel })).toHaveAccessibleDescription(
      PLAN.cancelConsequence,
    );
  });

  it("still names the form's own refusal beside the control", async () => {
    // The hint must not displace the note: an emptied plan is refused
    // client-side and the reason has to reach the same control.
    const typist = user();
    const { onReview } = await mountLoaded({
      plan: { sub_questions: ["only one"], search_queries: ["only one"] },
    });
    await typist.click(screen.getByRole("button", { name: "Remove sub-question 1" }));
    await typist.click(screen.getByRole("button", { name: PLAN.revise }));

    expect(onReview).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(primary()[0]).toHaveAccessibleDescription(
        expect.stringContaining(PLAN.emptyPlan),
      ),
    );
    expect(primary()[0]).toHaveAccessibleDescription(
      expect.stringContaining(PLAN.cancelHint),
    );
  });
});

// ---------------------------------------------------------------------------
// Criterion 9 — accessibility.
// ---------------------------------------------------------------------------

describe("criterion 9 — visible labels and the arXiv description", () => {
  it("gives every row a visible label, not a placeholder", async () => {
    await mountLoaded();
    for (const name of ["Sub-question 1", "Sub-question 2"]) {
      const row = screen.getByLabelText(name);
      const label = document.querySelector(`label[for="${row.id}"]`);
      expect(label).not.toBeNull();
      expect(label).toHaveTextContent(name);
      // A visible label: not clipped by the visually-hidden utility.
      expect(label?.className).not.toContain("ew-visually-hidden");
      expect(row).not.toHaveAttribute("placeholder");
    }
  });

  it("points every arXiv row at one hint that says the strings go to arXiv verbatim", async () => {
    await mountLoaded();
    const first = screen.getByLabelText("arXiv query 1");
    const second = screen.getByLabelText("arXiv query 2");
    const hintId = (first.getAttribute("aria-describedby") ?? "").split(" ")[0];

    expect(hintId).toBeTruthy();
    expect(second.getAttribute("aria-describedby")).toContain(hintId as string);
    expect(document.getElementById(hintId as string)).toHaveTextContent(
      PLAN.arxivQueriesHint,
    );
    expect(first).toHaveAccessibleDescription(
      expect.stringContaining("sent to arXiv verbatim"),
    );
  });

  it("does not attach the arXiv description to the sub-question column", async () => {
    await mountLoaded();
    expect(screen.getByLabelText("Sub-question 1")).not.toHaveAccessibleDescription(
      expect.stringContaining("arXiv"),
    );
  });

  it("keeps the counter reachable alongside the hint", async () => {
    await mountLoaded();
    expect(screen.getByLabelText("arXiv query 1")).toHaveAccessibleDescription(
      expect.stringContaining(`/ ${MAX_PLAN_ITEM_LEN}`),
    );
  });
});

describe("criterion 9 — the two families, and the row semantics", () => {
  it("sets the arXiv column in the mono face and the sub-questions in the UI face", async () => {
    await mountLoaded();
    const columns = document.querySelectorAll("[data-list]");
    expect(columns).toHaveLength(2);
    expect(document.querySelector('[data-list="subQuestions"]')).toHaveAttribute(
      "data-family",
      "ui",
    );
    const arxiv = document.querySelector('[data-list="searchQueries"]');
    expect(arxiv).toHaveAttribute("data-family", "mono");
    // The typeface itself, applied to the control rather than to the row.
    const wrapper = screen.getByLabelText("arXiv query 1").closest("div");
    expect(wrapper?.className ?? "").toContain("[&_textarea]:font-mono");
  });

  it("renders real list items, which is the baseline's listitem violation gone", async () => {
    await mountLoaded();
    const lists = screen.getAllByRole("list");
    expect(lists).toHaveLength(2);
    for (const list of lists) {
      expect(list.tagName).toBe("UL");
      expect(list).not.toHaveAttribute("role");
      for (const item of within(list).getAllByRole("listitem")) {
        expect(item.tagName).toBe("LI");
      }
    }
  });

  it("names each column with a real legend", async () => {
    await mountLoaded();
    expect(
      screen.getByRole("group", { name: PLAN.subQuestionsLabel }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: PLAN.arxivQueriesLabel }),
    ).toBeInTheDocument();
  });

  it("is a named region, so its content sits inside a landmark", async () => {
    await mountLoaded();
    // `region` and `landmark-one-main` are the two page-level rules in the
    // baseline's five; the surface's own contribution to them is to be a
    // named region rather than an anonymous div.
    expect(screen.getByRole("region", { name: PLAN.heading })).toBeInTheDocument();
  });
});

describe("criterion 9 — remove buttons and focus (03 §7.2)", () => {
  it("keeps a stable accessible name per row", async () => {
    await mountLoaded();
    expect(screen.getByRole("button", { name: "Remove sub-question 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove sub-question 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove arXiv query 1" })).toBeInTheDocument();
  });

  it("carries the target policy that makes it 24px, and 44px on a coarse pointer", async () => {
    await mountLoaded();
    const remove = screen.getByRole("button", { name: "Remove sub-question 1" });
    const add = screen.getByRole("button", { name: "Add sub-question" });
    // WO-07's `ew-target` is the single knob; `primitives.css` lifts every
    // modifier to `--size-target-coarse` under `(pointer: coarse)`.
    for (const control of [remove, add]) {
      expect(control.className).toContain("ew-target");
      expect(control.className).toContain("ew-target--md");
    }
  });

  it("moves focus to the next row when a row is removed", async () => {
    const typist = user();
    await mountLoaded({
      plan: {
        sub_questions: ["first", "second", "third"],
        search_queries: ["only query"],
      },
    });
    await typist.click(screen.getByRole("button", { name: "Remove sub-question 1" }));

    await waitFor(() => {
      // The row that took the removed row's index — "second" — now holds
      // position 1 and the caret.
      const focused = document.activeElement as HTMLTextAreaElement | null;
      expect(focused?.value).toBe("second");
    });
  });

  it("moves focus to the new last row when the last one is removed", async () => {
    const typist = user();
    await mountLoaded({
      plan: { sub_questions: ["first", "second"], search_queries: ["only query"] },
    });
    await typist.click(screen.getByRole("button", { name: "Remove sub-question 2" }));

    await waitFor(() => {
      const focused = document.activeElement as HTMLTextAreaElement | null;
      expect(focused?.value).toBe("first");
    });
  });

  it("moves focus to the add control when the list empties", async () => {
    const typist = user();
    await mountLoaded({
      plan: { sub_questions: ["only one"], search_queries: ["only query"] },
    });
    await typist.click(screen.getByRole("button", { name: "Remove sub-question 1" }));

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Add sub-question" }),
      ),
    );
    // And the empty column says so rather than rendering a bare gap.
    expect(screen.getByText(PLAN.noSubQuestions)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// In-flight and read-only states.
// ---------------------------------------------------------------------------

describe("the in-flight states do not lose the keyboard", () => {
  it.each(["submitting", "cancelling", "resolving"] as const)(
    "%s keeps the primary focusable and refuses a second press",
    async (status) => {
      const typist = user();
      const { onReview } = await mountLoaded({ status });
      const control = primary()[0] as HTMLButtonElement;

      expect(control).toHaveAttribute("aria-busy", "true");
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).toBeEnabled();

      await typist.click(control);
      expect(onReview).not.toHaveBeenCalled();
    },
  );

  it("makes the rows read-only rather than disabled, so focus survives", async () => {
    await mountLoaded({ status: "submitting" });
    const row = screen.getByLabelText("Sub-question 1");
    expect(row).toHaveAttribute("readonly");
    expect(row).toBeEnabled();
    expect(screen.getByRole("button", { name: "Add sub-question" })).toBeDisabled();
  });
});

describe("the plan on screen is the plan the server sent", () => {
  it("renders every entry, from props alone", async () => {
    await mountLoaded();
    expect(screen.getByLabelText("Sub-question 1")).toHaveValue(
      PLAN_FIXTURE.sub_questions[0],
    );
    expect(screen.getByLabelText("arXiv query 2")).toHaveValue(
      PLAN_FIXTURE.search_queries[1],
    );
  });

  it("opens on a supplied working copy when there is one", async () => {
    await mountLoaded({
      initialDraft: { subQuestions: ["restored"], searchQueries: ["restored query"] },
    });
    expect(screen.getByLabelText("Sub-question 1")).toHaveValue("restored");
    // And it reads as edited, because it differs from the server's plan.
    expect(primary()[0]).toHaveAccessibleName(PLAN.revise);
  });

  it("says so when a column arrives empty", async () => {
    await mountLoaded({
      plan: { sub_questions: ["one"], search_queries: [] },
    });
    expect(screen.getByText(PLAN.noArxivQueries)).toBeInTheDocument();
  });
});
