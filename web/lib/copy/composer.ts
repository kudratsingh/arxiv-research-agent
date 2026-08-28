// The composer's half of the copy dictionary (WO-13).
//
// WHY A FOURTH FILE RATHER THAN A FEW MORE KEYS IN `run.ts`. WO-12's
// barrel states the layout rule outright: "One file per surface behind
// this barrel (06-WORK-ORDERS.md §5.6's file-ownership table), so WO-13 …
// WO-19 add their own file rather than queueing on a shared one." This is
// that file. It is deliberately NOT re-exported from `lib/copy/index.ts`:
// every string here is route JavaScript on `/`, whose first-load budget
// (04 §8.1) has the least headroom of any row, and a barrel import would
// pull `errors.ts`, `run.ts` and `threads.ts` into a route that needed
// one of them. `components/features/QueryComposer.tsx` imports
// `@/lib/copy/composer` directly, exactly as the barrel's own header
// recommends.
//
// WHAT MOVED HERE FROM `run.ts`, AND WHY. 03 §1.4's landing surface —
// `LANDING`, `MAX_QUERY_LEN`, `queryCounter()`, `queryOverLimit()` — was
// defined in `lib/copy/run.ts` by WO-12, which had no composer file to put
// it in. It is the composer's surface, so it lives here now and `run.ts`
// RE-EXPORTS all four, unchanged: `@/lib/copy`, `@/lib/copy/run` and
// `web/tests/copy/forbidden.test.ts`'s walk of the run namespace all keep
// seeing them exactly where they saw them before, and §1.4 still has one
// edit site.
//
// The reason it had to move rather than be imported is measurable.
// `run.ts` is also the trace spine's and the metrics strip's dictionary.
// `vitest.config.mts` records the hazard: a module loaded by BOTH Vitest
// projects has its function lists concatenated, so a story that renders
// the composer would put all eleven of `run.ts`'s functions into the
// Storybook project while exercising three — measured at eight lost
// function-coverage points. The composer's stories now load this file,
// which has exactly the three functions they exercise.
//
// WHAT IS **NOT** HERE, ON PURPOSE. Every failure sentence. A submission
// failure is an `ApiFailure`, and `describeFailure()` in
// `lib/copy/errors.ts` is the one accessor for those (04 §3.4, RC-16). The
// composer maps nothing itself.
//
// `web/tests/copy/composer-copy.test.ts` is this file's gate. It walks
// every export with WO-12's own `collectCopyStrings()`, drives every
// exported function, and applies the same `DENY_LIST`, `LEXICON_PHRASES`
// and ownership rules that `web/tests/copy/forbidden.test.ts` applies to
// the other three modules, so a fourth copy file is held to one standard
// rather than to a new one.

// ---------------------------------------------------------------------------
// Landing (03 §1.4, verbatim). Moved from `run.ts` by WO-13; see above.
// ---------------------------------------------------------------------------

/** `MAX_QUERY_LEN` on `ResearchRequest` (`src/api/schemas.py:36-40`). */
export const MAX_QUERY_LEN = 8000;

/**
 * The landing surface, string for string as 03 §1.4 prints it.
 *
 * `disclosure` is persistent body copy directly above the button — "not a
 * tooltip, not a footnote, not revealed on hover". It says *billable*
 * because generating a plan is the moment money starts being spent, and
 * `button` says "Generate plan" rather than "Run research" because a
 * planner run that pauses is the action's true immediate effect.
 *
 * `process` is a legend for the trace spine the user is about to meet.
 * Four things that genuinely exist, in the lexicon's words (RC-12).
 *
 * WO-13 criterion 1 asserts every one of these against the brief's own
 * fenced block, parsed out of `docs/revamp/03-DESIGN-BRIEF.md` at test
 * time, so "verbatim" is checked against the source rather than against a
 * second copy of it.
 */
export const LANDING = {
  eyebrow: "Evidence Workbench",
  heading: "What should the literature settle?",
  questionLabel: "Research question",
  questionPlaceholder:
    "e.g. How do current systems evaluate faithfulness in retrieval-augmented generation?",
  disclosure:
    "Generating a plan starts a billable run. You review and edit the plan before any arXiv search or paper reading happens.",
  submit: "Generate plan",
  submitPending: "Generating plan…",
  process: ["Question", "Plan you approve", "arXiv run", "Briefing"],
} as const;

/** Group thousands without `toLocaleString`, whose output is host-dependent. */
function groupDigits(value: number): string {
  return String(Math.trunc(Math.abs(value))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * The character counter, visible from zero characters (03 §1.4).
 *
 * A counter, not a percentage: 03 §5.5 forbids any `%`, and a fraction of
 * a character limit is the one place a `%` would look harmless.
 */
export function queryCounter(length: number): string {
  return `${groupDigits(length)} / ${groupDigits(MAX_QUERY_LEN)}`;
}

/** Over the bound, client-side, before a request is ever made. */
export function queryOverLimit(length: number): string {
  const over = Math.max(0, Math.trunc(length) - MAX_QUERY_LEN);
  return `${groupDigits(over)} character${over === 1 ? "" : "s"} over the limit. Shorten the question to send it.`;
}

// ---------------------------------------------------------------------------
// The composer (03 §4.3, §2.2 rows 1, 4, 17; 04 §9.1 H6 and H7).
// ---------------------------------------------------------------------------

/**
 * Everything the composer says that 03 §1.4 does not already say.
 *
 * READ `retained` AND `noAutoRetry` TOGETHER. They are H6 written as a
 * sentence the user can check against what they see: `POST /research` has
 * no idempotency key (`routes.py:179-197`), so a retry is a second paid
 * run and can only ever be a deliberate act. The composer therefore
 * promises two things after a failure — the question is still in the box,
 * and nothing went out again by itself — and then leaves the same single
 * submit control it always had. There is no second "Retry" affordance,
 * because a control labelled *retry* invites a reflex where the honest
 * action is a decision.
 *
 * `orphanSentence` and `orphanAction` are H7. `web/app/page.tsx:33-36`
 * creates the thread BEFORE it submits, and both writes spend rate-limit
 * budget (`routes.py:157`, `:545`), so a submission that failed at the
 * second write has already left a real, empty thread in the rail. Saying
 * so and linking to it is the difference between an honest surface and
 * one that quietly litters.
 */
export const COMPOSER = {
  /**
   * The follow-up variant's field (03 §4.3). The landing variant uses
   * `LANDING.questionLabel` and `LANDING.questionPlaceholder` instead,
   * which are §1.4's own strings.
   */
  followUpLabel: "Follow-up question",
  followUpPlaceholder:
    "e.g. Which of those findings are contested, and what is the strongest case against them?",

  /**
   * The two refusals the composer makes on its own, before a request
   * exists. Both are attached to the submit control through
   * `aria-describedby` rather than being left as a greyed-out button with
   * no stated reason (03 §2.2 row 4's rule, applied to every reason).
   */
  emptyQuestion: "Type a question first. Nothing is sent until you do.",

  /**
   * Screen-reader label for the character counter, which is otherwise two
   * numbers and a slash. The counter itself is `queryCounter()` in
   * `lib/copy/run.ts`, printed verbatim as §1.4 prints it.
   */
  counterLabel: "Question length:",

  /** H6, after a failed submission. */
  retained: "The question is still in the box.",
  noAutoRetry: "Nothing was sent again on its own — asking again starts a new billable run.",

  /** H7, when the failure happened after the thread already existed. */
  orphanSentence: "An empty thread was created before this failed.",
  orphanAction: "Open the empty thread",

  /**
   * The accessible name of the process strip (03 §1.4's `[process]` row).
   * It is a legend for the trace spine the reader is about to meet, so it
   * is a named list rather than four decorative words.
   */
  processLabel: "What happens after you ask",

  /** The accessible name of the composer's own region. */
  regionLabel: "Ask a research question",
} as const;
