/**
 * WO-12 criteria 2 and 3 — the forbidden-string gate.
 *
 * REVIEW.md's blocking finding 2 is the reason this file exists, and
 * WO-12's own risk note says the quiet part: "if it is weak, the honesty
 * constraint degrades to a convention." So the gate is built to be hard to
 * pass accidentally:
 *
 *   1. It walks EVERY exported value of every copy module, recursively, and
 *      applies 03 §5.5's deny-list plus seam S6's ownership prohibition to
 *      every string it finds.
 *   2. It drives EVERY exported function and applies the same list to the
 *      output, because "3 checkpoints" is composed, not stored, and a gate
 *      over constants alone would never see it.
 *   3. It asserts that the set of functions it drove equals the set of
 *      functions the walker found. A new composer with no entry in the
 *      table below fails this file rather than slipping past it.
 *   4. It asserts the three REQUIRED qualifiers positively, because a
 *      deny-list cannot produce "on this connection" — it can only fail to
 *      forbid its absence.
 *   5. It carries WO-10's terminal allow-list, which travelled here with
 *      the wording it guards.
 *
 * WHAT IS DELIBERATELY NOT GATED. Values that originate OUTSIDE this
 * dictionary — a node label (H11: passed through verbatim), a thread title
 * (the user's own words), the backend's `error` string (RC-16: shown
 * unedited or not at all) — are driven with neutral placeholders. The gate
 * is over the words this product chose, and sanitising the backend's would
 * be the lossiness RC-16 forbids.
 */

import { describe, expect, it } from "vitest";

import * as errorsCopy from "@/lib/copy/errors";
import * as learnCopy from "@/lib/copy/learn";
import * as ledgerCopy from "@/lib/copy/ledger";
import * as reportCopy from "@/lib/copy/report";
import * as runCopy from "@/lib/copy/run";
import * as shellCopy from "@/lib/copy/shell";
import * as threadsCopy from "@/lib/copy/threads";
import {
  DENY_LIST,
  FORBIDDEN_PHRASES,
  LEARN_DENY_LIST,
  LEXICON_PHRASES,
  OWNERSHIP_PHRASES,
  PEDAGOGY_PHRASES,
  REQUIRED_QUALIFIERS,
  collectCopyStrings,
  findForbidden,
  type CopyString,
} from "@/lib/copy";
import { initialJobState, terminalPhrase } from "@/lib/job/machine";
import type { ApiFailure } from "@/lib/api";
import type { JobDetail } from "@/lib/api";
import type { JobState } from "@/lib/job/types";

import { readFileSync } from "node:fs";
import { join, sep } from "node:path";

import * as plantedCopy from "../fixtures/copy-pedagogy.fixture";
import {
  WEB_ROOT,
  copyModulesRenderedBy,
  reachableFrom,
  sourceFilesUnder,
} from "../support/copyGraph";

// ---------------------------------------------------------------------------
// The dictionary, walked.
// ---------------------------------------------------------------------------

/**
 * The modules this file walks and drives.
 *
 * WO-W14 ADDED THREE, AND TWO OF THEM ARE NOT ITS OWN. `ledger` is this
 * work order's surface. `shell` is WO-08's and `report` is WO-18's, and
 * both are here because the `(learn)` route group renders them: the
 * learning routes mount `WorkbenchShell`, and WO-W13's session view renders
 * `ReportReader` for the briefing companion. Their strings are
 * learning-surface strings, so the pedagogy gate below has to see them —
 * and this table is where a module's COMPOSERS get driven, which is the
 * half a per-module sibling test does not do.
 *
 * `shell.ts` exports no composer (`tests/copy/shell-copy.test.ts` pins
 * that); `report.ts` exports two, driven below. The overlap with
 * `report-copy.test.ts` and `shell-copy.test.ts` is deliberate duplication
 * of a cheap check, not a replacement for either.
 */
const MODULES = {
  errors: errorsCopy,
  learn: learnCopy,
  ledger: ledgerCopy,
  report: reportCopy,
  run: runCopy,
  shell: shellCopy,
  threads: threadsCopy,
} as const;

const walked = Object.entries(MODULES).map(([name, module]) => ({
  name,
  ...collectCopyStrings(module),
}));

/** Every stored string, with `<module>.<path>` so a failure names itself. */
const STORED: CopyString[] = walked.flatMap((entry) =>
  entry.strings.map((found) => ({ ...found, path: `${entry.name}.${found.path}` })),
);

/** Every exported function, same naming. */
const FUNCTION_PATHS = walked
  .flatMap((entry) => entry.functions.map((found) => `${entry.name}.${found}`))
  .sort();

/**
 * Wire identifiers that live in the dictionary on purpose.
 *
 * `MAPPED_ERROR_TYPES` is the backend's own `error_type` list — the drift
 * test compares it against Python, so it has to be the API's spelling, not
 * a translation. `SPINE_LEGEND[].mark` names a shape in
 * `components/primitives/marks.tsx`. `rawErrorEvidence`'s labels are the
 * API's field names, deliberately, because the reader is about to paste
 * them into an issue (RC-16).
 *
 * These are exempt from the LEXICON check only. The §5.5 deny-list and
 * S6's ownership list still apply to every one of them.
 */
const WIRE_IDENTIFIER = (path: string): boolean =>
  /^errors\.MAPPED_ERROR_TYPES\[\d+\]$/.test(path) ||
  /^run\.SPINE_LEGEND\[\d+\]\.mark$/.test(path);

// ---------------------------------------------------------------------------
// Composed strings. One entry per exported function, driven deliberately.
// ---------------------------------------------------------------------------

/** A minimal `ApiFailure` per kind — enough for `describeFailure`. */
const FAILURES: ApiFailure[] = [
  { kind: "unauthorized", status: 401, message: "", raw: null },
  { kind: "not_found", status: 404, message: "", raw: null },
  { kind: "conflict", status: 409, message: "", raw: null },
  { kind: "conflict", status: 409, state: "running", message: "", raw: null },
  { kind: "conflict", status: 409, state: "pending_review", message: "", raw: null },
  // A status this client has never heard of: the qualifier, not the wire word.
  { kind: "conflict", status: 409, state: "reticulating", message: "", raw: null },
  { kind: "rate_limited", status: 429, retryAfterSec: 60, message: "", raw: null },
  {
    kind: "rate_limited",
    status: 429,
    retryAfterSec: 900,
    limitPerHour: 20,
    message: "",
    raw: null,
  },
  { kind: "validation", status: 422, fields: [], message: "", raw: null },
  {
    kind: "validation",
    status: 422,
    fields: [{ path: "query", message: "is too long" }],
    message: "",
    raw: null,
  },
  {
    kind: "validation",
    status: 422,
    fields: [
      { path: "query", message: "is too long" },
      { path: "conversation_id", message: "is not a uuid" },
    ],
    message: "",
    raw: null,
  },
  { kind: "upstream_unavailable", status: 502, message: "", raw: null },
  { kind: "proxy_misconfigured", status: 503, message: "", raw: null },
  { kind: "server_error", status: 500, message: "", raw: null },
  { kind: "offline", message: "", raw: null },
  { kind: "timeout", message: "", raw: null },
  { kind: "cancelled", message: "", raw: null },
  { kind: "unknown", status: null, message: "", raw: null },
];

/** A neutral node label. H11: real ones are opaque and pass through. */
const NODE = "synthesizer";

const COMPOSED: Record<string, string[]> = {
  "errors.retryAfterPhrase": [1, 2, 59, 60, 61, 90, 3600, 7200].map((seconds) =>
    errorsCopy.retryAfterPhrase(seconds),
  ),
  "errors.rateLimitCeiling": [1, 20, 1000].map((limit) =>
    errorsCopy.rateLimitCeiling(limit),
  ),
  "errors.rateLimitRecovery": [
    errorsCopy.rateLimitRecovery(60),
    errorsCopy.rateLimitRecovery(900, 20),
  ],
  "errors.validationRecovery": [
    errorsCopy.validationRecovery([]),
    errorsCopy.validationRecovery([{ path: "query", message: "is too long" }]),
    errorsCopy.validationRecovery([
      { path: "query", message: "is too long" },
      { path: "conversation_id", message: "is not a uuid" },
    ]),
  ],
  "errors.describeFailure": FAILURES.flatMap((failure) => {
    const copy = errorsCopy.describeFailure(failure);
    return [copy.word, copy.sentence, copy.recovery];
  }),
  // Only OUR half. `rawError` is the backend's message and is rendered
  // unedited by design (RC-16); gating it would mean editing it.
  "errors.describeErrorType": [
    ...errorsCopy.MAPPED_ERROR_TYPES,
    "SomeFutureExceptionName",
    "",
  ]
    .map((errorType) => errorsCopy.describeErrorType(errorType, "raw backend text"))
    .flatMap((described) => [described.sentence, described.recovery]),
  // Same: the labels and the absence value are ours, the values are not.
  "errors.rawErrorEvidence": [
    ...errorsCopy.rawErrorEvidence(null, null).flatMap((row) => [row.label, row.value]),
    ...errorsCopy.rawErrorEvidence("orphaned", "x").map((row) => row.label),
  ],
  // WO-W13b's start refusals. Driven over every `ApiFailure` kind AND over
  // every `detail` code `POST /learn/sessions` raises, because the mapping is
  // keyed on the code rather than on the kind. Only `message` is gated:
  // `detail` is the service's own word, rendered unedited (RC-16), which is
  // the same rule `errors.describeErrorType`'s entry above follows.
  "learn.describeSessionStart": [
    null,
    ...FAILURES,
    ...[
      "session_loop_disabled",
      "session_loop_requires_auth",
      "learner_profile_required",
      "learn_content_invalid",
      "learn_path_not_found",
      "learn_resource_not_found",
      "briefing_companion_required",
      "a_code_this_dictionary_has_never_seen",
    ].map(
      (detail): ApiFailure => ({
        kind: "not_found",
        status: 404,
        message: "",
        raw: { detail },
      }),
    ),
  ].map((failure) => learnCopy.describeSessionStart(failure).message),
  // WO-W14's Ledger. The kind and the schedule label arrive from the wire,
  // so both are driven with the API's own spellings plus a value this
  // surface has never seen — the fallback is ours and is gated, the wire's
  // word is not ours to edit (the H11 rule, applied to a learning event).
  "ledger.evidenceKindLabel": [
    ...Object.keys(ledgerCopy.EVIDENCE_KIND_LABEL),
    "a_kind_with_no_producer",
    "",
  ].map((kind) => ledgerCopy.evidenceKindLabel(kind)),
  // `null` for a timestamp with no date, filtered exactly as
  // `run.lastUpdated` is: there is no sentence to gate when there is no
  // sentence.
  "ledger.recordedOn": ["2026-08-24T09:40:00.000000Z", "2026-08-24", "", "nope"]
    .map((ts) => ledgerCopy.recordedOn(ts))
    .filter((line): line is string => line !== null),
  "ledger.foldedFrom": [0, 1, 8, 41].map((count) => ledgerCopy.foldedFrom(count)),
  "ledger.assessmentCount": [1, 2, 12].map((count) =>
    ledgerCopy.assessmentCount(count),
  ),
  // The two shapes `_SCHEDULE_LABEL_PATTERN` in
  // src/learning/progress_store.py permits, and nothing else can reach here.
  "ledger.scheduleFigure": [
    "3 of 3 sessions",
    "0 of 12 sessions",
    "1 session recorded",
    "0 sessions recorded",
  ].map((label) => ledgerCopy.scheduleFigure(label)),
  "ledger.withheldEvidence": [0, 1, 2, 41]
    .map((count) => ledgerCopy.withheldEvidence(count))
    .filter((line): line is string => line !== null),
  // WO-18's region labels, reachable from `(learn)` through the session
  // view's `ReportReader`. The ordinal comes from the document's own order.
  "report.tableRegionLabel": [1, 2, 12].map((ordinal) =>
    reportCopy.tableRegionLabel(ordinal),
  ),
  "report.codeRegionLabel": [1, 2, 12].map((ordinal) =>
    reportCopy.codeRegionLabel(ordinal),
  ),
  "run.queryCounter": [0, 1, 999, 1000, 8000, 8001].map((length) =>
    runCopy.queryCounter(length),
  ),
  "run.queryOverLimit": [8001, 9000].map((length) => runCopy.queryOverLimit(length)),
  "run.checkpointCount": [0, 1, 2, 41].map((count) => runCopy.checkpointCount(count)),
  "run.checkpointName": [runCopy.checkpointName(null), runCopy.checkpointName(NODE)],
  "run.observedCheckpoint": [
    runCopy.observedCheckpoint(null),
    runCopy.observedCheckpoint(NODE),
  ],
  "run.lastUpdated": [0, 41, 60, 125, 3600, 7300]
    .map((seconds) => runCopy.lastUpdated(seconds))
    .filter((line): line is string => line !== null),
  "run.runningStatusLine": [
    runCopy.runningStatusLine(0),
    runCopy.runningStatusLine(1, 41),
    runCopy.runningStatusLine(3, null),
    runCopy.runningStatusLine(3, 7300),
  ],
  "run.failedStatusLine": [
    runCopy.failedStatusLine(null),
    runCopy.failedStatusLine(""),
    runCopy.failedStatusLine(NODE),
  ],
  "run.completedStatusLine": [
    runCopy.completedStatusLine({}),
    runCopy.completedStatusLine({ elapsedSec: 74.3 }),
    runCopy.completedStatusLine({
      elapsedSec: 74.3,
      qualityScore: 0.86,
      costUsd: 0.4231,
      llmCalls: 11,
    }),
    runCopy.completedStatusLine({ elapsedSec: 1, llmCalls: 1 }),
  ],
  "run.failedPhrase": [
    runCopy.failedPhrase(null),
    runCopy.failedPhrase(""),
    runCopy.failedPhrase(NODE),
  ],
  "threads.turnCount": [0, 1, 7].map((count) => threadsCopy.turnCount(count)),
  // WO-20's collapsed row name. `0` and a fraction are driven too, because
  // the ordinal arrives from the wire and the floor is this function's.
  "threads.turnLabel": [0, 1, 2.7, 12].map((ordinal) =>
    threadsCopy.turnLabel(ordinal),
  ),
  // The title is the user's own question. Neutral placeholder: the gate is
  // over the sentence around it.
  "threads.deleteDialog": [
    threadsCopy.deleteDialog(""),
    threadsCopy.deleteDialog("Retrieval-augmented evaluation"),
  ].flatMap((dialog) => Object.values(dialog)),
};

const COMPOSED_STRINGS: CopyString[] = Object.entries(COMPOSED).flatMap(
  ([path, values]) => values.map((value) => ({ path, value })),
);

const EVERY_STRING = [...STORED, ...COMPOSED_STRINGS];

// ---------------------------------------------------------------------------
// The gate.
// ---------------------------------------------------------------------------

describe("the gate covers the whole dictionary", () => {
  it("found strings in every copy module", () => {
    for (const entry of walked) {
      expect(entry.strings.length, entry.name).toBeGreaterThan(0);
    }
    expect(STORED.length).toBeGreaterThan(100);
  });

  it("drives every exported function — a new composer cannot skip the gate", () => {
    expect(Object.keys(COMPOSED).sort()).toEqual(FUNCTION_PATHS);
  });

  it("produced at least one string from every one of them", () => {
    for (const [path, values] of Object.entries(COMPOSED)) {
      expect(values.length, path).toBeGreaterThan(0);
      for (const value of values) expect(typeof value, path).toBe("string");
    }
  });
});

describe("criterion 2 — 03 §5.5's forbidden strings", () => {
  it.each(FORBIDDEN_PHRASES)("nothing says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("catches a violation when there is one — the gate is not vacuous", () => {
    expect(findForbidden("currently running the reader, 40% done")).toEqual([
      "currently running",
      "percentage",
    ]);
    expect(findForbidden("failed in stage 3")).toEqual(["stage", "failed in"]);
    expect(findForbidden("step 3 of 5, almost done")).toEqual([
      "step N of M",
      "step",
      "almost done",
    ]);
    expect(findForbidden("in progress, ETA 40 seconds")).toEqual(["in progress", "eta"]);
    expect(findForbidden("failed during the reader")).toEqual(["failed during"]);
    expect(findForbidden("the position is unknown")).toEqual(["unknown"]);
  });
});

describe("criterion 2 — seam S6's ownership prohibition (04 §10)", () => {
  it.each(OWNERSHIP_PHRASES)("nothing says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("catches ownership language when there is some", () => {
    expect(findForbidden("Delete all your conversations from my workspace")).toEqual([
      "your conversations",
      "my workspace",
    ]);
    expect(findForbidden("Sign in to your account")).toEqual(["your account"]);
  });

  it("says nothing about a signed-in user anywhere", () => {
    // The 401 is the one place a login prompt would look natural. 03 §6:
    // it is a server-configuration message, and "a disabled login button
    // is still a fake login".
    const login = /\bsign[- ]?in\b|\bsign[- ]?out\b|\blog[- ]?in\b|\blogged in\b|\bpassword\b|\bavatar\b/i;
    const offenders = EVERY_STRING.filter((entry) => login.test(entry.value));
    expect(offenders).toEqual([]);
  });

  it("the 401 reads as server configuration, never as a login prompt", () => {
    const copy = errorsCopy.FAILURE_COPY.unauthorized;
    expect(copy.sentence).toBe(
      "This deployment is not accepting requests from this server.",
    );
    expect(`${copy.sentence} ${copy.recovery}`).toMatch(/server/i);
    expect(findForbidden(`${copy.word} ${copy.sentence} ${copy.recovery}`)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// WO-W14 — the pedagogy honesty gate.
//
// RR-L09 (honesty erosion) is the learning platform's product-integrity
// risk, and 05-WEDGE-WORK-ORDERS.md makes this file its enforcement point
// for every learning surface, present and future. Two things make that more
// than a wish:
//
//   1. THE MODULE SET IS DISCOVERED, NOT LISTED. `copyModulesRenderedBy`
//      walks the import graph of `app/(learn)/` and reports every module
//      under `lib/copy/` the learning routes actually reach. WO-W13's
//      session strings land in `lib/copy/learn.ts`; a later surface will
//      add a file nobody has named yet. Both are covered the moment they
//      are rendered there, and a module the walk finds that `MODULES` above
//      does not carry fails the coverage assertion rather than escaping the
//      gate — the same rule this file already applies to composers.
//   2. THE GATE IS PROVEN BY A FIXTURE THAT MUST FAIL.
//      `tests/fixtures/copy-pedagogy.fixture.ts` is a committed copy module
//      written the way the industry writes one — "87% mastered", XP, a
//      streak, a graded explain-back — and the assertions below name the
//      exact violation for every key in it. A gate nobody has watched fire
//      is a convention.
//
// WHAT THE WALK FOUND WHEN WO-W13 LANDED, RECORDED BECAUSE IT IS THE
// INTERESTING CASE. On WO-W12's tree the `(learn)` group reached four copy
// modules. After the session view it reaches NINE: `report` and `errors`
// because the session renders `ReportReader`, and `run` — with `trace` and
// `composer` behind it — because `SessionDetailSurface` uses
// `lib/job/useJobStream`, whose machine imports `lib/copy/run` for the
// terminal phrase a learner reads. Three consequences, all of them the
// point of designing the gate over the discovered set:
//
//   1. FOUR OF WO-W13's SENTENCES TRIPPED THE LIST AND WERE REWORDED, in
//      `lib/copy/learn.ts` with a note on each. All four were NEGATIONS —
//      "not a grade or a claim of mastery", "no percentage", "not scored as
//      failure" — and the ruling is the one 03 §5.5 already makes about
//      "unknown": the dictionary does not use the word even to deny it. A
//      denial plants the frame it rejects, and a substring gate cannot tell
//      the two apart without a carve-out per sentence, which is how a gate
//      becomes a convention.
//   2. `run` IS GENUINELY IN SCOPE. A learner reads `run.TERMINAL_PHRASE`
//      through the session's job machine, so the module is not exempt.
//   3. ONE KEY INSIDE IT IS NOT REACHABLE and is exempted by path, with a
//      paired assertion rather than a promise. See `PEDAGOGY_EXEMPT`.
// ---------------------------------------------------------------------------

/** Every copy module the `(learn)` route group's import graph reaches. */
const LEARN_MODULES = copyModulesRenderedBy("(learn)");

/**
 * Every module in `lib/copy/`, loaded, so the pedagogy corpus is built from
 * what the walk FOUND rather than from `MODULES` above.
 *
 * The two sets are no longer the same and cannot be made the same. WO-W13's
 * session view renders `ReportReader`, so `report` and `errors` are learning
 * strings now; `lib/job/machine` imports `lib/copy/run`, which re-exports
 * `./trace` wholesale and re-exports `./composer`'s counters. A table keyed
 * by module name would have to choose between duplicating `trace` under two
 * names and leaving it out, and neither is the question this gate asks. The
 * question is "which STRINGS can a learning route render", so the corpus is
 * assembled per discovered module, by value.
 */
const COPY_MODULE_SOURCES = import.meta.glob("../../lib/copy/*.ts", {
  eager: true,
}) as Record<string, Record<string, unknown>>;

const COPY_MODULES_BY_NAME = new Map(
  Object.entries(COPY_MODULE_SOURCES).map(([file, module]) => [
    (file.split("/").pop() as string).replace(/\.ts$/, ""),
    module,
  ]),
);

/** Each discovered module, walked in its own right. */
const LEARN_WALKS = LEARN_MODULES.map((name) => ({
  name,
  ...collectCopyStrings(COPY_MODULES_BY_NAME.get(name) ?? {}),
}));

/**
 * The one path the pedagogy list is NOT applied to, and the proof that goes
 * with it.
 *
 * `run.BRIEFING` is the RESEARCH briefing document's surface — its metrics
 * strip names the run's `quality_score`, and `qualityLabel` is that metric's
 * real name, which is exactly why `score` cannot be banned product-wide.
 * `lib/copy/run` enters the `(learn)` graph through
 * `SessionDetailSurface` → `lib/job/useJobStream` → `lib/job/machine`, which
 * imports it for the TERMINAL PHRASE the session view renders. So the module
 * is genuinely in scope — a learner does read `run.TERMINAL_PHRASE` — while
 * this one key inside it is not reachable from any learning component.
 *
 * A module-granularity gate cannot tell those two apart, so the exemption is
 * PATH-granular and is paired with the assertion below: no component a
 * `(learn)` route reaches may so much as name `BRIEFING`. The day one does,
 * that assertion fails and this exemption has to be argued again rather than
 * silently covering a string a learner can now see. Nothing is removed from
 * `PEDAGOGY_PHRASES`: "Quality score" stays banned everywhere a learning
 * surface can render it.
 */
const PEDAGOGY_EXEMPT = (path: string): boolean =>
  path === "run.BRIEFING.qualityLabel";

/** Every STORED string a `(learn)` route can render. */
const LEARN_STORED: CopyString[] = LEARN_WALKS.flatMap((entry) =>
  entry.strings.map((found) => ({ ...found, path: `${entry.name}.${found.path}` })),
);

/** Every string, stored or composed, that a `(learn)` route can render. */
const LEARN_STRINGS = [
  ...LEARN_STORED,
  ...COMPOSED_STRINGS.filter((entry) =>
    LEARN_MODULES.includes(entry.path.split(".")[0] as string),
  ),
].filter((entry) => !PEDAGOGY_EXEMPT(entry.path));

/** One violation, named so a red run says which string in which module. */
interface Offence {
  path: string;
  value: string;
  id: string;
}

/** The gate itself, as one function, applied to real and planted alike. */
function pedagogyOffences(strings: readonly CopyString[]): Offence[] {
  return strings.flatMap((entry) =>
    findForbidden(entry.value, LEARN_DENY_LIST).map((id) => ({
      path: entry.path,
      value: entry.value,
      id,
    })),
  );
}

/** The planted fixture, walked and driven exactly as a real module is. */
const PLANTED_WALK = collectCopyStrings(plantedCopy);
const PLANTED_STRINGS: CopyString[] = [
  ...PLANTED_WALK.strings.map((found) => ({
    ...found,
    path: `planted.${found.path}`,
  })),
  ...[0, 87, 100].map((percent) => ({
    path: "planted.masteryLine",
    value: plantedCopy.masteryLine(percent),
  })),
];

describe("WO-W14 criterion 2 — the gate covers every (learn) copy module", () => {
  it("discovers the module set from the route group's own imports", () => {
    expect(LEARN_MODULES.length).toBeGreaterThan(0);
    // The two the learning surfaces own today. `learn` is WO-W12's and
    // WO-W13's; `ledger` is this work order's.
    expect(LEARN_MODULES).toContain("learn");
    expect(LEARN_MODULES).toContain("ledger");
  });

  it("holds every discovered module to the gate — a new one cannot escape", () => {
    for (const name of LEARN_MODULES) {
      expect(
        COPY_MODULES_BY_NAME.has(name),
        `${name} was discovered but could not be loaded`,
      ).toBe(true);
      expect(
        LEARN_STRINGS.some((entry) => entry.path.startsWith(`${name}.`)),
        `${name} contributed no string to the gate`,
      ).toBe(true);
    }
  });

  it("drives every composer a (learn) route can reach, under some name", () => {
    // `run` re-exports `./trace` wholesale and `./composer`'s two counters,
    // so a composer can legitimately be driven under a name other than its
    // own file's. What may NOT happen is a composer nothing drives: its
    // output would never meet the pedagogy list even though a learner reads
    // it. Matched on the function name for that reason.
    const driven = new Set(
      Object.keys(COMPOSED).map((path) => path.split(".").pop() as string),
    );
    for (const walk of LEARN_WALKS) {
      for (const fn of walk.functions) {
        expect(driven, `${walk.name}.${fn} is reachable but never driven`).toContain(
          fn,
        );
      }
    }
  });

  it("exempts one path, and only because no learning component can render it", () => {
    // The exemption exists at all: a vacuous carve-out would pass silently.
    const exempt = EVERY_STRING.filter((entry) => PEDAGOGY_EXEMPT(entry.path));
    expect(exempt.map((entry) => entry.path)).toEqual(["run.BRIEFING.qualityLabel"]);
    expect(exempt[0]?.value).toBe("Quality score");

    // And the proof it rests on, checked rather than asserted in prose: no
    // component the `(learn)` routes reach names `BRIEFING`. `lib/copy/run`
    // is in their graph only through `lib/job/machine`'s terminal phrase.
    const reachable = [...reachableFrom(sourceFilesUnder(join(WEB_ROOT, "app", "(learn)")))];
    const components = reachable.filter((file) =>
      file.startsWith(join(WEB_ROOT, "components") + sep),
    );
    expect(components.length).toBeGreaterThan(0);
    for (const file of components) {
      expect(readFileSync(file, "utf8"), file).not.toMatch(/\bBRIEFING\b/);
    }

    // The phrase itself is still banned for anything a learner can read.
    expect(findForbidden("Quality score", LEARN_DENY_LIST)).toEqual(["score"]);
  });

  it("keeps the pedagogy list a strict extension of the product-wide one", () => {
    expect(LEARN_DENY_LIST).toEqual([...DENY_LIST, ...PEDAGOGY_PHRASES]);
    expect(PEDAGOGY_PHRASES.length).toBeGreaterThanOrEqual(10);
    for (const phrase of PEDAGOGY_PHRASES) {
      expect(phrase.why.length, phrase.id).toBeGreaterThan(20);
      expect(phrase.pattern, phrase.id).toBeInstanceOf(RegExp);
    }
  });
});

describe("WO-W14 criterion 2 — no learning surface states a knowledge scalar", () => {
  it.each(PEDAGOGY_PHRASES)("nothing a (learn) route renders says $id", (phrase) => {
    const offenders = LEARN_STRINGS.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("the whole (learn) dictionary is clean under the extended list", () => {
    expect(pedagogyOffences(LEARN_STRINGS)).toEqual([]);
    // Not vacuous: the gate really did look at something.
    expect(LEARN_STRINGS.length).toBeGreaterThan(40);
  });
});

describe("WO-W14 criterion 2 — the planted fixture, which MUST fail", () => {
  it("is shaped like a copy module: constants plus a driven composer", () => {
    expect(PLANTED_WALK.functions).toEqual(["masteryLine"]);
    expect(PLANTED_WALK.strings.length).toBeGreaterThan(5);
  });

  it("fails on '87% mastered'", () => {
    expect(findForbidden("87% mastered", LEARN_DENY_LIST).sort()).toEqual([
      "mastery",
      "percentage",
      "percentage of knowledge",
    ]);
    expect(
      findForbidden(plantedCopy.PLANTED_PEDAGOGY.headline, LEARN_DENY_LIST),
    ).not.toEqual([]);
  });

  it("catches every planted key, not just the headline", () => {
    const offences = pedagogyOffences(PLANTED_STRINGS);
    const caught = new Set(offences.map((offence) => offence.path));
    for (const key of Object.keys(plantedCopy.PLANTED_PEDAGOGY)) {
      expect(caught, key).toContain(`planted.PLANTED_PEDAGOGY.${key}`);
    }
    // The composed form too: a percentage assembled at render time is
    // invisible to any check that only reads stored strings.
    expect(caught).toContain("planted.masteryLine");
  });

  it("names which rule caught what, so a failure is actionable", () => {
    const byKey = (key: keyof typeof plantedCopy.PLANTED_PEDAGOGY): string[] =>
      findForbidden(plantedCopy.PLANTED_PEDAGOGY[key], LEARN_DENY_LIST).sort();

    expect(byKey("scoreLine")).toEqual(["knowledge scalar", "score"]);
    expect(byKey("unlocked")).toEqual(["streak guilt", "unlocked"]);
    expect(byKey("streak")).toEqual(["streak", "streak guilt"]);
    expect(byKey("xp")).toEqual(["xp"]);
    expect(byKey("proficiency")).toEqual(["proficiency"]);
    expect(byKey("badge")).toEqual(["badge"]);
    expect(byKey("dashboard")).toEqual(["dashboard"]);
    expect(byKey("graded")).toEqual(["grade"]);
  });

  it("would have escaped the product-wide list — which is why this list exists", () => {
    // 03 §5.5's deny-list is about a *run*: no ETA, no invented stage, no
    // percentage. It catches the percent sign and nothing else here.
    const caughtByProductWideList = Object.entries(plantedCopy.PLANTED_PEDAGOGY)
      .filter(([, value]) => findForbidden(value, DENY_LIST).length > 0)
      .map(([key]) => key);
    expect(caughtByProductWideList).toEqual(["headline"]);
  });
});

describe("RC-12 — the lexicon, on the nouns a substring match can decide", () => {
  it.each(LEXICON_PHRASES)("no user-facing string says $id", (phrase) => {
    const offenders = EVERY_STRING.filter(
      (entry) => !WIRE_IDENTIFIER(entry.path) && phrase.pattern.test(entry.value),
    );
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("uses the lexicon's four nouns where the concepts appear", () => {
    const all = EVERY_STRING.map((entry) => entry.value).join("\n");
    expect(all).toMatch(/\bthreads?\b/i);
    expect(all).toMatch(/\bruns?\b/i);
    expect(all).toMatch(/\bbriefings?\b/i);
    expect(all).toMatch(/\bcheckpoints?\b/i);
  });

  it("exempts only the wire identifiers it names, and only from this list", () => {
    const exempt = STORED.filter((entry) => WIRE_IDENTIFIER(entry.path));
    expect(exempt.length).toBeGreaterThan(0);
    // The §5.5 and S6 lists still apply to every one of them.
    for (const entry of exempt) {
      expect(findForbidden(entry.value, DENY_LIST), entry.path).toEqual([]);
    }
  });
});

describe("two rulings the dictionary is also the enforcement point for", () => {
  it("H12 / D-010 ruling 5 — nothing offers to skip the review pause", () => {
    // The HITL bypass field stays unavailable in the UI as a stated rule
    // (03 §8.4; the field itself is named only inside lib/api, and
    // tests/api.test.ts enforces that containment by scanning for it —
    // which is why it is not spelled out here). WO-13 enforces that no
    // code path passes it; this enforces that no copy path advertises it,
    // which is the half a component could reintroduce without touching a
    // request.
    const bypass = /\bbypass\b|skip (?:the )?(?:review|plan)|without review|run (?:it )?(?:straight|directly)/i;
    const offenders = EVERY_STRING.filter((entry) => bypass.test(entry.value));
    expect(offenders).toEqual([]);
  });

  it("RC-12 — the dictionary renames link labels, never export filenames", () => {
    // Filenames come from `Content-Disposition` upstream
    // (`src/api/routes.py:385`) and pass through the proxy allowlist
    // untouched. A filename in the copy would be a promise the frontend
    // cannot keep.
    const filename = /[\w-]+\.(?:md|pdf|json|txt|csv)\b/i;
    const offenders = EVERY_STRING.filter((entry) => filename.test(entry.value));
    expect(offenders).toEqual([]);
  });
});

describe("criterion 3 — the required qualifiers", () => {
  it("'on this connection' appears wherever a checkpoint count does", () => {
    const counts = [
      ...[0, 1, 2, 41].map((n) => runCopy.checkpointCount(n)),
      ...[0, 1, 3].map((n) => runCopy.runningStatusLine(n, 41)),
    ];
    for (const line of counts) {
      expect(line, line).toContain(REQUIRED_QUALIFIERS.count);
    }
    // And in the two fixed lines that state a count of zero in prose.
    expect(runCopy.RUN_STATUS_LINE.failedWithoutCheckpoints).toContain(
      REQUIRED_QUALIFIERS.count,
    );
  });

  it("no stored or composed string counts checkpoints without the qualifier", () => {
    const counting = EVERY_STRING.filter((entry) =>
      /\bcheckpoints?\b/i.test(entry.value),
    );
    expect(counting.length).toBeGreaterThan(0);
    for (const entry of counting) {
      const countsThem = /\d+\s+checkpoints?\b|no checkpoints/i.test(entry.value);
      if (!countsThem) continue;
      expect(entry.value, entry.path).toContain(REQUIRED_QUALIFIERS.count);
    }
  });

  it("'observed' appears wherever a checkpoint is named", () => {
    expect(runCopy.observedCheckpoint(NODE)).toContain(REQUIRED_QUALIFIERS.named);
    expect(runCopy.failedStatusLine(NODE)).toContain(REQUIRED_QUALIFIERS.named);
    // A named checkpoint with no qualifier would read as "it is there now".
    expect(runCopy.failedStatusLine(NODE)).toBe(
      `Failed after the last observed checkpoint (${NODE}).`,
    );
  });

  it("'not reported' replaces 'unknown', everywhere", () => {
    expect(REQUIRED_QUALIFIERS.silence).toBe("not reported");
    expect(runCopy.checkpointName(null)).toBe(REQUIRED_QUALIFIERS.silence);
    expect(runCopy.observedCheckpoint(undefined)).toContain(REQUIRED_QUALIFIERS.silence);
    for (const row of errorsCopy.rawErrorEvidence(null, null)) {
      expect(row.value).toBe(REQUIRED_QUALIFIERS.silence);
      expect(row.present).toBe(false);
    }
    // The deny-list carries the other half: nothing may say "unknown".
    for (const entry of EVERY_STRING) {
      expect(/\bunknown\b/i.test(entry.value), entry.path).toBe(false);
    }
  });

  it("never labels a checkpoint that was not observed (03 §5.5)", () => {
    // The label comes from the frame or it does not exist. There is no
    // vocabulary to fall back on, so absence is reported rather than named.
    expect(runCopy.checkpointName("")).toBe(REQUIRED_QUALIFIERS.silence);
    expect(runCopy.failedStatusLine(null)).not.toMatch(/\(/);
    expect(runCopy.failedPhrase(null)).toBe("failed");
  });
});

// ---------------------------------------------------------------------------
// The terminal allow-list, travelled here from WO-10 with the wording.
// ---------------------------------------------------------------------------

describe("H3 — the terminal phrase, allow-listed", () => {
  const FAILED = { ...initialJobState } as JobState;

  function settled(status: JobDetail["status"], node: string | null): JobState {
    return {
      ...FAILED,
      phase: "settled",
      detail: { status } as JobDetail,
      checkpoint:
        node === null ? null : { node, observedAt: 0, stateDelta: {} },
    };
  }

  it("the only shape a failure phrase can take is 'failed' or 'failed after X'", () => {
    for (const node of [null, NODE, "a_node_nobody_has_heard_of"]) {
      expect(runCopy.failedPhrase(node)).toMatch(/^failed( after [^\s]+)?$/);
      expect(terminalPhrase(settled("failed", node))).toMatch(
        /^failed( after [^\s]+)?$/,
      );
    }
  });

  it("the reducer's phrases all come out of the dictionary now", () => {
    const dictionary = new Set<string>([
      ...Object.values(runCopy.TERMINAL_PHRASE),
      runCopy.failedPhrase(null),
      runCopy.failedPhrase(NODE),
    ]);
    const phrases = [
      terminalPhrase({ ...FAILED, phase: "unavailable" }),
      terminalPhrase({ ...FAILED, phase: "submit_failed" }),
      terminalPhrase(settled("succeeded", null)),
      terminalPhrase(settled("cancelled", null)),
      terminalPhrase(settled("failed", null)),
      terminalPhrase(settled("failed", NODE)),
      terminalPhrase({ ...FAILED, phase: "settled" }),
    ];
    for (const phrase of phrases) {
      expect(phrase).not.toBeNull();
      expect(dictionary.has(phrase as string), phrase ?? "null").toBe(true);
    }
  });

  it("no terminal phrase trips the deny-list", () => {
    for (const phrase of Object.values(runCopy.TERMINAL_PHRASE)) {
      expect(findForbidden(phrase), phrase).toEqual([]);
    }
    expect(findForbidden(runCopy.failedPhrase(NODE))).toEqual([]);
    expect(findForbidden(runCopy.UNAVAILABLE_COPY)).toEqual([]);
  });

  it("H8 — the 404 sentence says neither deleted nor no permission", () => {
    expect(runCopy.UNAVAILABLE_COPY).toMatch(/no longer available/);
    expect(runCopy.UNAVAILABLE_COPY).not.toMatch(/deleted|permission|denied/i);
  });
});
