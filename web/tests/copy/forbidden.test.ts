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
import * as runCopy from "@/lib/copy/run";
import * as threadsCopy from "@/lib/copy/threads";
import {
  DENY_LIST,
  FORBIDDEN_PHRASES,
  LEXICON_PHRASES,
  OWNERSHIP_PHRASES,
  REQUIRED_QUALIFIERS,
  collectCopyStrings,
  findForbidden,
  type CopyString,
} from "@/lib/copy";
import { initialJobState, terminalPhrase } from "@/lib/job/machine";
import type { ApiFailure } from "@/lib/api";
import type { JobDetail } from "@/lib/api";
import type { JobState } from "@/lib/job/types";

// ---------------------------------------------------------------------------
// The dictionary, walked.
// ---------------------------------------------------------------------------

const MODULES = {
  errors: errorsCopy,
  run: runCopy,
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
  it("found strings in all three modules", () => {
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
