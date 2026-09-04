"use client";

/**
 * PlanEditorFields — the half of the plan editor that needs a form library
 * (WO-17 criteria 1, 2, 3, 4, 7, 9, 10).
 *
 * THIS MODULE IS THE DYNAMIC-IMPORT BOUNDARY. It is reached only through
 * `React.lazy(() => import("./PlanEditorFields"))` in `PlanEditor.tsx`, and
 * it is the only module in the product that imports `react-hook-form`.
 * 04 §8.1 leaves `/` 10.9 KB of first-load headroom and `/c/[id]` 14.6 KB;
 * the package is ~9 KB gzip, so it fits in neither and must not try to.
 * `web/tests/plan/bundle.test.ts` walks the static import graph from both
 * route entrypoints and asserts it is not reachable without crossing an
 * `import()`, and re-checks the same claim against the build manifests when
 * a production build exists.
 *
 * WHY REACT HOOK FORM EARNS ITS PLACE (04 §4.4's table). Two dynamic arrays
 * whose rows carry their own validation state, plus server errors that have
 * to land on individual rows, plus a dirty comparison against the server's
 * plan. `useFieldArray` gives the rows stable keys across insertion and
 * removal — which is what makes the focus rule in 03 §7.2 implementable —
 * and `setError` is how a 422 reaches a row instead of a page-level banner.
 *
 * ZOD DOES NOT (`known-gaps.md` §19). It used to: `buildPlanSchema` was this
 * module's resolver, and it made the chunk `React.lazy` fetches at
 * plan-review 296 KB raw / 73.6 KB gzip and a ~250 ms long task on the
 * 2-vCPU runner's regime — for two bounds. Both are `planIssues` in
 * `lib/plan/schema.ts`, which `reviewRequestFor` has always used and which
 * has always been the thing that decides whether a request is built at all;
 * `planResolver` there is now the eleven lines that put those issues on
 * React Hook Form's rows. The Zod statement of the same rules is retained in
 * `web/tests/plan/schema.test.ts` as the oracle that file compares the
 * resolver against, so the bounds are still checked against a library on
 * every run — they are just not shipped to a browser to do it.
 *
 * AND WO-30'S `z.config({ jitless: true })` GOES WITH IT. That call was here
 * because Zod 4 probes for `new Function` at module evaluation, which the
 * enforcing policy reports as a `script-src blocked=eval` violation once per
 * session — the single violation `web/e2e/csp.spec.ts`'s report-only sweep
 * found across the whole §4 matrix, and it was on this state. With the
 * package gone there is no probe left to silence, and `csp.spec.ts` still
 * gates the count at zero.
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
} from "react-hook-form";

import { Button } from "@/components/primitives/Button";
import { Textarea } from "@/components/primitives/Textarea";
import { PLAN, atItemLimit } from "@/lib/copy/plan";
import {
  MAX_PLAN_ITEMS,
  MAX_PLAN_ITEM_LEN,
  PLAN_LIST_SPECS,
  cancelRequest,
  draftToValues,
  isEdited,
  isListFull,
  mapFieldIssues,
  planResolver,
  planToDraft,
  reviewRequestFor,
  valuesToDraft,
  type PlanDraft,
  type PlanFormValues,
  type PlanListErrors,
  type PlanListKey,
  type PlanListSpec,
} from "@/lib/plan/schema";

import type { PlanEditorFieldsProps } from "./PlanEditor";

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
      // all, and the resolver and `reviewRequestFor` now call the SAME
      // `planIssues` — which is the strongest form that claim has taken.
      // `web/tests/plan/schema.test.ts` still checks that function against a
      // Zod schema of the same bounds, case for case.
      setFormNote(PLAN.emptyPlan);
      return;
    }
    setFormNote(null);
    onReview(submission.request);
  }

  /** Invalid submit: put the caret where the problem is. */
  function focusFirstError(formErrors: FieldErrors<PlanFormValues>) {
    for (const list of ["subQuestions", "searchQueries"] as const) {
      const rows = formErrors[list] as PlanListErrors;
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
  const rows = errors[spec.key] as PlanListErrors;
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
