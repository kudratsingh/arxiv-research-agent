// The copy dictionary (WO-12).
//
// ONE MODULE IS THE SINGLE EDIT SITE FOR EVERY USER-FACING STRING
// (criterion 1). That is not a tidiness preference. 03 §5.5's copy rules
// and 04 §9.1's honesty rules are rules about *sentences*: "never claim a
// current stage", "no percentage", "not reported rather than unknown",
// "no ownership language before MT-01". A rule about sentences can only be
// enforced where the sentences are, so they are all here, and two
// mechanisms keep them here:
//
//   1. An ESLint rule (`copy/no-inline-text` in `web/eslint.config.mjs`)
//      rejects string literals rendered as text inside
//      `components/patterns/` and `components/features/`. Fixtures in
//      `web/tests/fixtures/copy-*.fixture.tsx` prove it fires.
//   2. `web/tests/copy/forbidden.test.ts` walks every exported value in
//      this directory AND drives every exported function, then applies the
//      §5.5 deny-list and seam S6's ownership prohibition to the result.
//      A key that cannot be reached by the walker fails the coverage
//      assertion rather than escaping the gate.
//
// LAYOUT. One file per surface behind this barrel (06-WORK-ORDERS.md
// §5.6's file-ownership table), so WO-13 … WO-19 add their own file rather
// than queueing on a shared one. Prefer importing the surface module
// directly — `@/lib/copy/run` — over this barrel: every string in here is
// route JavaScript, and a barrel import pulls all three files into a route
// that needed one.
//
// DIRECTION. `lib/job/machine.ts` imports from `lib/copy/run`, never the
// reverse. Copy has no state; the machine has no wording.

import { NOT_REPORTED } from "./errors";

export * from "./errors";
export * from "./learn";
export * from "./ledger";
export * from "./run";
export * from "./threads";

// ---------------------------------------------------------------------------
// The policy the gate enforces.
//
// These are exported so a later work order's copy file can be held to the
// same list without restating it, and so the list itself is reviewable in
// one place rather than reconstructed from a test.
// ---------------------------------------------------------------------------

/** One banned form, with the reason it is banned. */
export interface ForbiddenPhrase {
  id: string;
  pattern: RegExp;
  why: string;
}

/**
 * 03 §5.5's forbidden strings, as patterns.
 *
 * Every one of them is banned because the contract cannot support it, not
 * because it reads badly:
 *
 *   - There is no `node_started` (`streaming.py:25-29`) and
 *     `node_completed` fires *after* a node returns
 *     (`runner.py:952-956`), so nothing can be "currently running" or
 *     "in progress".
 *   - No frame carries a denominator, so "step N of M", any `%` and any
 *     ETA would all have to be invented (H4).
 *   - No terminal payload carries a node (`runner.py:1063-1072`,
 *     `routes.py:857-867`), so "failed in"/"failed during"/"stage"
 *     attribute a failure to something the API never named (H3).
 *   - "almost done" is an ETA wearing a different coat.
 */
export const FORBIDDEN_PHRASES: readonly ForbiddenPhrase[] = [
  {
    id: "currently running",
    pattern: /currently running/i,
    why: "No frame reports a running node; node_completed fires after the fact.",
  },
  {
    id: "in progress",
    pattern: /\bin progress\b/i,
    why: "Same reason: there is no node_started event to base it on.",
  },
  {
    id: "step N of M",
    pattern: /\bstep\s+\d+\s+of\s+\d+/i,
    why: "No denominator exists in any frame.",
  },
  {
    id: "step",
    pattern: /\bsteps?\b/i,
    why: "03 §1.5: a checkpoint is never a step, and sub-questions are never steps.",
  },
  {
    id: "stage",
    pattern: /\bstages?\b/i,
    why: "03 §1.5 and H3: the node vocabulary is configuration-dependent and unnamed by terminal frames.",
  },
  {
    id: "percentage",
    pattern: /%/,
    why: "No denominator exists, so every percentage would be invented.",
  },
  {
    id: "eta",
    pattern: /\beta\b|\bestimated (?:time|completion)\b|\btime remaining\b|\bremaining time\b/i,
    why: "Nothing in the contract predicts a finish time.",
  },
  {
    id: "failed during",
    pattern: /failed during\b/i,
    why: "H3: no terminal payload carries a node.",
  },
  {
    id: "failed in",
    pattern: /failed in\b/i,
    why: "H3: 'after the last observed checkpoint' is the only true form.",
  },
  {
    id: "almost done",
    pattern: /almost done/i,
    why: "An ETA with the number removed is still an ETA.",
  },
  {
    id: "unknown",
    pattern: /\bunknown\b/i,
    why: "03 §5.5: 'not reported' — silence is the API's behaviour, not a gap in ours.",
  },
];

/**
 * Seam S6's ownership prohibition (04 §10), carried by the same gate.
 *
 * There is no user identity to own anything until MT-01, and D-009
 * forbids faking one. This list is the mechanism that keeps S6 enforced
 * rather than remembered: a possessive that implies an account fails a
 * test the moment it is typed, in whichever file it is typed in.
 */
export const OWNERSHIP_PHRASES: readonly ForbiddenPhrase[] = [
  {
    id: "your conversations",
    pattern: /your conversations?\b/i,
    why: "S6: there is no per-user view; every principal sees the same threads.",
  },
  {
    id: "my workspace",
    pattern: /\bmy workspace\b/i,
    why: "S6: the workspace is shared, and the copy says so.",
  },
  {
    id: "my library",
    pattern: /\bmy library\b/i,
    why: "S6: nothing in this product is owned by a user.",
  },
  {
    id: "your account",
    pattern: /\byour account\b/i,
    why: "S6 and 03 §6: there is no account, and a 401 is a server-configuration message.",
  },
];

/**
 * RC-12 register 1 — the lexicon, as the four nouns that have exactly one
 * user-facing word each.
 *
 * Only the unambiguous ones are patterns. 03 §1.5's "we never say" column
 * also lists *request*, *task*, *execution*, *state*, *score* and
 * *session*, and none of those can be banned by substring: "This
 * deployment is not accepting requests from this server" is correct
 * English about an HTTP request, "quality score" is the metric's real
 * name, and 03 §5.4's own approved copy contains "outside this session".
 * Banning them by token would fail the brief's own sentences, so the
 * lexicon is enforced here on the nouns where a substring match IS the
 * error, and by review everywhere else.
 */
export const LEXICON_PHRASES: readonly ForbiddenPhrase[] = [
  {
    id: "conversation",
    pattern: /\bconversations?\b/i,
    why: "03 §1.5: a Conversation is a **Thread** on screen; /conversations stays on the wire.",
  },
  {
    id: "chat",
    pattern: /\bchats?\b/i,
    why: "03 §1.5: not a chat product.",
  },
  {
    id: "job",
    pattern: /\bjobs?\b/i,
    why: "03 §1.5: a Job is a **Run** on screen.",
  },
  {
    id: "node",
    pattern: /\bnodes?\b/i,
    why: "03 §1.5: a node_completed is a **Checkpoint**.",
  },
  {
    id: "phase",
    pattern: /\bphases?\b/i,
    why: "03 §1.5: never a phase.",
  },
];

// ===========================================================================
// BEGIN PEDAGOGY VOCABULARY — owned by WO-W14, APPEND-ONLY BELOW.
//
// A later learning work order adds entries to `PEDAGOGY_PHRASES` inside this
// fence and touches nothing else in this file. That is the coordination rule
// 05-WEDGE-WORK-ORDERS.md §5.4 assigns to this list, and it is why the list
// lives in the dictionary rather than inside a test: it is reviewable in one
// place, and a surface that wants to argue with it has to edit it.
//
// WHY IT IS A SEPARATE LIST AND NOT MORE ROWS IN `FORBIDDEN_PHRASES`. The
// §5.5 deny-list holds for the whole product. This list holds for the copy
// the `(learn)` route group renders, and one of its entries — `score` —
// cannot hold product-wide, for exactly the reason `LEXICON_PHRASES` gives
// about the same word: "quality score" is the research metric's real name
// (`run.qualityLabel`, `metrics.qualityLabel`) and banning it everywhere
// would fail the brief's own sentences. A learning surface is different:
// 01-LEARNING-AGENT.md §4.3 keeps the assessment judge's output as advice to
// the tutor rather than a number shown to the learner, so on these surfaces
// there is no score to name.
//
// WHICH MODULES IT IS APPLIED TO IS *DISCOVERED*, NOT LISTED HERE. The gate
// walks the import graph of `app/(learn)/` and holds every copy module it
// reaches to this list, so WO-W13's session strings in `./learn.ts` — and
// any module a future learning surface introduces — are covered the moment
// they are rendered there, with no list to remember to update. A module the
// walk finds that the gate's own table does not carry fails the coverage
// assertion in `web/tests/copy/forbidden.test.ts` rather than escaping.
// ===========================================================================

/**
 * The pedagogy vocabulary: RR-L09's enforcement point (03 §7).
 *
 * `01-LEARNING-AGENT.md` §4.1 names three allowed currencies of progress —
 * assessment events, repetition history, artifacts — and one banned one:
 * "You are 87% through Transformers" is a claim about a latent variable no
 * LLM judge can measure. `00-VISION.md` §5.5 extends that to the lexicon a
 * learning surface may use at all: **Demonstrated**, never mastered,
 * completed or unlocked; **Ledger**, never profile, XP or stats; **Review
 * due**, never streak.
 *
 * The backend already refuses to *store* such a thing — `BANNED_SCALAR_TOKENS`
 * in `src/learning/progress_store.py` rejects the key at the write boundary,
 * a CHECK constraint rejects it in the database, and `_SCHEDULE_LABEL_PATTERN`
 * bounds what a label may say. This list is the same ban one tier up, where
 * copy could reintroduce by wording what the store refuses by schema: a
 * surface needs no field named `mastery` to render the sentence "87%
 * mastered".
 */
export const PEDAGOGY_PHRASES: readonly ForbiddenPhrase[] = [
  {
    id: "mastery",
    pattern: /\bmaster(?:ed|s|ing|y)?\b/i,
    why: "00 §5.5: a demonstrated capability is **Demonstrated**. Mastery is the latent variable 01 §4.1 says nothing here can measure.",
  },
  {
    id: "percentage of knowledge",
    pattern: /%|\bpercent(?:age|ile)s?\b/i,
    why: "01 §4.1's banned currency: a knowledge percentage has no denominator any event could supply.",
  },
  {
    id: "unlocked",
    pattern: /\bunlock(?:ed|s|ing)?\b/i,
    why: "00 §5.5: content is not withheld and then released; a path is a sequence, not a gate.",
  },
  {
    id: "xp",
    pattern: /\bxp\b|\bexperience points?\b|\bpoints? earned\b|\bearn(?:ed|s)? \d+\b/i,
    why: "00 §5.5: the record of demonstration is the **Ledger**, never XP or stats.",
  },
  {
    id: "streak",
    pattern: /\bstreaks?\b|\bchains?\b|\bfreezes?\b/i,
    why: "00 §5.5: spaced-retrieval continuity is **Review due**, never a streak, chain or freeze.",
  },
  {
    id: "streak guilt",
    pattern:
      /\bdon['’]t (?:break|lose|stop)\b|\bkeep it up\b|\bfalling behind\b|\bfell behind\b|\byou missed\b|\bback on track\b/i,
    why: "00 §5.4: a lapse is a truthful state with a one-tap remedy, not a shame badge. Guilt is not a currency of progress.",
  },
  {
    id: "badge",
    pattern: /\bbadges?\b|\bcertificates?\b|\bcertifications?\b/i,
    why: "00 §5.1: certificates attest attendance. Marcus's shareable proof falls out of the evidence, not out of a ribbon.",
  },
  {
    id: "proficiency",
    pattern: /\bproficien\w*|\bcompetenc\w*/i,
    why: "Mirrors `BANNED_SCALAR_TOKENS` in src/learning/progress_store.py: both read as a knowledge scalar.",
  },
  {
    id: "knowledge scalar",
    pattern:
      /\b(?:knowledge|skill|mastery|learning|comprehension)[ _-](?:level|score|scalar|meter|bar|rating)\b/i,
    why: "01 §4.1: no scalar over a latent variable, whatever it is called.",
  },
  {
    id: "score",
    pattern: /\bscores?\b|\bscored\b|\bscoring\b/i,
    why: "01 §4.3: the judge's output is advice to the tutor, never a number shown to the learner. Learn-surface only — 'quality score' is the research metric's real name.",
  },
  {
    id: "grade",
    pattern: /\bgrades?\b|\bgraded\b|\bgrading\b|\bmarks? out of\b/i,
    why: "01 §4.3 and the tutor prompt's own prohibition: an assessment is `recorded_ungraded`. The surface may not grade what the agent refuses to.",
  },
  {
    id: "dashboard",
    pattern: /\bdashboards?\b/i,
    why: "00 §5.5, the anti-dashboard-soup rule: the daily surface is **Today** and the record is the **Ledger**.",
  },
];

// END PEDAGOGY VOCABULARY — append above this line.
// ===========================================================================

/**
 * The qualifiers 03 §5.5 REQUIRES, as opposed to the phrases it forbids.
 *
 * A deny-list alone cannot produce honest copy: "3 checkpoints" is not on
 * any banned list and is still a claim about the run rather than about the
 * connection. These three are asserted positively.
 */
export const REQUIRED_QUALIFIERS = {
  /** Wherever a checkpoint COUNT appears. */
  count: "on this connection",
  /** Wherever a checkpoint is NAMED. */
  named: "observed",
  /** Instead of "unknown", wherever the API is simply silent. */
  silence: NOT_REPORTED,
} as const;

/** Every banned form: 03 §5.5 plus seam S6. */
export const DENY_LIST: readonly ForbiddenPhrase[] = [
  ...FORBIDDEN_PHRASES,
  ...OWNERSHIP_PHRASES,
];

/**
 * What a `(learn)` copy module is held to: everything above, plus pedagogy.
 *
 * The product-wide list is not relaxed for the learning surfaces — a
 * learning surface may no more invent an ETA than a run surface may. This
 * is `DENY_LIST` with the vocabulary that only makes sense where a learner
 * is reading, and it is the list
 * `web/tests/copy/forbidden.test.ts` applies to every copy module the
 * `(learn)` route group's import graph reaches.
 */
export const LEARN_DENY_LIST: readonly ForbiddenPhrase[] = [
  ...DENY_LIST,
  ...PEDAGOGY_PHRASES,
];

/** The ids of every banned form `text` contains. Empty means clean. */
export function findForbidden(
  text: string,
  list: readonly ForbiddenPhrase[] = DENY_LIST,
): string[] {
  return list.filter((entry) => entry.pattern.test(text)).map((entry) => entry.id);
}

// ---------------------------------------------------------------------------
// The walker the gate uses.
// ---------------------------------------------------------------------------

/** A string found in the dictionary, with the path that reached it. */
export interface CopyString {
  path: string;
  value: string;
}

/**
 * Every string reachable from a copy module's exports, depth-first.
 *
 * Functions are NOT called here — a walker that invented arguments would
 * be guessing at the composed forms, and the gate's whole claim is that
 * the composed forms are enumerated deliberately. `collectCopyStrings`
 * reports them as `path: "<name> (function)"` with no value so the test
 * can assert that every one of them is covered by an explicit case.
 */
export function collectCopyStrings(
  root: unknown,
  prefix = "",
): { strings: CopyString[]; functions: string[] } {
  const strings: CopyString[] = [];
  const functions: string[] = [];

  const visit = (value: unknown, path: string): void => {
    if (typeof value === "string") {
      strings.push({ path, value });
      return;
    }
    if (typeof value === "function") {
      functions.push(path);
      return;
    }
    if (value instanceof RegExp || value === null || typeof value !== "object") {
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((entry, index) => {
        visit(entry, `${path}[${index}]`);
      });
      return;
    }
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      visit(entry, path === "" ? key : `${path}.${key}`);
    }
  };

  visit(root, prefix);
  return { strings, functions };
}
