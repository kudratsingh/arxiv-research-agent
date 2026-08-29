"use client";

/**
 * PlanEditorFields — the half of the plan editor that needs a form library
 * (WO-17 criteria 1, 2, 3, 4, 7, 9, 10).
 *
 * THIS MODULE IS THE DYNAMIC-IMPORT BOUNDARY. It is reached only through
 * `React.lazy(() => import("./PlanEditorFields"))` in `PlanEditor.tsx`, and
 * it is the only module in the product that imports `react-hook-form` or
 * `zod`. 04 §8.1 leaves `/` 10.9 KB of first-load headroom and `/c/[id]`
 * 14.6 KB; the two packages are ~9 KB and ~14 KB gzip, so they do not fit in
 * either and must not try to. `web/tests/plan/bundle.test.ts` walks the
 * static import graph from both route entrypoints and asserts neither
 * package is reachable without crossing an `import()`, and re-checks the
 * same claim against the build manifests when a production build exists.
 *
 * WHY REACT HOOK FORM EARNS ITS PLACE (04 §4.4's table). Two dynamic arrays
 * whose rows carry their own validation state, plus server errors that have
 * to land on individual rows, plus a dirty comparison against the server's
 * plan. `useFieldArray` gives the rows stable keys across insertion and
 * removal — which is what makes the focus rule in 03 §7.2 implementable —
 * and `setError` is how a 422 reaches a row instead of a page-level banner.
 *
 * WHY ZOD (`buildPlanSchema`). The client bounds must be the server's
 * bounds, exactly (`MAX_PLAN_ITEMS`, `MAX_PLAN_ITEM_LEN`,
 * `src/api/schemas.py:26-27`), so over-length input is refused in the form
 * rather than surfaced as a 422. The schema is built from the injected `z`
 * namespace by `lib/plan/schema.ts`, which is how the bounds stay readable
 * from a zod-free module that the eager half can import.
 *
 * CONTROLLED ROWS, NOT `register`. `Textarea` is not a `forwardRef`
 * component, so a `register()` ref cannot reach the element; `Controller`
 * needs no ref. Focus is then moved by element id — the ids are generated
 * here from `useId`, so the lookup reaches nothing this component does not
 * own.
 *
 * NO STRING IS WRITTEN HERE (`copy/no-inline-text`). Every sentence comes
 * from `@/lib/copy/plan`, most of them through `PLAN_LIST_SPECS` so that the
 * two columns differ in a table rather than in a ternary per line.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";

import {
  Controller,
  useFieldArray,
  useForm,
  useWatch,
  type Control,
  type FieldErrors,
  type FieldPath,
  type Resolver,
} from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/primitives/Button";
import { Textarea } from "@/components/primitives/Textarea";
import { PLAN, atItemLimit } from "@/lib/copy/plan";
import {
  MAX_PLAN_ITEMS,
  MAX_PLAN_ITEM_LEN,
  PLAN_LIST_SPECS,
  buildPlanSchema,
  cancelRequest,
  draftToValues,
  isEdited,
  isListFull,
  mapFieldIssues,
  planToDraft,
  reviewRequestFor,
  valuesToDraft,
  type PlanDraft,
  type PlanFormValues,
  type PlanListKey,
  type PlanListSpec,
} from "@/lib/plan/schema";

import type { PlanEditorFieldsProps } from "./PlanEditor";

// ---------------------------------------------------------------------------
// The resolver.
// ---------------------------------------------------------------------------

/**
 * WO-30: turn off Zod's JIT before any schema is built.
 *
 * FOUND BY THE REPORT-ONLY RUN, NOT REASONED ABOUT. `web/e2e/csp.spec.ts`'s
 * first sweep reported exactly one `script-src blocked=eval` violation
 * across the whole §4 matrix, on the `plan-review` state, at
 * `_next/static/chunks/295.*.js`. That is Zod 4's own feature probe:
 *
 *     let jitAvailable = memo(() => {
 *       if (globalConfig.jitless || …) return false;
 *       try { return Function(""), true } catch { return false }
 *     });
 *
 * Zod compiles validators with `new Function` when it can and interprets
 * them when it cannot, and the probe is inside a `try`, so the plan editor
 * WORKS under the enforcing policy either way. What it does not do is stay
 * quiet: the attempt is a genuine CSP violation, reported once per session
 * in every operator's console, and criterion 1 asks for zero.
 *
 * THE ALTERNATIVE WAS `'unsafe-eval'`, AND IT IS NOT A REAL ALTERNATIVE.
 * Adding it to `script-src` would let any injected string become code,
 * which is most of what the policy exists to prevent — trading the whole
 * control for a validator that runs slightly faster on a form with two
 * lists in it. `jitless` is Zod's own documented switch for exactly this
 * environment ("Useful in environments that disallow `eval`"), it changes
 * no validation result, and it is set here rather than anywhere else
 * because this module is the ONLY runtime importer of `zod` in the product
 * — so the call cannot miss a schema, and `lib/plan/schema.ts` stays
 * zod-free the way WO-17's bundle boundary requires.
 */
z.config({ jitless: true });

/** Built once per module load, not per render: the bounds never change. */
const planSchema = buildPlanSchema(z);

/**
 * How this file reads its own error tree.
 *
 * `toFormErrors` builds an array per list and hangs a `root` off it, which
 * is React Hook Form's own slot for an error about the array rather than
 * about one of its rows. The library's public `FieldErrors` type cannot
 * express that union precisely, so the shape is declared once here and cast
 * to at the two places that read it, rather than being `any` at ten.
 */
type RowError = { value?: { message?: string } } | undefined;
type ListErrors = (RowError[] & { root?: { message?: string } }) | undefined;

/**
 * Zod issues → React Hook Form's error tree.
 *
 * A row issue arrives as `["subQuestions", 3, "value"]` and lands on the
 * row. The list-level issue (too many rows) arrives as `["subQuestions"]`
 * and lands on `root`.
 */
function toFormErrors(
  issues: readonly { path: readonly PropertyKey[]; message: string }[],
): FieldErrors<PlanFormValues> {
  const errors: Record<string, unknown> = {};

  for (const issue of issues) {
    const [listKey, index] = issue.path;
    // `String()` rather than a type guard: every path this schema produces
    // starts with a list name, and a guard would be an unreachable branch
    // pretending otherwise.
    const key = String(listKey);
    const rows = (errors[key] ?? (errors[key] = [])) as RowError[] & {
      root?: unknown;
    };
    const entry = { type: "validate", message: issue.message };
    if (typeof index === "number") rows[index] = { value: entry };
    else rows.root = entry;
  }

  return errors as FieldErrors<PlanFormValues>;
}

/**
 * The resolver itself.
 *
 * Returning `values: {}` on failure is React Hook Form's contract for "do
 * not submit": `handleSubmit`'s valid branch never runs, which is the
 * mechanism behind criterion 3 — 501 characters produce no request because
 * there is no code path from here to `onReview`.
 */
const planResolver: Resolver<PlanFormValues> = (values) => {
  const parsed = planSchema.safeParse(values);
  if (parsed.success) return { values, errors: {} };
  return { values: {}, errors: toFormErrors(parsed.error.issues) };
};

/** The RHF path of one row's control. */
function rowPath(list: PlanListKey, index: number): FieldPath<PlanFormValues> {
  return `${list}.${index}.value` as FieldPath<PlanFormValues>;
}

// ---------------------------------------------------------------------------

export default function PlanEditorFields({
  plan,
  status,
  initialDraft,
  issues,
  onReview,
  arxivHintId,
}: PlanEditorFieldsProps) {
  const uid = useId();
  const noteId = `${uid}-note`;
  const cancelHintId = `${uid}-cancel-hint`;

  const defaultValues = useMemo(
    () => draftToValues(initialDraft ?? planToDraft(plan)),
    [initialDraft, plan],
  );

  const { control, formState, getValues, handleSubmit, setError } =
    useForm<PlanFormValues>({
      defaultValues,
      resolver: planResolver,
      // Validate on submit, then keep re-validating as the row is repaired.
      // Validating on the first keystroke would mark a row invalid before
      // anybody had a chance to finish typing in it.
      mode: "onSubmit",
      reValidateMode: "onChange",
    });

  // Two calls rather than a loop: hooks are not callable conditionally, and
  // a `PLAN_LISTS.map` here would be exactly that.
  const subQuestions = useFieldArray({ control, name: "subQuestions" });
  const searchQueries = useFieldArray({ control, name: "searchQueries" });
  const addSubQuestionRef = useRef<HTMLButtonElement | null>(null);
  const addArxivQueryRef = useRef<HTMLButtonElement | null>(null);

  // `useWatch` rather than `watch()`: the React Compiler cannot memoize a
  // component that calls `watch()` (it returns a fresh function), and this
  // repository lints with `--max-warnings 0`. The subscription is the same
  // one; only the shape of the value is deep-partial, which
  // `valuesToDraft` is typed for.
  const draft: PlanDraft = valuesToDraft(useWatch({ control }));
  // Criterion 1's relabel condition, computed from the working copy against
  // the server's plan — never from a "dirty" flag, which would also fire for
  // a blank row nobody typed in.
  const edited = isEdited(plan, draft);

  const interactive = status === "editing";
  const inFlight =
    status === "submitting" || status === "cancelling" || status === "resolving";

  /** A row's control id. Stable, and owned by this component. */
  const rowId = (list: PlanListKey, index: number): string =>
    `${uid}-${list}-${index}`;

  // -------------------------------------------------------------------------
  // Criterion 4 — a 422 that still arrives lands on the offending row.
  // -------------------------------------------------------------------------

  const [serverNote, setServerNote] = useState<string | null>(null);
  const [formNote, setFormNote] = useState<string | null>(null);
  // The applied set, serialized. `issues` is a fresh array on most renders,
  // so the effect compares contents rather than identity; without that it
  // would re-run forever.
  const appliedIssues = useRef<string | null>(null);

  useEffect(() => {
    const key = JSON.stringify(issues);
    if (appliedIssues.current === key) return;
    appliedIssues.current = key;

    const { rows, unmapped } = mapFieldIssues(issues);
    for (const row of rows) {
      setError(rowPath(row.list, row.index), {
        type: "server",
        message: row.message,
      });
    }
    // Nothing is swallowed. A field the editor has no row for — the
    // `revise_requires_plan` 422 (`routes.py:265-269`), or a field some
    // future schema adds — is stated beside the primary action rather than
    // dropped because it failed to match a path.
    setServerNote(
      unmapped.length === 0 ? null : unmapped.map((issue) => issue.message).join(" "),
    );
  }, [issues, setError]);

  // -------------------------------------------------------------------------
  // 03 §7.2 — focus on removal.
  // -------------------------------------------------------------------------

  // A REF, NOT STATE. "Move focus" is not something the UI renders — it is
  // an instruction to the DOM, consumed once — and holding it in state would
  // mean calling `setState` inside the effect that consumes it, which is a
  // cascading render and which this repository's lint rejects outright
  // (`react-hooks/set-state-in-effect`). The effect below runs after every
  // commit, does nothing unless a removal set the ref, and clears it.
  const pendingFocus = useRef<{ list: PlanListKey; index: number } | null>(null);

  useEffect(() => {
    const pending = pendingFocus.current;
    if (pending === null) return;
    pendingFocus.current = null;
    const { list, index } = pending;

    const remaining = getValues(list).length;
    // "the next row, or the add control when the list empties" (03 §7.2).
    // The next row is whichever one took the removed row's index; when the
    // last row was removed there is no next, so the new last row takes it.
    if (remaining === 0) {
      const addRef =
        list === "subQuestions" ? addSubQuestionRef : addArxivQueryRef;
      addRef.current?.focus();
      return;
    }
    document.getElementById(rowId(list, Math.min(index, remaining - 1)))?.focus();
  });

  function removeRow(list: PlanListKey, index: number) {
    (list === "subQuestions" ? subQuestions : searchQueries).remove(index);
    pendingFocus.current = { list, index };
    setFormNote(null);
  }

  function addRow(list: PlanListKey) {
    (list === "subQuestions" ? subQuestions : searchQueries).append({ value: "" });
    setFormNote(null);
  }

  // -------------------------------------------------------------------------
  // Submission.
  // -------------------------------------------------------------------------

  function submit(formValues: PlanFormValues) {
    const submission = reviewRequestFor(plan, valuesToDraft(formValues));
    if (!submission.ok) {
      // Criterion 7: `revise` without a plan is never built, let alone sent.
      //
      // `empty_plan` is the ONLY refusal that can reach here, and there is
      // deliberately no branch pretending otherwise: a `bounds` refusal is
      // caught by the resolver before `handleSubmit` calls this function at
      // all, and `web/tests/plan/schema.test.ts` proves the Zod schema and
      // `planIssues` agree case for case.
      setFormNote(PLAN.emptyPlan);
      return;
    }
    setFormNote(null);
    onReview(submission.request);
  }

  /** Invalid submit: put the caret where the problem is. */
  function focusFirstError(formErrors: FieldErrors<PlanFormValues>) {
    for (const list of ["subQuestions", "searchQueries"] as const) {
      const rows = formErrors[list] as ListErrors;
      if (!Array.isArray(rows)) continue;
      const index = rows.findIndex((row) => row !== undefined && row !== null);
      if (index >= 0) {
        document.getElementById(rowId(list, index))?.focus();
        return;
      }
    }
  }

  const note = formNote ?? serverNote;

  return (
    <form
      noValidate
      onSubmit={handleSubmit(submit, focusFirstError)}
      className="flex flex-col gap-6"
      data-edited={edited ? "true" : "false"}
    >
      <div className="grid gap-6 md:grid-cols-2">
        <PlanColumn
          spec={PLAN_LIST_SPECS.subQuestions}
          control={control}
          fields={subQuestions.fields}
          errors={formState.errors}
          interactive={interactive}
          full={isListFull(draft, "subQuestions")}
          rowId={rowId}
          hintId={`${uid}-sub-questions-hint`}
          addRef={addSubQuestionRef}
          onAdd={addRow}
          onRemove={removeRow}
        />
        <PlanColumn
          spec={PLAN_LIST_SPECS.searchQueries}
          control={control}
          fields={searchQueries.fields}
          errors={formState.errors}
          interactive={interactive}
          full={isListFull(draft, "searchQueries")}
          rowId={rowId}
          hintId={arxivHintId}
          addRef={addArxivQueryRef}
          onAdd={addRow}
          onRemove={removeRow}
        />
      </div>

      {note === null ? null : (
        <p id={noteId} className="text-ui-sm text-critical-text">
          {note}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {/* Criterion 1: ONE primary action. Its label — and the action it
            sends — are derived from the working copy, so there is never a
            second control the user has to choose between. */}
        <Button
          type="submit"
          variant="primary"
          size="md"
          data-primary="true"
          busy={inFlight}
          {...(note === null ? {} : { "aria-describedby": noteId })}
        >
          {edited ? PLAN.revise : PLAN.approve}
        </Button>

        {/* Criterion 2: cancel is at the FAR END, destructive-secondary, and
            its consequence travels with it rather than being left implied. */}
        <span className="flex-1" />
        <span id={cancelHintId} className="text-ui-xs text-ink-muted">
          {PLAN.cancelConsequence}
        </span>
        <Button
          variant="secondary"
          size="md"
          className="border-critical text-critical-text hover:bg-critical-surface"
          aria-describedby={cancelHintId}
          disabled={!interactive}
          onClick={() => onReview(cancelRequest())}
        >
          {PLAN.cancel}
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// One column.
// ---------------------------------------------------------------------------

interface PlanColumnProps {
  spec: PlanListSpec;
  control: Control<PlanFormValues>;
  fields: { id: string }[];
  errors: FieldErrors<PlanFormValues>;
  interactive: boolean;
  full: boolean;
  rowId: (list: PlanListKey, index: number) => string;
  hintId: string;
  addRef: React.RefObject<HTMLButtonElement | null>;
  onAdd: (list: PlanListKey) => void;
  onRemove: (list: PlanListKey, index: number) => void;
}

function PlanColumn({
  spec,
  control,
  fields,
  errors,
  interactive,
  full,
  rowId,
  hintId,
  addRef,
  onAdd,
  onRemove,
}: PlanColumnProps) {
  const rows = errors[spec.key] as ListErrors;
  const rootMessage = rows?.root?.message;

  return (
    <fieldset
      className="flex min-w-0 flex-col gap-3"
      data-list={spec.key}
      data-family={spec.family}
    >
      <legend className="text-ui-sm font-semibold text-ink">
        {spec.columnLabel}
      </legend>

      {/* One hint element per column, read once per field rather than
          repeated under every row. On the arXiv column this is the element
          every row's `aria-describedby` points at (D-010 ruling 8). */}
      <p id={hintId} className="text-ui-xs text-ink-muted">
        {spec.columnHint}
      </p>

      {fields.length === 0 ? (
        <p className="text-ui-sm text-ink-muted">{spec.emptyNote}</p>
      ) : (
        // A real list of real list items. The baseline's `listitem`
        // violation comes from a `role="log"` sitting over rows that are
        // semantically list items; there is no role override anywhere here.
        <ul className="flex flex-col gap-3">
          {fields.map((field, index) => {
            const message = rows?.[index]?.value?.message;

            return (
              <li key={field.id} className="flex items-end gap-2">
                <Controller
                  control={control}
                  name={rowPath(spec.key, index)}
                  render={({ field: controlled }) => (
                    <Textarea
                      id={rowId(spec.key, index)}
                      // 03 §3.5's two families. The typeface is the visual
                      // carrier of prose-versus-literal; the column hint is
                      // the carrier for everyone it cannot reach. Size stays
                      // `ui-base` (16px) in both columns, because 03 §7.5
                      // makes that a viewport rule rather than a type-scale
                      // preference.
                      className={
                        spec.family === "mono"
                          ? "min-w-0 flex-1 [&_textarea]:font-mono"
                          : "min-w-0 flex-1"
                      }
                      label={spec.rowLabel(index + 1)}
                      rows={2}
                      limit={MAX_PLAN_ITEM_LEN}
                      value={String(controlled.value ?? "")}
                      onChange={controlled.onChange}
                      onBlur={controlled.onBlur}
                      name={controlled.name}
                      readOnly={!interactive}
                      {...(spec.describesRows
                        ? { "aria-describedby": hintId }
                        : {})}
                      {...(message === undefined ? {} : { error: message })}
                    />
                  )}
                />
                <Button
                  iconOnly
                  size="md"
                  variant="ghost"
                  className="mb-6 shrink-0"
                  aria-label={spec.removeLabel(index + 1)}
                  disabled={!interactive}
                  onClick={() => onRemove(spec.key, index)}
                >
                  <RemoveGlyph />
                </Button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-col gap-1">
        <Button
          ref={addRef}
          size="md"
          variant="secondary"
          className="self-start"
          disabled={!interactive || full}
          onClick={() => onAdd(spec.key)}
        >
          {spec.addLabel}
        </Button>
        {full ? (
          <p className="text-ui-xs text-ink-muted">{atItemLimit(MAX_PLAN_ITEMS)}</p>
        ) : null}
        {rootMessage === undefined ? null : (
          <p className="text-ui-xs text-critical-text">{rootMessage}</p>
        )}
      </div>
    </fieldset>
  );
}

/** The remove mark. `aria-hidden`: the Button's `aria-label` is the name. */
function RemoveGlyph() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <path
        d="M4 4l8 8M12 4l-8 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}
