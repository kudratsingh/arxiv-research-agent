/**
 * The copy gate for `web/lib/copy/spine.ts` (WO-15).
 *
 * `web/tests/copy/forbidden.test.ts` walks WO-12's three modules and is
 * closed over them by construction — its `MODULES` map is a literal, and
 * that file is not this work order's to edit. So the fourth copy module
 * brings its own gate, built to the same five rules and REUSING WO-12's
 * exported utilities rather than restating a single pattern:
 *
 *   1. Walk every exported value recursively (`collectCopyStrings`) and
 *      apply 03 §5.5's deny-list plus seam S6's ownership prohibition.
 *   2. Drive every exported function and apply the same list to the output,
 *      because "3 checkpoints observed on this connection" is composed.
 *   3. Assert the set of functions driven EQUALS the set the walker found,
 *      so a new composer cannot be added without an entry here.
 *   4. Assert the required qualifiers positively — a deny-list cannot
 *      produce "on this connection".
 *   5. Additionally: assert that this module COMPOSES `run.ts` rather than
 *      restating it, which is the property that keeps WO-12's single edit
 *      site single.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

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
import * as composerCopy from "@/lib/copy/composer";
import * as runCopy from "@/lib/copy/run";
import * as spineCopy from "@/lib/copy/spine";
import * as traceCopy from "@/lib/copy/trace";

const walked = collectCopyStrings(spineCopy);

const STORED: CopyString[] = walked.strings.map((found) => ({
  ...found,
  path: `spine.${found.path}`,
}));

const FUNCTION_PATHS = walked.functions.map((found) => `spine.${found}`).sort();

/** A neutral node label. H11: real ones are opaque and pass through. */
const NODE = "synthesizer";

const COMPOSED: Record<string, string[]> = {
  "spine.segmentLabel": [
    spineCopy.segmentLabel("Question", runCopy.RUN_STATUS_WORD.observed),
    spineCopy.segmentLabel("Run", runCopy.RUN_STATUS_WORD.notObserved),
    spineCopy.segmentLabel("Report", runCopy.RUN_STATUS_WORD.expired),
  ],
  "spine.observationDetail": [
    spineCopy.observationDetail(0),
    spineCopy.observationDetail(1, 41),
    spineCopy.observationDetail(3, null),
    spineCopy.observationDetail(41, 7300),
  ],
  "spine.detailSeparator": [
    spineCopy.detailSeparator(spineCopy.SPINE.running),
    spineCopy.detailSeparator(runCopy.RUN_STATUS_LINE.reconnecting),
  ],
};

const COMPOSED_STRINGS: CopyString[] = Object.entries(COMPOSED).flatMap(
  ([path_, values]) => values.map((value) => ({ path: path_, value })),
);

const EVERY_STRING = [...STORED, ...COMPOSED_STRINGS];

// ---------------------------------------------------------------------------

describe("the gate covers the whole of lib/copy/spine.ts", () => {
  it("found strings and functions to gate", () => {
    expect(STORED.length).toBeGreaterThan(8);
    expect(FUNCTION_PATHS.length).toBeGreaterThan(0);
  });

  it("drives every exported function — a new composer cannot skip the gate", () => {
    expect(Object.keys(COMPOSED).sort()).toEqual(FUNCTION_PATHS);
  });

  it("produced at least one string from every one of them", () => {
    for (const [path_, values] of Object.entries(COMPOSED)) {
      expect(values.length, path_).toBeGreaterThan(0);
      for (const value of values) expect(typeof value, path_).toBe("string");
    }
  });
});

describe("03 §5.5's forbidden strings", () => {
  it.each(FORBIDDEN_PHRASES)("nothing says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("in particular, nothing here says 'unknown' or claims a current stage", () => {
    for (const entry of EVERY_STRING) {
      expect(/\bunknown\b/i.test(entry.value), entry.path).toBe(false);
      expect(findForbidden(entry.value, DENY_LIST), entry.path).toEqual([]);
    }
  });
});

describe("seam S6 and RC-12's lexicon", () => {
  it.each(OWNERSHIP_PHRASES)("nothing says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it.each(LEXICON_PHRASES)("no user-facing string says $id", (phrase) => {
    const offenders = EVERY_STRING.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it("uses the lexicon's own nouns for the things it names", () => {
    const all = EVERY_STRING.map((entry) => entry.value).join("\n");
    expect(all).toMatch(/\bruns?\b/i);
    expect(all).toMatch(/\bcheckpoints?\b/i);
  });
});

describe("03 §5.5's required qualifiers", () => {
  it("'on this connection' travels with every count this module produces", () => {
    for (const count of [0, 1, 3, 41]) {
      expect(spineCopy.observationDetail(count)).toContain(REQUIRED_QUALIFIERS.count);
      expect(spineCopy.observationDetail(count, 41)).toContain(REQUIRED_QUALIFIERS.count);
    }
    // And the two stored strings that state a count in prose.
    expect(spineCopy.SPINE.ledgerEmpty).toContain(REQUIRED_QUALIFIERS.count);
    expect(spineCopy.SPINE.ledgerLabel).toContain(REQUIRED_QUALIFIERS.count);
  });

  it("no stored or composed string counts checkpoints without the qualifier", () => {
    const counting = EVERY_STRING.filter((entry) => /\bcheckpoints?\b/i.test(entry.value));
    expect(counting.length).toBeGreaterThan(0);
    for (const entry of counting) {
      if (!/\d+\s+checkpoints?\b|no checkpoints/i.test(entry.value)) continue;
      expect(entry.value, entry.path).toContain(REQUIRED_QUALIFIERS.count);
    }
  });

  it("'not reported' replaces 'unknown' in both places this module is silent", () => {
    expect(spineCopy.SPINE.voidDescription).toContain(REQUIRED_QUALIFIERS.silence);
    expect(spineCopy.SPINE.notReportedYet).toContain(REQUIRED_QUALIFIERS.silence);
  });

  it("'observed' is how the ledger's own label names checkpoints", () => {
    expect(spineCopy.SPINE.ledgerLabel).toContain(REQUIRED_QUALIFIERS.named);
    expect(spineCopy.SPINE.voidWord).toBe(runCopy.RUN_STATUS_WORD.notObserved);
  });
});

describe("criterion 1's single edit site survives a fourth module", () => {
  const source = readFileSync(
    path.join(process.cwd(), "lib", "copy", "spine.ts"),
    "utf8",
  );

  it("composes the dictionary's sentences rather than restating them", () => {
    // Every sentence the spine renders is WO-12's. This module contributes
    // structure (names, joiners) and exactly one status word.
    expect(spineCopy.SPINE.voidWord).toBe(traceCopy.RUN_STATUS_WORD.notObserved);
    expect(spineCopy.SPINE.voidDescription).toBe(
      traceCopy.RUN_STATUS_LINE.positionNotReported,
    );
    expect(spineCopy.SPINE.ledgerEmpty).toBe(`${traceCopy.checkpointCount(0)}.`);
    expect(source).toContain('from "./trace"');
  });

  it("run.ts still offers every name it offered before the split", () => {
    // `trace.ts` is a file boundary, not a rename: `run.ts` re-exports it,
    // so `@/lib/copy/run`, `@/lib/copy` and `lib/job/machine.ts` see the
    // same export set, and `web/tests/copy/forbidden.test.ts` — which this
    // work order may not edit — walks the same names off the same
    // namespace.
    for (const name of Object.keys(traceCopy)) {
      expect(runCopy, name).toHaveProperty(name);
      expect(
        (runCopy as Record<string, unknown>)[name],
        name,
      ).toBe((traceCopy as Record<string, unknown>)[name]);
    }
  });

  it("pins the one sentence that has two declaration sites", () => {
    // 03 §5.4's submitting row and the composer's in-flight button label
    // are the same words in two files, because WO-13 moved `LANDING` to
    // `./composer.ts` and this work order moved `RUN_STATUS_LINE` to
    // `./trace.ts`, each to keep the other's functions out of the
    // Storybook project's module graph. An import between them would undo
    // one of those moves and put landing copy on `/c/[id]`'s first load.
    // So: two sites, one assertion, and a divergence is a decision rather
    // than a drift. See `lib/copy/trace.ts`'s note on `submitting`.
    expect(composerCopy.LANDING.submitPending).toBe(
      traceCopy.RUN_STATUS_LINE.submitting,
    );
    expect(runCopy.LANDING.submitPending).toBe(traceCopy.RUN_STATUS_LINE.submitting);
    // Neither file imports the other, which is the property the pin exists
    // to make safe.
    expect(readFileSync(path.join(process.cwd(), "lib", "copy", "trace.ts"), "utf8"))
      .not.toContain('from "./composer"');
    expect(readFileSync(path.join(process.cwd(), "lib", "copy", "composer.ts"), "utf8"))
      .not.toContain('from "./trace"');
  });

  it("holds no sentence that also exists verbatim in the run dictionary", () => {
    const runStrings = new Set(
      collectCopyStrings(runCopy).strings.map((entry) => entry.value),
    );
    // The two words it deliberately re-exports through SPINE are the
    // exception and are asserted identical above; everything else must be
    // new, or it belongs in run.ts.
    const shared = STORED.filter(
      (entry) =>
        runStrings.has(entry.value) &&
        entry.path !== "spine.SPINE.voidWord" &&
        entry.path !== "spine.SPINE.voidDescription",
    );
    expect(shared).toEqual([]);
  });

  it("is not re-exported from the barrel, so a route pays only for what it renders", () => {
    const barrel = readFileSync(
      path.join(process.cwd(), "lib", "copy", "index.ts"),
      "utf8",
    );
    expect(barrel).not.toContain("./spine");
  });
});

describe("the joiners", () => {
  it("uses a middot after a phrase and a space after a sentence", () => {
    expect(spineCopy.detailSeparator(spineCopy.SPINE.running)).toBe(
      spineCopy.SPINE.separator,
    );
    expect(spineCopy.detailSeparator(runCopy.RUN_STATUS_LINE.reconnecting)).toBe(
      spineCopy.SPINE.gap,
    );
    // 03 §5.4's running line, reassembled exactly as the table prints it.
    expect(
      [
        spineCopy.SPINE.running,
        spineCopy.detailSeparator(spineCopy.SPINE.running),
        spineCopy.observationDetail(3, 41),
      ].join(""),
    ).toBe("Running · 3 checkpoints observed on this connection · updated 41s ago");
  });

  it("segmentLabel joins a name to its word without inventing a third thing", () => {
    expect(spineCopy.segmentLabel("Run", "observed")).toBe("Run · observed");
    expect(findForbidden(spineCopy.segmentLabel("Run", "not observed"))).toEqual([]);
    expect(spineCopy.observationDetail(1, null)).toBe(runCopy.checkpointCount(1));
  });

  it("never names a checkpoint that was not observed", () => {
    // The label comes from the frame or it does not exist. `NODE` is only
    // here to prove the composed forms carry the qualifier with it.
    expect(runCopy.observedCheckpoint(NODE)).toContain(REQUIRED_QUALIFIERS.named);
    expect(runCopy.checkpointName(null)).toBe(REQUIRED_QUALIFIERS.silence);
  });
});
