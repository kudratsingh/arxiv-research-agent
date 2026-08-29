// The plan editor's bounds, its working copy, and the rules that decide
// what — if anything — gets sent (04 §4.5, WO-17 criteria 3, 4, 7).
//
// NOTHING HERE IMPORTS ZOD AT RUNTIME. `buildPlanSchema` takes the Zod
// namespace as an argument and `import type` is erased by the compiler, so
// this module carries no edge to `zod` in the module graph. That is what
// lets the outer `PlanEditor` — which is on the `/c/[id]` first-load path —
// use `isEdited`, the bounds and the 422 mapping without dragging Zod into
// the route's chunk union (04 §8.1, R-11). The lazily-loaded
// `PlanEditorFields` is the only module that imports Zod for real, and
// `web/tests/plan/bundle.test.ts` proves the boundary from the import graph
// and, when a production build is present, from the route manifests.
//
// THE BOUNDS ARE THE SERVER'S, NOT A CLIENT PREFERENCE.
// `web/tests/plan/schema.test.ts` re-derives both numbers from
// `src/api/schemas.py` on every run, the way WO-12's error_type drift test
// re-derives its vocabulary from Python, so "mirror the server exactly"
// stays a fact rather than a comment.
//
// EVERY DECISION IN THIS FILE IS A PURE FUNCTION. The component decides
// nothing about validity on its own: it renders what `planIssues` and
// `reviewRequestFor` return. That is what makes WO-17 criterion 3's claim —
// 501 characters produce no request — provable without a DOM.

import type * as ZodModule from "zod";

import type { FieldIssue, Plan, ReviewRequest } from "@/lib/api";
import {
  ADD_ARXIV_QUERY,
  ADD_SUB_QUESTION,
  PLAN,
  arxivQueryLabel,
  atItemLimit,
  overItemLength,
  removeArxivQuery,
  removeSubQuestion,
  subQuestionLabel,
} from "@/lib/copy/plan";

/**
 * The Zod namespace as a TYPE ONLY.
 *
 * `import type` is erased by the compiler, so the import above creates no
 * edge to `zod` in the module graph a bundler walks — which is the whole
 * reason the schema is a factory over an injected namespace rather than a
 * module-level constant. `typeof ZodModule.z` rather than `typeof
 * ZodModule`: the package root re-exports the classic namespace under `z`,
 * and that is the object `PlanEditorFields` imports and hands in.
 */
type Zod = typeof ZodModule.z;

// ---------------------------------------------------------------------------
// The bounds (`src/api/schemas.py:26-27`).
// ---------------------------------------------------------------------------

/** `MAX_PLAN_ITEMS` — the cap on either list. */
export const MAX_PLAN_ITEMS = 20;

/** `MAX_PLAN_ITEM_LEN` — the cap on one entry, in characters. */
export const MAX_PLAN_ITEM_LEN = 500;

// ---------------------------------------------------------------------------
// The working copy.
// ---------------------------------------------------------------------------

/**
 * The two lists, in the form the editor holds them.
 *
 * Named in the client's own camelCase rather than the wire's snake_case so
 * that a form path (`subQuestions.0.value`) can never be mistaken for a
 * server path (`plan.sub_questions.0`) — the 422 mapping below translates
 * between them in exactly one place.
 */
export interface PlanDraft {
  subQuestions: string[];
  searchQueries: string[];
}

export const PLAN_LISTS = ["subQuestions", "searchQueries"] as const;

export type PlanListKey = (typeof PLAN_LISTS)[number];

/** Everything that differs between the two columns, in one table. */
export interface PlanListSpec {
  key: PlanListKey;
  /** The field name in `Plan` (`schemas.py:63-76`). */
  wire: "sub_questions" | "search_queries";
  /**
   * Which family the column is set in (03 §3.5). `ui` is prose the user may
   * rewrite; `mono` is a literal string that goes to arXiv as typed. The
   * typeface is the visual carrier of that distinction and the column hint
   * is the carrier for everyone it cannot reach (D-010 ruling 8).
   */
  family: "ui" | "mono";
  /**
   * Does every row in this column carry the column hint as its
   * `aria-describedby`? True for the arXiv column, and only for it: that is
   * the sentence D-010 ruling 8 made load-bearing.
   */
  describesRows: boolean;
  columnLabel: string;
  columnHint: string;
  emptyNote: string;
  rowLabel: (position: number) => string;
  removeLabel: (position: number) => string;
  addLabel: string;
}

export const PLAN_LIST_SPECS: Record<PlanListKey, PlanListSpec> = {
  subQuestions: {
    key: "subQuestions",
    wire: "sub_questions",
    family: "ui",
    describesRows: false,
    columnLabel: PLAN.subQuestionsLabel,
    columnHint: PLAN.subQuestionsHint,
    emptyNote: PLAN.noSubQuestions,
    rowLabel: subQuestionLabel,
    removeLabel: removeSubQuestion,
    addLabel: ADD_SUB_QUESTION,
  },
  searchQueries: {
    key: "searchQueries",
    wire: "search_queries",
    family: "mono",
    describesRows: true,
    columnLabel: PLAN.arxivQueriesLabel,
    columnHint: PLAN.arxivQueriesHint,
    emptyNote: PLAN.noArxivQueries,
    rowLabel: arxivQueryLabel,
    removeLabel: removeArxivQuery,
    addLabel: ADD_ARXIV_QUERY,
  },
};

/** Wire path segment → list key, for the 422 mapping. */
const WIRE_TO_LIST: Record<string, PlanListKey> = {
  sub_questions: "subQuestions",
  search_queries: "searchQueries",
};

/** `JobDetail.plan` → the working copy. Never mutates the argument. */
export function planToDraft(plan: Plan): PlanDraft {
  return {
    subQuestions: [...(plan.sub_questions ?? [])],
    searchQueries: [...(plan.search_queries ?? [])],
  };
}

/**
 * The working copy → the plan that would be sent.
 *
 * Blank rows are dropped rather than sent: an entry a user added and never
 * filled in is not a sub-question, and the alternative — refusing the whole
 * submission because an empty row exists — turns "Add" into a trap. Nothing
 * else is normalised; the strings are the user's, including their spacing,
 * because the arXiv column is sent verbatim.
 */
export function draftToPlan(draft: PlanDraft): Plan {
  return {
    sub_questions: draft.subQuestions.filter((entry) => entry.trim() !== ""),
    search_queries: draft.searchQueries.filter((entry) => entry.trim() !== ""),
  };
}

function sameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((entry, index) => entry === b[index]);
}

/** Two plans, compared as the wire would see them. */
export function planEquals(a: Plan, b: Plan): boolean {
  return (
    sameList(a.sub_questions ?? [], b.sub_questions ?? []) &&
    sameList(a.search_queries ?? [], b.search_queries ?? [])
  );
}

/**
 * Does the working copy differ from what the server already holds?
 *
 * Compared AFTER blank rows are dropped, which is what makes the primary
 * button's label honest: pressing "Add" and typing nothing changes nothing
 * that would be sent, so the control must not start offering to save it.
 * This is the whole of WO-17 criterion 1's relabel condition.
 */
export function isEdited(original: Plan, draft: PlanDraft): boolean {
  return !planEquals(original, draftToPlan(draft));
}

// ---------------------------------------------------------------------------
// Client-side bounds. Criterion 3: over-length input is blocked in the form,
// never surfaced as a 422.
// ---------------------------------------------------------------------------

export type PlanIssueCode = "too_long" | "too_many";

/** One problem, addressed to one row or to one list. */
export interface PlanIssue {
  list: PlanListKey;
  /** `null` when the problem belongs to the list rather than to a row. */
  index: number | null;
  code: PlanIssueCode;
  message: string;
}

/**
 * Every bound violation in a draft, in reading order.
 *
 * This is the same rule set `buildPlanSchema` hands to React Hook Form's
 * resolver — written twice on purpose, and asserted equivalent in
 * `web/tests/plan/schema.test.ts`, because the resolver's copy runs inside
 * the lazily-loaded chunk and this one has to be callable from anywhere,
 * including from a test that never mounts a component.
 */
export function planIssues(draft: PlanDraft): PlanIssue[] {
  const issues: PlanIssue[] = [];
  for (const list of PLAN_LISTS) {
    const entries = draft[list];
    entries.forEach((entry, index) => {
      if (entry.length > MAX_PLAN_ITEM_LEN) {
        issues.push({
          list,
          index,
          code: "too_long",
          message: overItemLength(entry.length - MAX_PLAN_ITEM_LEN),
        });
      }
    });
    if (entries.length > MAX_PLAN_ITEMS) {
      issues.push({
        list,
        index: null,
        code: "too_many",
        message: atItemLimit(MAX_PLAN_ITEMS),
      });
    }
  }
  return issues;
}

/**
 * Is this list already at the server's cap? Then `Add` is unavailable.
 *
 * Named apart from `atItemLimit` in `lib/copy/plan.ts` deliberately: that
 * one is the sentence, this one is the fact, and the editor imports both.
 */
export function isListFull(draft: PlanDraft, list: PlanListKey): boolean {
  return draft[list].length >= MAX_PLAN_ITEMS;
}

// ---------------------------------------------------------------------------
// What gets sent.
// ---------------------------------------------------------------------------

/** Why a submission was refused before any request was made. */
export type PlanRefusal = "bounds" | "empty_plan";

export type PlanSubmission =
  | { ok: true; request: ReviewRequest }
  | { ok: false; refusal: PlanRefusal; issues: PlanIssue[] };

/**
 * The whole submit decision, as a pure function.
 *
 * Three contract facts are encoded here and nowhere else:
 *
 *   - **One intent, one control** (criterion 1). The action is derived from
 *     the working copy, never chosen by the user: identical to the server's
 *     plan sends `approve`, anything else sends `revise`.
 *   - **Bounds are refused, not truncated** (criterion 3). A draft that
 *     violates `MAX_PLAN_ITEM_LEN` or `MAX_PLAN_ITEMS` returns `ok: false`,
 *     so the caller has nothing to send.
 *   - **`revise` requires a plan** (criterion 7, `routes.py:265-269`). A
 *     draft whose non-blank rows would leave either list empty cannot be
 *     saved; the request that would 422 is never built.
 *
 * `approve` deliberately carries no `plan` field: the server already has
 * one, and sending it back would make an unedited approval indistinguishable
 * from a revision on the wire.
 */
export function reviewRequestFor(
  original: Plan,
  draft: PlanDraft,
): PlanSubmission {
  const issues = planIssues(draft);
  if (issues.length > 0) return { ok: false, refusal: "bounds", issues };

  if (!isEdited(original, draft)) {
    return { ok: true, request: { action: "approve" } };
  }

  const plan = draftToPlan(draft);
  if (plan.sub_questions.length === 0 || plan.search_queries.length === 0) {
    return { ok: false, refusal: "empty_plan", issues: [] };
  }
  return { ok: true, request: { action: "revise", plan } };
}

/** The cancel request. Separate because it ignores the working copy entirely. */
export function cancelRequest(): ReviewRequest {
  return { action: "cancel" };
}

// ---------------------------------------------------------------------------
// 422 → row (criterion 4).
// ---------------------------------------------------------------------------

/** A server field issue, resolved onto a row of the editor. */
export interface MappedFieldIssue {
  list: PlanListKey;
  index: number;
  message: string;
  type?: string;
}

/**
 * `plan.sub_questions.0` → `{ list: "subQuestions", index: 0 }`.
 *
 * `normalizeFailure` has already dropped FastAPI's `body` prefix
 * (`lib/api/errors.ts`), so the paths this sees are `plan.<field>.<index>`.
 * A `plan` prefix is optional because `ReviewRequest.plan` is nested but a
 * future flattening would keep the same leaf names, and anything that does
 * not resolve to a row returns `null` rather than being silently dropped —
 * the caller shows those instead of swallowing them.
 */
export function mapFieldIssue(issue: FieldIssue): MappedFieldIssue | null {
  const segments = issue.path.split(".").filter((segment) => segment !== "");
  const start = segments[0] === "plan" ? 1 : 0;
  const field = segments[start];
  const position = segments[start + 1];
  if (field === undefined || position === undefined) return null;
  const list = WIRE_TO_LIST[field];
  if (list === undefined) return null;
  if (!/^\d+$/.test(position)) return null;
  return issue.type === undefined
    ? { list, index: Number(position), message: issue.message }
    : { list, index: Number(position), message: issue.message, type: issue.type };
}

/** Split a 422's fields into the ones that land on a row and the rest. */
export function mapFieldIssues(issues: readonly FieldIssue[]): {
  rows: MappedFieldIssue[];
  unmapped: FieldIssue[];
} {
  const rows: MappedFieldIssue[] = [];
  const unmapped: FieldIssue[] = [];
  for (const issue of issues) {
    const mapped = mapFieldIssue(issue);
    if (mapped === null) unmapped.push(issue);
    else rows.push(mapped);
  }
  return { rows, unmapped };
}

// ---------------------------------------------------------------------------
// The Zod schema, built from an INJECTED namespace.
// ---------------------------------------------------------------------------

/** The form's value shape. React Hook Form's field arrays need objects. */
export interface PlanFormValues {
  subQuestions: { value: string }[];
  searchQueries: { value: string }[];
}

/**
 * What `useWatch` hands back: every level optional.
 *
 * React Hook Form types a subscription's value as a deep partial, because a
 * field array can be observed before it has populated. Accepting that shape
 * here rather than casting at the call site is what keeps the component free
 * of `as` — and a missing row reads as an empty string, which is exactly
 * what an empty row is.
 */
export interface PartialPlanFormValues {
  subQuestions?: ({ value?: string } | undefined)[];
  searchQueries?: ({ value?: string } | undefined)[];
}

/** `{ value }` rows → the plain draft the pure rules above operate on. */
export function valuesToDraft(values: PartialPlanFormValues): PlanDraft {
  return {
    subQuestions: (values.subQuestions ?? []).map((row) => row?.value ?? ""),
    searchQueries: (values.searchQueries ?? []).map((row) => row?.value ?? ""),
  };
}

/** The plain draft → the form's value shape. */
export function draftToValues(draft: PlanDraft): PlanFormValues {
  return {
    subQuestions: draft.subQuestions.map((value) => ({ value })),
    searchQueries: draft.searchQueries.map((value) => ({ value })),
  };
}

/** One list's Zod shape, with the same two messages `planIssues` produces. */
function listSchema(z: Zod) {
  return z
    .array(
      z.object({
        value: z.string().superRefine((entry, ctx) => {
          if (entry.length > MAX_PLAN_ITEM_LEN) {
            ctx.addIssue({
              code: "custom",
              message: overItemLength(entry.length - MAX_PLAN_ITEM_LEN),
            });
          }
        }),
      }),
    )
    .superRefine((rows, ctx) => {
      if (rows.length > MAX_PLAN_ITEMS) {
        ctx.addIssue({
          code: "custom",
          message: atItemLimit(MAX_PLAN_ITEMS),
        });
      }
    });
}

/**
 * The resolver's schema, over the injected Zod namespace.
 *
 * The injection is the dynamic-import boundary made structural: this module
 * never names `zod` in a value position, so no bundler can follow an edge
 * from here to it. `PlanEditorFields` — which is only ever reached through
 * `React.lazy(() => import("./PlanEditorFields"))` — imports Zod for real
 * and hands it in.
 */
export function buildPlanSchema(z: Zod) {
  return z.object({
    subQuestions: listSchema(z),
    searchQueries: listSchema(z),
  });
}
