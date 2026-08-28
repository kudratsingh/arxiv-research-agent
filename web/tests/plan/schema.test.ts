/**
 * WO-17 criteria 3, 4 and 7, at the level where they are decidable without a
 * DOM: the bounds, the 422 mapping, and the rule that builds a request.
 *
 * THE BOUNDS ARE RE-DERIVED FROM PYTHON ON EVERY RUN. `MAX_PLAN_ITEMS` and
 * `MAX_PLAN_ITEM_LEN` appear in no OpenAPI schema — `PlanItem` is an
 * `Annotated[str, Field(max_length=...)]` and the list cap is enforced by a
 * validator (`src/api/schemas.py:26-27`) — so nothing generates the
 * frontend's view of them and a transcribed pair would drift the day
 * somebody widens the cap. This is the same technique
 * `web/tests/copy/errorTypeDrift.test.ts` uses for the `error_type`
 * vocabulary, for the same reason: the check belongs on the side that would
 * otherwise silently send a request the server refuses.
 *
 * The Zod schema is checked against the pure `planIssues` implementation
 * rather than against a restatement of the bounds, which is what makes
 * "written twice on purpose" safe: if the two ever disagree, this file says
 * so.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";
import * as ZodModule from "zod";

import type { FieldIssue, Plan } from "@/lib/api";
import {
  MAX_PLAN_ITEMS,
  MAX_PLAN_ITEM_LEN,
  PLAN_LISTS,
  PLAN_LIST_SPECS,
  buildPlanSchema,
  cancelRequest,
  draftToPlan,
  draftToValues,
  isEdited,
  isListFull,
  mapFieldIssue,
  mapFieldIssues,
  planEquals,
  planIssues,
  planToDraft,
  reviewRequestFor,
  valuesToDraft,
  type PlanDraft,
} from "@/lib/plan/schema";

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const SCHEMAS_PY = readFileSync(
  path.join(REPO_ROOT, "src", "api", "schemas.py"),
  "utf8",
);

/** `NAME = 20` or `NAME = 8_000`, as Python writes it. */
function pythonConstant(name: string): number {
  const match = new RegExp(`^${name}\\s*=\\s*([0-9_]+)\\s*$`, "m").exec(SCHEMAS_PY);
  if (match === null) throw new Error(`${name} is not assigned in src/api/schemas.py`);
  return Number((match[1] as string).replaceAll("_", ""));
}

const PLAN_FIXTURE: Plan = {
  sub_questions: ["Which verification architectures are used?", "How is provenance kept?"],
  search_queries: ["retrieval augmented claim verification", "evidence provenance"],
};

function draft(over: Partial<PlanDraft> = {}): PlanDraft {
  return { ...planToDraft(PLAN_FIXTURE), ...over };
}

// ---------------------------------------------------------------------------
// Criterion 3 — the bounds are the server's.
// ---------------------------------------------------------------------------

describe("criterion 3 — client bounds mirror src/api/schemas.py exactly", () => {
  it("MAX_PLAN_ITEMS is the Python value, read from the file", () => {
    expect(MAX_PLAN_ITEMS).toBe(pythonConstant("MAX_PLAN_ITEMS"));
    // Belt and braces: the value at the time of writing, so a change in BOTH
    // places is still visible in a diff of this file.
    expect(MAX_PLAN_ITEMS).toBe(20);
  });

  it("MAX_PLAN_ITEM_LEN is the Python value, read from the file", () => {
    expect(MAX_PLAN_ITEM_LEN).toBe(pythonConstant("MAX_PLAN_ITEM_LEN"));
    expect(MAX_PLAN_ITEM_LEN).toBe(500);
  });

  it("the Python bound is the one applied to a plan entry", () => {
    // `PlanItem = Annotated[str, Field(max_length=MAX_PLAN_ITEM_LEN)]` — if
    // the entry type stops referencing the constant, mirroring the constant
    // stops meaning anything.
    expect(SCHEMAS_PY).toMatch(
      /PlanItem\s*=\s*Annotated\[str,\s*Field\(max_length=MAX_PLAN_ITEM_LEN\)\]/,
    );
  });
});

describe("criterion 3 — an over-length entry is refused, never truncated", () => {
  const tooLong = "x".repeat(MAX_PLAN_ITEM_LEN + 1);

  it("reports the row and the overage", () => {
    const issues = planIssues(draft({ subQuestions: [tooLong] }));
    expect(issues).toEqual([
      {
        list: "subQuestions",
        index: 0,
        code: "too_long",
        message: expect.stringContaining("1 character over the limit"),
      },
    ]);
  });

  it("accepts exactly the bound", () => {
    const atLimit = "x".repeat(MAX_PLAN_ITEM_LEN);
    expect(planIssues(draft({ subQuestions: [atLimit] }))).toEqual([]);
  });

  it("builds no request at all", () => {
    const submission = reviewRequestFor(
      PLAN_FIXTURE,
      draft({ subQuestions: [tooLong] }),
    );
    expect(submission.ok).toBe(false);
    expect(submission.ok === false && submission.refusal).toBe("bounds");
  });

  it("keeps every character the user typed", () => {
    // Refuse, don't truncate: the draft is unchanged by validating it.
    const value = draft({ subQuestions: [tooLong] });
    planIssues(value);
    expect(value.subQuestions[0]).toHaveLength(MAX_PLAN_ITEM_LEN + 1);
  });
});

describe("criterion 3 — the item cap", () => {
  const many = Array.from({ length: MAX_PLAN_ITEMS + 2 }, (_, i) => `q${i}`);

  it("reports a list-level issue, not a row one", () => {
    const issues = planIssues(draft({ searchQueries: many }));
    expect(issues).toEqual([
      {
        list: "searchQueries",
        index: null,
        code: "too_many",
        // One sentence for both sides of the cap: at it, and past it.
        message: expect.stringContaining("holds 20 entries at most"),
      },
    ]);
  });

  it("closes the add control at the cap, not one past it", () => {
    const full = Array.from({ length: MAX_PLAN_ITEMS }, (_, i) => `q${i}`);
    expect(isListFull(draft({ subQuestions: full }), "subQuestions")).toBe(true);
    expect(isListFull(draft({ subQuestions: full.slice(1) }), "subQuestions")).toBe(
      false,
    );
  });
});

// ---------------------------------------------------------------------------
// Criterion 1's relabel condition, and criterion 7.
// ---------------------------------------------------------------------------

describe("criterion 1 — the action is derived, never chosen", () => {
  it("sends approve, with no plan, when nothing changed", () => {
    const submission = reviewRequestFor(PLAN_FIXTURE, draft());
    expect(submission).toEqual({ ok: true, request: { action: "approve" } });
    expect(submission.ok === true && "plan" in submission.request).toBe(false);
  });

  it("sends revise, with the plan, when something changed", () => {
    const submission = reviewRequestFor(
      PLAN_FIXTURE,
      draft({ subQuestions: ["A different question"] }),
    );
    expect(submission.ok).toBe(true);
    expect(submission.ok === true && submission.request).toEqual({
      action: "revise",
      plan: {
        sub_questions: ["A different question"],
        search_queries: PLAN_FIXTURE.search_queries,
      },
    });
  });

  it("does not count a blank row as an edit", () => {
    // Pressing Add and typing nothing changes nothing that would be sent, so
    // the primary control must not start offering to save it.
    const withBlank = draft({
      subQuestions: [...PLAN_FIXTURE.sub_questions, "   "],
    });
    expect(isEdited(PLAN_FIXTURE, withBlank)).toBe(false);
    expect(reviewRequestFor(PLAN_FIXTURE, withBlank)).toEqual({
      ok: true,
      request: { action: "approve" },
    });
  });

  it("counts a reorder as an edit", () => {
    const reordered = draft({
      subQuestions: [...PLAN_FIXTURE.sub_questions].reverse(),
    });
    expect(isEdited(PLAN_FIXTURE, reordered)).toBe(true);
  });
});

describe("criterion 7 — revise cannot be submitted without a plan", () => {
  it("refuses when the sub-questions would be empty", () => {
    const submission = reviewRequestFor(PLAN_FIXTURE, draft({ subQuestions: [] }));
    expect(submission).toEqual({ ok: false, refusal: "empty_plan", issues: [] });
  });

  it("refuses when the arXiv queries would be empty", () => {
    const submission = reviewRequestFor(
      PLAN_FIXTURE,
      draft({ searchQueries: ["  "] }),
    );
    expect(submission).toEqual({ ok: false, refusal: "empty_plan", issues: [] });
  });

  it("refuses when both are empty", () => {
    const submission = reviewRequestFor(
      PLAN_FIXTURE,
      { subQuestions: [], searchQueries: [] },
    );
    expect(submission.ok).toBe(false);
  });

  it("still allows approve on a plan the server already holds", () => {
    // An empty plan that was never edited is the server's own; approving it
    // sends no plan at all, so `revise_requires_plan` cannot be reached.
    const empty: Plan = { sub_questions: [], search_queries: [] };
    expect(reviewRequestFor(empty, planToDraft(empty))).toEqual({
      ok: true,
      request: { action: "approve" },
    });
  });

  it("cancel ignores the working copy entirely", () => {
    expect(cancelRequest()).toEqual({ action: "cancel" });
  });
});

// ---------------------------------------------------------------------------
// Criterion 4 — 422 → row.
// ---------------------------------------------------------------------------

describe("criterion 4 — a 422 maps onto the offending row", () => {
  it.each([
    ["plan.sub_questions.0", "subQuestions", 0],
    ["plan.search_queries.3", "searchQueries", 3],
    ["sub_questions.11", "subQuestions", 11],
  ] as const)("%s → %s[%i]", (wire, list, index) => {
    expect(mapFieldIssue({ path: wire, message: "too long" })).toEqual({
      list,
      index,
      message: "too long",
    });
  });

  it("keeps the backend's discriminator when it sent one", () => {
    expect(
      mapFieldIssue({
        path: "plan.sub_questions.1",
        message: "String should have at most 500 characters",
        type: "string_too_long",
      }),
    ).toEqual({
      list: "subQuestions",
      index: 1,
      message: "String should have at most 500 characters",
      type: "string_too_long",
    });
  });

  it.each([
    "",
    "plan",
    "plan.sub_questions",
    "plan.sub_questions.x",
    "query",
    "plan.unknown_field.0",
  ])("does not invent a row for %s", (wire) => {
    expect(mapFieldIssue({ path: wire, message: "nope" })).toBeNull();
  });

  it("splits a body into rows and the rest, swallowing neither", () => {
    const fields: FieldIssue[] = [
      { path: "plan.sub_questions.0", message: "too long" },
      { path: "plan", message: "revise_requires_plan" },
      { path: "plan.search_queries.1", message: "too long" },
    ];
    const { rows, unmapped } = mapFieldIssues(fields);
    expect(rows).toHaveLength(2);
    expect(unmapped).toEqual([{ path: "plan", message: "revise_requires_plan" }]);
  });
});

// ---------------------------------------------------------------------------
// The Zod schema, against the pure rules.
// ---------------------------------------------------------------------------

describe("the Zod schema and planIssues agree", () => {
  const schema = buildPlanSchema(ZodModule.z);

  const CASES: { name: string; value: PlanDraft }[] = [
    { name: "a clean plan", value: draft() },
    { name: "an over-length row", value: draft({ subQuestions: ["y".repeat(501)] }) },
    {
      name: "an at-limit row",
      value: draft({ searchQueries: ["y".repeat(MAX_PLAN_ITEM_LEN)] }),
    },
    {
      name: "too many rows",
      value: draft({ searchQueries: Array.from({ length: 21 }, (_, i) => `q${i}`) }),
    },
    { name: "empty lists", value: { subQuestions: [], searchQueries: [] } },
  ];

  it.each(CASES)("$name: the same verdict, and the same messages", ({ value }) => {
    const parsed = schema.safeParse(draftToValues(value));
    const pure = planIssues(value);
    expect(parsed.success).toBe(pure.length === 0);
    if (parsed.success) return;
    expect(parsed.error.issues.map((issue) => issue.message).sort()).toEqual(
      pure.map((issue) => issue.message).sort(),
    );
  });

  it("puts a row issue on the row's own path", () => {
    const parsed = schema.safeParse(
      draftToValues(draft({ subQuestions: ["ok", "z".repeat(501)] })),
    );
    expect(parsed.success).toBe(false);
    if (parsed.success) return;
    expect(parsed.error.issues[0]?.path).toEqual(["subQuestions", 1, "value"]);
  });

  it("puts a list issue on the list's own path", () => {
    const parsed = schema.safeParse(
      draftToValues(draft({ subQuestions: Array.from({ length: 21 }, () => "q") })),
    );
    expect(parsed.success).toBe(false);
    if (parsed.success) return;
    expect(parsed.error.issues[0]?.path).toEqual(["subQuestions"]);
  });
});

// ---------------------------------------------------------------------------
// Shape conversions.
// ---------------------------------------------------------------------------

describe("the working copy round-trips", () => {
  it("plan → draft → plan is the identity for a clean plan", () => {
    expect(draftToPlan(planToDraft(PLAN_FIXTURE))).toEqual(PLAN_FIXTURE);
  });

  it("draft → form values → draft is the identity", () => {
    const value = draft();
    expect(valuesToDraft(draftToValues(value))).toEqual(value);
  });

  it("survives a field array that has not populated yet", () => {
    expect(valuesToDraft({})).toEqual({ subQuestions: [], searchQueries: [] });
    expect(valuesToDraft({ subQuestions: [undefined, { value: "a" }] })).toEqual({
      subQuestions: ["", "a"],
      searchQueries: [],
    });
  });

  it("copies the arrays rather than aliasing the server's", () => {
    const value = planToDraft(PLAN_FIXTURE);
    value.subQuestions.push("mutated");
    expect(PLAN_FIXTURE.sub_questions).toHaveLength(2);
  });

  it("compares plans as the wire would see them", () => {
    expect(planEquals(PLAN_FIXTURE, { ...PLAN_FIXTURE })).toBe(true);
    expect(
      planEquals(PLAN_FIXTURE, { ...PLAN_FIXTURE, search_queries: [] }),
    ).toBe(false);
  });
});

describe("the column table", () => {
  it("covers both lists and nothing else", () => {
    expect(Object.keys(PLAN_LIST_SPECS).sort()).toEqual([...PLAN_LISTS].sort());
  });

  it("puts the arXiv column in the mono family and describes its rows", () => {
    // 03 §3.5's two families, and D-010 ruling 8's fallback: the arXiv
    // column — and only it — points every row at the shared hint.
    expect(PLAN_LIST_SPECS.searchQueries.family).toBe("mono");
    expect(PLAN_LIST_SPECS.searchQueries.describesRows).toBe(true);
    expect(PLAN_LIST_SPECS.subQuestions.family).toBe("ui");
    expect(PLAN_LIST_SPECS.subQuestions.describesRows).toBe(false);
  });

  it("names the wire fields the API uses", () => {
    expect(PLAN_LIST_SPECS.subQuestions.wire).toBe("sub_questions");
    expect(PLAN_LIST_SPECS.searchQueries.wire).toBe("search_queries");
  });
});
