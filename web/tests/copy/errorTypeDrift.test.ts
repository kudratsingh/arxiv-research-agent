/**
 * WO-12 criterion 7 — the `error_type` drift test, rebased on ADR 0064.
 *
 * "A test enumerates the `error_type` values the backend can produce and
 * asserts each is mapped or visibly falls through."
 *
 * IT STILL READS PYTHON, NOT A TRANSCRIBED LIST. `error_type` appears in no
 * OpenAPI schema as an enum — `schemas.py` types it `str | None` — so
 * nothing generates the frontend's view of it and a hand-copied list would
 * drift the day somebody adds a `raise`.
 *
 * WHAT CHANGED, AND WHY THIS FILE IS SHORTER.
 *
 * This test used to derive the producible set by hand from five places at
 * once: `job.error_type = "literal"` assignments in `runner.py` and
 * `redriver.py`, their exact line numbers, and `type(exc).__name__` for
 * every `class X(Exception)` under `src/` minus the ones the runner caught
 * by name. That was the best available derivation while the backend had no
 * error taxonomy — and it made two things load-bearing that had no business
 * being load-bearing: the *base class* of an exception, and the *line
 * number* of an assignment.
 *
 * ADR 0064 gave the backend one: `src/errors.py` defines `AppError` with a
 * stable `code`, `ERROR_CODES` as the closed set, and `JOB_ERROR_TYPES` as
 * the subset a *run* can carry. The Python side proves that subset is
 * complete — `tests/test_errors.py::TestTheJobVocabulary` derives it from
 * the runner's assignments, the redriver's, and every `AppError` subclass
 * on the job path, in both directions. So the honest thing for this file to
 * do is read that one declaration rather than re-implement a weaker version
 * of the same derivation in TypeScript.
 *
 * The cross-side guarantee is unchanged and is what matters: a value the
 * backend can produce and this dictionary has no sentence for fails here.
 *
 * THE SCOPE NARROWING THAT USED TO LIVE HERE IS NOW STRUCTURAL. This file
 * used to carry an `OFF_THE_JOB_PATH` exclusion for `src/learning/`,
 * `src/content/` and `src/contracts/` — packages whose exceptions cannot
 * reach `Job.error_type` — plus a guard that re-derived the exclusion from
 * the runner and the graph, because the enumeration was "every exception
 * class under `src/`" and had to be narrowed by hand. Deriving from
 * `JOB_ERROR_TYPES` removes the need: a failure only enters that set by
 * being reachable from the runner, which the Python side proves. The one
 * live obligation the exclusion carried forward is unchanged and belongs to
 * its own card: `src/contracts/` (P0-WO00) has no runtime integration yet,
 * and P0-WO05 must give its failures an `AppError` code — or catch them —
 * when the shared kernel joins the job path. It will fail here if it does
 * neither.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  ERROR_TYPE_COPY,
  MAPPED_ERROR_TYPES,
  UNMAPPED_ERROR_TYPE_COPY,
  describeErrorType,
} from "@/lib/copy/errors";

const WEB_ROOT = path.resolve(__dirname, "..", "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");

function read(...segments: string[]): string {
  return readFileSync(path.join(REPO_ROOT, ...segments), "utf8");
}

const ERRORS_PY = read("src", "errors.py");
const RUNNER = read("src", "api", "runner.py");
const REDRIVER = read("src", "api", "redriver.py");

// ---------------------------------------------------------------------------
// The producible set, read out of `src/errors.py`.
// ---------------------------------------------------------------------------

/** The string members of a `frozenset({...})` bound to `name`. */
function frozensetMembers(source: string, name: string): string[] {
  const declaration = new RegExp(
    `^${name}[^=]*=\\s*frozenset\\(\\s*\\{([\\s\\S]*?)\\}\\s*\\)`,
    "m",
  ).exec(source);
  if (declaration === null) return [];
  return [...(declaration[1] as string).matchAll(/"([a-z0-9_]+)"/g)].map(
    (match) => match[1] as string,
  );
}

const PRODUCIBLE = frozensetMembers(ERRORS_PY, "JOB_ERROR_TYPES").sort();
const ALL_CODES = frozensetMembers(ERRORS_PY, "ERROR_CODES").sort();

// ---------------------------------------------------------------------------

describe("the enumeration reads the real backend", () => {
  it("finds a non-empty closed set and the job subset of it", () => {
    // A regex that silently matched nothing would make every assertion
    // below vacuous, so both sets are proven non-empty and related.
    expect(PRODUCIBLE.length).toBeGreaterThan(0);
    expect(ALL_CODES.length).toBeGreaterThan(PRODUCIBLE.length);
    for (const value of PRODUCIBLE) {
      expect(ALL_CODES, value).toContain(value);
    }
  });

  it("finds the seven deliberate assignments still in the runner and redriver", () => {
    // The literals moved behind class constants (`JobTimeout.code`), so
    // this pins the assignment sites by their class rather than by a
    // string or a line number — a rename now has to change both sides of
    // an import, which the Python type checker sees.
    //
    // The seventh is ADR 0068's dead-letter. It is a *separate*
    // assignment rather than an argument to the reclaim's, precisely so
    // that it stays visible to this file: a code that reached the row
    // through a default parameter would be invisible here, and the
    // first anyone would learn of it is the run rendering "The run
    // failed." forever.
    for (const [source, expression] of [
      [RUNNER, "job.error_type = SessionTurnTimeout.code"],
      [RUNNER, "job.error_type = HitlTimeout.code"],
      [RUNNER, "job.error_type = BudgetExceededSession.code"],
      [RUNNER, "job.error_type = BudgetExceededRun.code"],
      [RUNNER, "job.error_type = JobTimeout.code"],
      [REDRIVER, "job.error_type = ORPHANED_ERROR_TYPE"],
      [REDRIVER, "job.error_type = DEAD_LETTER_ERROR_TYPE"],
    ] as const) {
      expect(source).toContain(expression);
    }
  });

  it("finds the generic branch, and proves it no longer leaks a class name", () => {
    // The finding this whole ADR closes: the generic handler used to
    // write `type(exc).__name__` into the job record, an API body, an
    // SSE frame and a metric attribute.
    expect(RUNNER).toContain("job.error_type = app_error.code");
    expect(RUNNER).not.toMatch(/^\s*job\.error_type = type\(exc\)\.__name__$/m);
    expect(RUNNER).not.toMatch(
      /^\s*job\.error = f"\{type\(exc\)\.__name__\}: \{exc\}"$/m,
    );
  });

  it("the five class names it used to enumerate are gone from the vocabulary", () => {
    // The old second half of this test. Each of these was an `error_type`
    // value; each is now a code. Asserting their absence is what stops a
    // half-finished revert from leaving the dictionary keyed on names the
    // backend can no longer produce.
    for (const legacy of [
      "NoPapersFoundError",
      "ArxivUnavailableError",
      "AllPaperAnalysesFailedError",
      "SynthesizerOutputError",
      "JobCancelledError",
    ]) {
      expect(PRODUCIBLE, legacy).not.toContain(legacy);
      expect(MAPPED_ERROR_TYPES as readonly string[], legacy).not.toContain(
        legacy,
      );
    }
  });
});

describe("criterion 7 — every producible value is mapped or visibly falls through", () => {
  it("enumerates fourteen values", () => {
    // Fourteen since WO-A17 added `upstream_model` — the code a
    // model-provider outage now carries. It had been landing as
    // `internal_unexpected`, which is in this set already, so the count
    // is the only thing that moves when a failure stops being
    // misfiled.
    expect(PRODUCIBLE).toHaveLength(14);
  });

  it.each(PRODUCIBLE)("%s is mapped or falls through with its raw text", (value) => {
    const described = describeErrorType(value, "raw backend message");
    if (described.mapped) {
      expect(Object.hasOwn(ERROR_TYPE_COPY, value)).toBe(true);
      expect(described.sentence.length).toBeGreaterThan(0);
      return;
    }
    // The fall-through branch, and the thing that makes it non-lossy:
    // the generic sentence AND the raw text, both reachable.
    expect(described.sentence).toBe(UNMAPPED_ERROR_TYPE_COPY.sentence);
    expect(described.rawError).toBe("raw backend message");
    expect(described.showRawError).toBe(true);
    expect(described.errorType).toBe(value);
  });

  it("maps all fourteen — the dictionary and the backend agree exactly", () => {
    // Both directions. A fifteenth backend value fails the first half; a
    // mapping entry for a value the backend can no longer produce fails
    // the second, which is what stops the table becoming folklore.
    expect([...MAPPED_ERROR_TYPES].sort()).toEqual(PRODUCIBLE);
  });

  it("would notice a fifteenth value", () => {
    const described = describeErrorType("some_future_code", "boom");
    expect(described.mapped).toBe(false);
    expect(MAPPED_ERROR_TYPES as readonly string[]).not.toContain(
      "some_future_code",
    );
  });

  it("maps no HTTP-boundary code, which is why the subset exists", () => {
    // `ERROR_CODES` also holds forty-odd codes a route answers with —
    // `job_not_found`, `missing_api_key`. A run never becomes one, so
    // requiring a run-failure sentence for them would be inventing copy
    // for states the reader cannot reach.
    for (const value of ["job_not_found", "missing_api_key", "rate_limited"]) {
      expect(ALL_CODES, value).toContain(value);
      expect(PRODUCIBLE, value).not.toContain(value);
    }
  });
});
