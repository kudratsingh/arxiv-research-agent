/**
 * WO-S2b — the plan editor's Suspense fallback is SIZED FROM THE PLAN.
 *
 * WHAT THIS FILE CAN PROVE AND WHAT IT CANNOT. The claim S2b is actually
 * making is about pixels: the box that holds the place of `PlanEditorFields`
 * is the height that component is about to take, so the 161px of reading
 * column still visible below it does not get pushed off screen when the lazy
 * chunk resolves. Pixels need a layout engine, and jsdom has none —
 * `getBoundingClientRect` returns zeroes there — so the pixel claim is
 * `web/e2e/plan-fallback.spec.ts`, which measures the two boxes in Chromium
 * and asserts they are equal to the pixel.
 *
 * What is provable HERE is everything that decides those pixels, and it is
 * the half that will actually rot:
 *
 *   1. THE ROW COUNT COMES FROM THE PLAN, and from `initialDraft` when there
 *      is one — because that is what `PlanEditorFields` opens with. A
 *      fallback that reserved a fixed number of rows would be right for the
 *      three-item fixture and wrong for every other plan.
 *   2. THE COLUMN CHROME IS THE FORM'S OWN COPY. `PlanEditor` cannot import
 *      `PLAN_LIST_SPECS` — that module is a value import away from the lazy
 *      chunk's whole dependency (see `FALLBACK_COLUMNS`' comment) — so the
 *      pairing of sentence to column is stated twice. This file is what
 *      stops the two statements drifting: it compares them field by field.
 *   3. THE FIELD BOX IS A TOKEN EXPRESSION, not a measured pixel constant.
 *   4. THE MIRROR IS HIDDEN FROM THE ACCESSIBILITY TREE, so that for the
 *      ~30ms the chunk is in flight there are not two `Approve plan` buttons
 *      for a role query — or for a screen reader — to choose between.
 */

import { describe, expect, it } from "vitest";

import { PlanEditor } from "@/components/patterns/PlanEditor";
import type { Plan } from "@/lib/api";
import { ADD_ARXIV_QUERY, ADD_SUB_QUESTION, PLAN } from "@/lib/copy/plan";
import { PLAN_LIST_SPECS } from "@/lib/plan/schema";

import { render, screen } from "../support/render";

const PLAN_FIXTURE: Plan = {
  sub_questions: [
    "Which verification architectures are currently used?",
    "How is evidence provenance preserved?",
    "What does the failure surface look like?",
  ],
  search_queries: ["retrieval augmented claim verification", "evidence provenance"],
};

/**
 * Render and read the fallback, WITHOUT awaiting the lazy chunk.
 *
 * Every other test in this directory starts by awaiting a row label, which is
 * the dynamic-import boundary being crossed. This one deliberately does not:
 * the frame before that boundary is the whole subject.
 */
function mountFallback(
  options: { plan?: Plan; initialDraft?: { subQuestions: string[]; searchQueries: string[] } } = {},
) {
  render(
    <main>
      <PlanEditor
        plan={options.plan ?? PLAN_FIXTURE}
        {...(options.initialDraft === undefined
          ? {}
          : { initialDraft: options.initialDraft })}
        onReview={() => {}}
      />
    </main>,
  );
  const fallback = document.querySelector('[data-testid="plan-editor-loading"]');
  expect(fallback, "the Suspense fallback is not on screen").not.toBeNull();
  return fallback as HTMLElement;
}

const columnOf = (fallback: HTMLElement, key: string): HTMLElement => {
  const column = fallback.querySelector(`[data-fallback-list="${key}"]`);
  expect(column, `the fallback has no ${key} column`).not.toBeNull();
  return column as HTMLElement;
};

describe("WO-S2b — the fallback reserves one row per row the form will render", () => {
  it("takes the row counts from the plan", () => {
    const fallback = mountFallback();

    expect(columnOf(fallback, "subQuestions").querySelectorAll("li")).toHaveLength(3);
    expect(columnOf(fallback, "searchQueries").querySelectorAll("li")).toHaveLength(2);
  });

  it("takes them from `initialDraft` when there is one, because the form does", () => {
    // The restored-draft case. `PlanEditorFields` opens with
    // `draftToValues(initialDraft ?? planToDraft(plan))`, so a fallback that
    // read the plan here would reserve three rows for a five-row form.
    const fallback = mountFallback({
      initialDraft: {
        subQuestions: ["a", "b", "c", "d", "e"],
        searchQueries: ["q"],
      },
    });

    expect(columnOf(fallback, "subQuestions").querySelectorAll("li")).toHaveLength(5);
    expect(columnOf(fallback, "searchQueries").querySelectorAll("li")).toHaveLength(1);
  });

  it("reserves the empty note, not a row, for a column with nothing in it", () => {
    // `PlanColumn` renders `spec.emptyNote` instead of the `ul` when a list
    // is empty, and that note is a different height from a row.
    const fallback = mountFallback({
      plan: { sub_questions: [], search_queries: ["one"] },
    });

    const empty = columnOf(fallback, "subQuestions");
    expect(empty.querySelectorAll("li")).toHaveLength(0);
    expect(empty.textContent).toContain(PLAN.noSubQuestions);
    expect(columnOf(fallback, "searchQueries").querySelectorAll("li")).toHaveLength(1);
  });

  it("survives a plan whose lists are absent rather than empty", () => {
    // BOTH FIELDS ARE OPTIONAL ON THE WIRE and required in the type, which is
    // exactly why this case needs a cast to be written at all: `schema.d.ts`
    // generates `sub_questions?: string[]`, and `Serialized` in
    // `lib/api/models.ts` strips the `?` "to guard keys the API always
    // sends". A server that omits them is therefore representable in JSON and
    // not in TypeScript — and `planToDraft` spreads `?? []` for precisely
    // that reason, so the fallback does too. Reading `.length` off
    // `undefined` here would throw INSIDE a Suspense boundary, which paints
    // as a blank surface rather than as an error anyone can read.
    const fallback = mountFallback({
      plan: {} as unknown as Plan,
    });

    expect(fallback.querySelectorAll("li")).toHaveLength(0);
    expect(fallback.textContent).toContain(PLAN.noSubQuestions);
    expect(fallback.textContent).toContain(PLAN.noArxivQueries);
  });
});

describe("WO-S2b — the fallback's chrome is the form's own", () => {
  it.each([
    ["subQuestions", ADD_SUB_QUESTION] as const,
    ["searchQueries", ADD_ARXIV_QUERY] as const,
  ])(
    "renders %s with exactly the strings `PLAN_LIST_SPECS` gives the real column",
    (key, addLabel) => {
      // THE DRIFT GUARD. `PlanEditor` states the pairing a second time
      // because it cannot afford the module `PLAN_LIST_SPECS` lives in; this
      // is the assertion that makes the second statement equal to the first.
      const spec = PLAN_LIST_SPECS[key];
      const column = columnOf(mountFallback(), key);

      expect(column.querySelector("legend")?.textContent).toBe(spec.columnLabel);
      expect(column.textContent).toContain(spec.columnHint);
      expect(column.textContent).toContain(spec.addLabel);
      expect(spec.addLabel).toBe(addLabel);
    },
  );

  it("renders the empty note each column would show, in the right column", () => {
    const fallback = mountFallback({ plan: { sub_questions: [], search_queries: [] } });

    expect(columnOf(fallback, "subQuestions").textContent).toContain(
      PLAN_LIST_SPECS.subQuestions.emptyNote,
    );
    expect(columnOf(fallback, "searchQueries").textContent).toContain(
      PLAN_LIST_SPECS.searchQueries.emptyNote,
    );
  });

  it("reserves the actions row with the words that decide where it wraps", () => {
    // Below `md` this row wraps onto a second line, and where it wraps is
    // decided by the two button labels' widths. `PLAN.approve` and not
    // `PLAN.revise`: the form opens un-edited, so `PLAN.approve` is the label
    // that is on screen the frame the chunk lands.
    const fallback = mountFallback();

    expect(fallback.textContent).toContain(PLAN.cancelHint);
    expect(fallback.textContent).toContain(PLAN.approve);
    expect(fallback.textContent).toContain(PLAN.cancelConsequence);
    expect(fallback.textContent).toContain(PLAN.cancel);
    expect(fallback.textContent).not.toContain(PLAN.revise);
  });

  it("sizes the field box from tokens rather than from a measured constant", () => {
    // `Textarea` is `rows={2}` of `text-ui-base` inside `p-3` with a 1px
    // border on each edge. Written as an expression over the same three
    // tokens, the reservation follows the type scale; written as `74px` it
    // would silently stop matching the first time one of them moved.
    const fallback = mountFallback();
    const heights = Array.from(fallback.querySelectorAll("li .ew-skeleton")).map(
      (bar) => (bar as HTMLElement).style.height,
    );

    expect(heights).toContain(
      "calc(2 * var(--text-ui-base-line) + 2 * var(--space-3) + 2px)",
    );
    expect(heights).toContain("var(--text-ui-sm-line)");
    expect(heights).toContain("var(--text-ui-xs-line)");
    // No bare pixel anywhere in the reservation.
    for (const height of heights) {
      expect(height, `${height} is a pixel guess, not a token`).not.toMatch(/^\d+px$/);
    }
  });
});

describe("WO-S2b — the mirror is not a second copy of the controls", () => {
  it("hides the whole mirror from the accessibility tree", () => {
    const fallback = mountFallback();
    const mirror = fallback.querySelector('[aria-hidden="true"]');

    expect(mirror, "the fallback's visual mirror is not aria-hidden").not.toBeNull();
    expect(mirror?.contains(fallback.querySelector("fieldset"))).toBe(true);
  });

  it("exposes no button by role while the chunk is in flight", () => {
    // The reason this matters is not tidiness. `web/e2e/reach.spec.ts` asks
    // for `Approve plan` by role the instant the page has loaded; a fallback
    // that offered a second one would make that a strict-mode violation
    // rather than an assertion.
    mountFallback();

    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("leaves nothing inside the hidden subtree focusable", () => {
    // `aria-hidden` over a focusable element is an axe violation
    // (`aria-hidden-focus`), which is why every control in the mirror carries
    // `disabled` rather than `aria-disabled`.
    const fallback = mountFallback();

    for (const control of Array.from(fallback.querySelectorAll("button"))) {
      expect(control, `${control.textContent} is focusable inside aria-hidden`).toBeDisabled();
    }
  });

  it("still names the region for a screen reader", () => {
    // The clipped word the old fallback carried through `Skeleton`'s `label`.
    const fallback = mountFallback();

    expect(fallback.getAttribute("aria-busy")).toBe("true");
    expect(fallback.querySelector(".ew-visually-hidden")?.textContent).toBe(PLAN.heading);
  });
});
