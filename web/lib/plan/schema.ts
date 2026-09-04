// The plan editor's bounds, its working copy, and the rules that decide
// what — if anything — gets sent (04 §4.5, WO-17 criteria 3, 4, 7).
//
// THIS MODULE IS ON `/c/[id]`'s FIRST-LOAD PATH, SO ITS IMPORTS ARE A BUDGET
// DECISION. `PlanEditor` — the eager half — imports it for `isEdited`, the
// bounds and the 422 mapping, so every value import here lands in the route's
// chunk union (04 §8.1, R-11). React Hook Form is named here only as a TYPE,
// which the compiler erases; the package itself is reached exclusively
// through `React.lazy(() => import("./PlanEditorFields"))`.
//
// ZOD IS NOT IMPORTED AT ALL ANY MORE (`known-gaps.md` §19). `planResolver`
// below is what the form validates with, and it is a pure function over
// `planIssues` — the same function `reviewRequestFor` has always used. The
// Zod schema that used to be the resolver now lives in
// `web/tests/plan/schema.test.ts` as the DIFFERENTIAL ORACLE that file checks
// this one against, case for case, on every run. `web/tests/plan/bundle.test.ts`
// holds both facts: React Hook Form stays behind the `import()` boundary, and
// Zod is in no shipped module and no emitted chunk.
//
// THE BOUNDS ARE THE SERVER'S, NOT A CLIENT PREFERENCE.
// `web/tests/plan/schema.test.ts` re-derives both numbers from
// `src/api/schemas.py` on every run, the way WO-12's error_type drift test
// re-derives its vocabulary from Python, so "mirror the server exactly"
// stays a fact rather than a comment.
//
// EVERY DECISION IN THIS FILE IS A PURE FUNCTION. The component decides
// nothing about validity on its own: it renders what `planIssues`,
// `planResolver` and `reviewRequestFor` return. That is what makes WO-17
// criterion 3's claim — 501 characters produce no request — provable
// without a DOM.

import type { FieldErrors, Resolver } from "react-hook-form";

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
 * THIS IS NOW THE ONLY RULE SET THAT SHIPS. `planResolver` below is a thin
 * translation of what this returns into React Hook Form's error tree, so the
 * form and `reviewRequestFor` cannot disagree about what is valid — they run
 * the same function. The second statement of these rules lives in
 * `web/tests/plan/schema.test.ts`, in Zod, and that file asserts the two
 * agree case for case; that copy is the oracle, not the implementation.
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
// The form's shapes.
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

// ---------------------------------------------------------------------------
// The resolver. Pure, Zod-free, and the thing that actually ships.
// ---------------------------------------------------------------------------

/**
 * How this module and its readers see one row's error slot.
 *
 * `planFormErrors` builds an array per list and hangs a `root` off it, which
 * is React Hook Form's own slot for an error about the array rather than
 * about one of its rows. The library's public `FieldErrors` type cannot
 * express that union precisely, so the shape is declared once here — where it
 * is written — and cast to where `PlanEditorFields` reads it, rather than
 * being `any` at ten call sites.
 */
export type PlanRowError = { value?: { message?: string } } | undefined;

export type PlanListErrors =
  | (PlanRowError[] & { root?: { message?: string } })
  | undefined;

/**
 * `planIssues` → React Hook Form's error tree.
 *
 * A row issue (`index` is a number) lands on the row. The list-level issue —
 * too many rows — lands on `root`, which is the slot React Hook Form reserves
 * for a complaint about the array itself.
 */
export function planFormErrors(
  issues: readonly PlanIssue[],
): FieldErrors<PlanFormValues> {
  const errors: Record<string, unknown> = {};

  for (const issue of issues) {
    const rows = (errors[issue.list] ?? (errors[issue.list] = [])) as PlanRowError[] & {
      root?: unknown;
    };
    const entry = { type: "validate", message: issue.message };
    if (issue.index === null) rows.root = entry;
    else rows[issue.index] = { value: entry };
  }

  return errors as FieldErrors<PlanFormValues>;
}

/**
 * The form's resolver.
 *
 * WHY THIS IS NOT A ZOD SCHEMA ANY MORE (`known-gaps.md` §19). Zod 4.4.3 is
 * 296 KB raw / 73.6 KB gzip and evaluating it was a single ~250 ms long task
 * on the 2-vCPU runner's regime, inside the chunk `React.lazy` fetches the
 * moment the plan-review state renders — for a form whose entire rule set is
 * "an entry is at most `MAX_PLAN_ITEM_LEN` characters" and "a list holds at
 * most `MAX_PLAN_ITEMS` of them". Those two rules already existed here as
 * `planIssues`, because `reviewRequestFor` — the function that decides
 * whether a request is built at all — has always been Zod-free and is the
 * real gate. So the schema was never the safety property; it was a second
 * statement of it that cost 73.6 KB to ship. It is retained in
 * `web/tests/plan/schema.test.ts` as the oracle that file compares this
 * against, case for case, and is no longer shipped.
 *
 * Returning `values: {}` on failure is React Hook Form's contract for "do
 * not submit": `handleSubmit`'s valid branch never runs, which is the
 * mechanism behind criterion 3 — 501 characters produce no request because
 * there is no code path from here to `onReview`.
 */
export const planResolver: Resolver<PlanFormValues> = (values) => {
  const issues = planIssues(valuesToDraft(values));
  if (issues.length === 0) return { values, errors: {} };
  return { values: {}, errors: planFormErrors(issues) };
};
