/**
 * WO-13 — the fourth copy module, held to WO-12's gate.
 *
 * `web/tests/copy/forbidden.test.ts` walks `errors`, `run` and `threads`.
 * `lib/copy/composer.ts` is a fourth file and would otherwise be a copy
 * module with no gate at all — which is precisely the failure mode WO-12's
 * risk note names: "if it is weak, the honesty constraint degrades to a
 * convention". So this file re-uses the same machinery rather than a
 * lighter version of it: `collectCopyStrings()` for the walk, `DENY_LIST`
 * for 03 §5.5 plus seam S6, `LEXICON_PHRASES` for RC-12, and the same
 * "the gate is not vacuous" check that proves the walker really sees this
 * module's strings.
 *
 * It also asserts the one thing a deny-list cannot: that the composer's
 * copy module does NOT restate 03 §1.4. Criterion 1 asserts the landing
 * copy string-for-string, and a second copy of a string that is asserted
 * verbatim is a second place for it to drift.
 */

import { describe, expect, it } from "vitest";

import * as composerCopy from "@/lib/copy/composer";
import * as runCopy from "@/lib/copy/run";
import {
  DENY_LIST,
  FORBIDDEN_PHRASES,
  LEXICON_PHRASES,
  OWNERSHIP_PHRASES,
  collectCopyStrings,
  findForbidden,
  type CopyString,
} from "@/lib/copy";

const walked = collectCopyStrings(composerCopy, "composer");

/**
 * Every composed string, one entry per exported function.
 *
 * Same discipline as `forbidden.test.ts`: the functions are driven
 * deliberately rather than guessed at by the walker, and the set driven
 * here is asserted equal to the set the walker found, so a new composer
 * with no entry below fails this file instead of slipping past it.
 */
const COMPOSED: Record<string, string[]> = {
  "composer.queryCounter": [0, 1, 999, 1000, 8000, 8001].map((length) =>
    composerCopy.queryCounter(length),
  ),
  "composer.queryOverLimit": [8001, 9000].map((length) =>
    composerCopy.queryOverLimit(length),
  ),
};

/** Every string this module can put on a screen, stored or composed. */
const STRINGS: CopyString[] = [
  ...walked.strings,
  ...Object.entries(COMPOSED).flatMap(([path, values]) =>
    values.map((value) => ({ path, value })),
  ),
];

describe("the gate reaches the whole module", () => {
  it("found the module's strings", () => {
    expect(walked.strings.length).toBeGreaterThan(5);
    for (const entry of STRINGS) expect(typeof entry.value).toBe("string");
  });

  it("drives every exported function — a new composer cannot skip the gate", () => {
    expect(Object.keys(COMPOSED).sort()).toEqual([...walked.functions].sort());
  });

  it("is not vacuous — the walker really rejects a bad string", () => {
    expect(findForbidden("currently running, 40% done, almost done")).toEqual([
      "currently running",
      "percentage",
      "almost done",
    ]);
  });
});

describe("03 §5.5's forbidden strings", () => {
  it.each(FORBIDDEN_PHRASES)("nothing says $id", (phrase) => {
    const offenders = STRINGS.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });
});

describe("seam S6's ownership prohibition (04 §10)", () => {
  it.each(OWNERSHIP_PHRASES)("nothing says $id", (phrase) => {
    const offenders = STRINGS.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("says nothing about a signed-in user", () => {
    const login =
      /\bsign[- ]?in\b|\bsign[- ]?out\b|\blog[- ]?in\b|\blogged in\b|\bpassword\b|\bavatar\b/i;
    expect(STRINGS.filter((entry) => login.test(entry.value))).toEqual([]);
  });
});

describe("RC-12 — the lexicon", () => {
  it.each(LEXICON_PHRASES)("no string says $id", (phrase) => {
    const offenders = STRINGS.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("uses 'thread' and 'run', which are the two nouns it needs", () => {
    const all = STRINGS.map((entry) => entry.value).join("\n");
    expect(all).toMatch(/\bthreads?\b/i);
    expect(all).toMatch(/\bruns?\b/i);
  });

  it("passes the whole deny-list, string by string", () => {
    for (const entry of STRINGS) {
      expect(findForbidden(entry.value, DENY_LIST), entry.path).toEqual([]);
    }
  });
});

describe("H12 — nothing here advertises skipping the review pause", () => {
  it("offers no bypass", () => {
    const bypass =
      /\bbypass\b|skip (?:the )?(?:review|plan)|without review|run (?:it )?(?:straight|directly)/i;
    expect(STRINGS.filter((entry) => bypass.test(entry.value))).toEqual([]);
  });
});

describe("criterion 1 — 03 §1.4 still has exactly one home", () => {
  it("run.ts re-exports the landing surface rather than copying it", () => {
    // WO-13 moved §1.4 out of `run.ts` so a composer story stops dragging
    // the spine's dictionary into the Storybook project. The names have to
    // stay reachable at their old paths — `web/tests/copy/forbidden.test.ts`
    // walks the run namespace and drives `run.queryCounter` — and they have
    // to be the SAME objects, not a second copy that can drift.
    expect(runCopy.LANDING).toBe(composerCopy.LANDING);
    expect(runCopy.MAX_QUERY_LEN).toBe(composerCopy.MAX_QUERY_LEN);
    expect(runCopy.queryCounter).toBe(composerCopy.queryCounter);
    expect(runCopy.queryOverLimit).toBe(composerCopy.queryOverLimit);
  });

  it("keeps the run status line pinned to the landing button's pending word", () => {
    // `run.ts` imports `LANDING` back for this one line, which is what
    // makes "Generate plan" → "Generating plan…" one decision rather than
    // two strings that happen to agree today (03 §1.4's first note).
    expect(runCopy.RUN_STATUS_LINE.submitting).toBe(
      composerCopy.LANDING.submitPending,
    );
  });

  it("states the bound once, and it is the backend's", () => {
    expect(composerCopy.MAX_QUERY_LEN).toBe(8000);
    expect(composerCopy.queryCounter(0)).toBe("0 / 8,000");
  });
});

describe("H6 — the failure copy promises no automatic retry", () => {
  it("says nothing was re-sent, and names the cost of asking again", () => {
    expect(composerCopy.COMPOSER.noAutoRetry).toMatch(/nothing was sent again/i);
    expect(composerCopy.COMPOSER.noAutoRetry).toMatch(/billable/i);
    // "Retrying" as a promise the client makes is exactly what R-01
    // forbids; the sentence must not read as one.
    expect(composerCopy.COMPOSER.noAutoRetry).not.toMatch(/we (?:will )?(?:retry|try)/i);
  });

  it("H7 — the orphan thread is named as a thread, and offered", () => {
    expect(composerCopy.COMPOSER.orphanSentence).toMatch(/\bthread\b/);
    expect(composerCopy.COMPOSER.orphanAction).toMatch(/\bthread\b/);
  });
});
