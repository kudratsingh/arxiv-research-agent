"use client";

import { useEffect, useState } from "react";
import type { Plan, ReviewAction } from "@/lib/types";

interface PlanReviewProps {
  plan: Plan;
  onReview: (action: ReviewAction, plan?: Plan) => void | Promise<void>;
}

/**
 * The HITL breakpoint UI (ADR 0030). Shows the planner's output
 * (sub_questions + search_queries) as editable lists. The user
 * either approves as-is, saves edits and approves, or cancels the
 * run.
 *
 * Local state carries the working copy; only committed on submit.
 * `Reset` restores the original planner output.
 */
export default function PlanReview({ plan, onReview }: PlanReviewProps) {
  const [subs, setSubs] = useState<string[]>(plan.sub_questions);
  const [queries, setQueries] = useState<string[]>(plan.search_queries);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Refresh the working copy if the plan prop changes (e.g. a new
    // job with a new plan).
    setSubs(plan.sub_questions);
    setQueries(plan.search_queries);
  }, [plan]);

  const edited =
    !arraysEqual(subs, plan.sub_questions) ||
    !arraysEqual(queries, plan.search_queries);

  const call = async (action: ReviewAction, editedPlan?: Plan) => {
    setBusy(true);
    try {
      await onReview(action, editedPlan);
    } finally {
      setBusy(false);
    }
  };

  const approve = () => call("approve");
  const revise = () =>
    call("revise", {
      sub_questions: subs.filter((s) => s.trim() !== ""),
      search_queries: queries.filter((s) => s.trim() !== ""),
    });
  const cancel = () => call("cancel");
  const reset = () => {
    setSubs(plan.sub_questions);
    setQueries(plan.search_queries);
  };

  return (
    <section
      aria-labelledby="plan-review-heading"
      className="rounded-lg border border-amber-300 bg-amber-50 p-5 dark:border-amber-800 dark:bg-amber-950/40"
    >
      <div className="flex items-baseline justify-between">
        <h2
          id="plan-review-heading"
          className="text-xs font-semibold uppercase tracking-wider text-amber-800 dark:text-amber-200"
        >
          Plan review
        </h2>
        <span className="text-xs text-amber-700 dark:text-amber-300">
          Workflow paused after the planner. Approve, edit, or cancel.
        </span>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <EditableList
          label="Sub-questions"
          items={subs}
          onChange={setSubs}
          placeholder="Add a sub-question…"
        />
        <EditableList
          label="Search queries"
          items={queries}
          onChange={setQueries}
          placeholder="Add a search query…"
        />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={approve}
          disabled={busy || edited}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 disabled:cursor-not-allowed disabled:opacity-60"
          title={edited ? "Save edits with the button to the right" : "Approve as-is"}
        >
          Approve as-is
        </button>
        <button
          type="button"
          onClick={revise}
          disabled={busy || !edited}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Save edits &amp; approve
        </button>
        <button
          type="button"
          onClick={reset}
          disabled={busy || !edited}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-500/40 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Reset
        </button>
        <span className="flex-1" />
        <button
          type="button"
          onClick={cancel}
          disabled={busy}
          className="rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 shadow-sm hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500/40 disabled:cursor-not-allowed disabled:opacity-60 dark:border-red-800 dark:bg-slate-900 dark:text-red-200 dark:hover:bg-red-950/40"
        >
          Cancel job
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sub-components + helpers
// ---------------------------------------------------------------------------

interface EditableListProps {
  label: string;
  items: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
}

function EditableList({
  label,
  items,
  onChange,
  placeholder,
}: EditableListProps) {
  const update = (idx: number, value: string) => {
    const next = items.slice();
    next[idx] = value;
    onChange(next);
  };
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx));
  const add = () => onChange([...items, ""]);

  return (
    <div>
      <label className="mb-1 block text-sm font-semibold text-amber-900 dark:text-amber-100">
        {label}
      </label>
      <ul className="space-y-1">
        {items.map((item, idx) => (
          <li key={idx} className="flex items-center gap-2">
            <input
              type="text"
              value={item}
              onChange={(e) => update(idx, e.target.value)}
              placeholder={placeholder}
              aria-label={`${label} #${idx + 1}`}
              className="block w-full rounded-md border border-amber-300 bg-white px-2 py-1 text-sm shadow-sm focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500 dark:border-amber-800 dark:bg-slate-950"
            />
            <button
              type="button"
              onClick={() => remove(idx)}
              aria-label={`Remove ${label} #${idx + 1}`}
              className="rounded p-1 text-amber-700 hover:bg-amber-100 dark:text-amber-300 dark:hover:bg-amber-900/50"
            >
              &times;
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={add}
        className="mt-2 text-xs font-semibold text-amber-800 hover:underline dark:text-amber-200"
      >
        + Add {label.toLowerCase().slice(0, -1)}
      </button>
    </div>
  );
}

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}
