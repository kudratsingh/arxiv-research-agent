/**
 * WO-12 criterion 7 — the `error_type` drift test.
 *
 * "A test enumerates the `error_type` values the backend can produce
 * (`runner.py:1057`, `:1085`, `:1150`, `redriver.py:507`, plus
 * `type(exc).__name__` for the named exception classes) and asserts each is
 * mapped or visibly falls through."
 *
 * IT READS PYTHON, NOT A TRANSCRIBED LIST. `error_type` appears in no
 * OpenAPI schema as an enum — `schemas.py:110` types it `str | None` — so
 * nothing generates the frontend's view of it and a hand-copied list would
 * drift the day somebody adds a `raise`. This test derives the producible
 * set from `src/` on every run, exactly the way
 * `tests/test_contract_sse_events.py` derives the SSE event names from the
 * emit sites. No Python is added: the sources already say everything this
 * needs, and reading them from the web suite keeps the check on the side
 * that would otherwise silently render "The run failed." forever.
 *
 * THE PRODUCIBLE SET HAS TWO HALVES.
 *
 *   1. Four deliberate literals, assigned to `job.error_type` in
 *      `runner.py` and `redriver.py`.
 *   2. `type(exc).__name__` at `runner.py:1219`, for every exception class
 *      that can reach the generic handler. An exception the runner catches
 *      by name FIRST cannot: `HitlTimeoutError` becomes `hitl_timeout`,
 *      `CostBudgetExceeded` becomes `cost_budget_exceeded`, and
 *      `HitlCancelledError` sets no `error_type` at all because the job is
 *      `cancelled`, not `failed`. So the second half is "every exception
 *      class defined in src/, minus the ones runner.py intercepts", which
 *      is derived here rather than assumed.
 */

import { readFileSync, readdirSync } from "node:fs";
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
const SRC = path.join(REPO_ROOT, "src");

function read(...segments: string[]): string {
  return readFileSync(path.join(REPO_ROOT, ...segments), "utf8");
}

const RUNNER = read("src", "api", "runner.py");
const REDRIVER = read("src", "api", "redriver.py");

/** Every `.py` under `src/`, recursively. */
function pythonFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return pythonFiles(full);
    return entry.isFile() && entry.name.endsWith(".py") ? [full] : [];
  });
}

// ---------------------------------------------------------------------------
// Half 1 — the deliberate literals.
// ---------------------------------------------------------------------------

/** `job.error_type = "literal"`, wherever it appears. */
function assignedLiterals(source: string): string[] {
  return [...source.matchAll(/job\.error_type\s*=\s*"([a-z_]+)"/g)].map(
    (match) => match[1] as string,
  );
}

/** `job.error_type = SOME_CONSTANT`, resolved through its own `Final[str]`. */
function assignedConstants(source: string): string[] {
  return [...source.matchAll(/job\.error_type\s*=\s*([A-Z][A-Z0-9_]+)\b/g)].flatMap(
    (match) => {
      const name = match[1] as string;
      const declaration = new RegExp(
        `^${name}\\s*(?::\\s*Final\\[str\\]\\s*)?=\\s*"([a-z_]+)"`,
        "m",
      ).exec(source);
      return declaration === null ? [] : [declaration[1] as string];
    },
  );
}

const DELIBERATE = [
  ...assignedLiterals(RUNNER),
  ...assignedLiterals(REDRIVER),
  ...assignedConstants(RUNNER),
  ...assignedConstants(REDRIVER),
].sort();

// ---------------------------------------------------------------------------
// Half 2 — `type(exc).__name__`.
// ---------------------------------------------------------------------------

/** Exception classes defined anywhere under `src/`. */
const EXCEPTION_CLASSES = pythonFiles(SRC)
  .flatMap((file) => [
    ...readFileSync(file, "utf8").matchAll(
      /^class\s+(\w+)\((?:Exception|RuntimeError|ValueError|KeyError|OSError)\):/gm,
    ),
  ])
  .map((match) => match[1] as string)
  .sort();

/** Names `runner.py` catches before the generic `except Exception as exc`. */
const INTERCEPTED = [
  ...RUNNER.slice(0, RUNNER.indexOf("except Exception as exc:")).matchAll(
    /^\s*except\s+([A-Za-z_][\w.]*)/gm,
  ),
]
  .map((match) => (match[1] as string).replace(/^asyncio\./, ""))
  .filter((name) => name !== "Exception");

const FROM_CLASS_NAME = EXCEPTION_CLASSES.filter(
  (name) => !INTERCEPTED.includes(name),
);

const PRODUCIBLE = [...DELIBERATE, ...FROM_CLASS_NAME].sort();

// ---------------------------------------------------------------------------

describe("the enumeration reads the real backend", () => {
  it("finds the four deliberate values at their cited sites", () => {
    expect(DELIBERATE).toEqual([
      "cost_budget_exceeded",
      "hitl_timeout",
      "orphaned",
      "timeout",
    ]);
    // The citations themselves, so a moved assignment is noticed rather
    // than silently re-found somewhere the design brief never read.
    expect(RUNNER.split("\n")[1056]).toContain('job.error_type = "hitl_timeout"');
    expect(RUNNER.split("\n")[1084]).toContain('job.error_type = "cost_budget_exceeded"');
    expect(RUNNER.split("\n")[1149]).toContain('job.error_type = "timeout"');
    expect(REDRIVER.split("\n")[506]).toContain("job.error_type = ORPHANED_ERROR_TYPE");
  });

  it("finds the generic branch that turns any other exception into a value", () => {
    expect(RUNNER).toContain("job.error_type = type(exc).__name__");
  });

  it("finds the exception classes, and the three the runner intercepts first", () => {
    expect(EXCEPTION_CLASSES).toEqual([
      "AllPaperAnalysesFailedError",
      "ArxivUnavailableError",
      "CostBudgetExceeded",
      "HitlCancelledError",
      "HitlTimeoutError",
      "JobCancelledError",
      "NoPapersFoundError",
      "SynthesizerOutputError",
    ]);
    for (const name of ["HitlTimeoutError", "CostBudgetExceeded", "HitlCancelledError"]) {
      expect(INTERCEPTED, name).toContain(name);
    }
    // ...leaving exactly the five 03 §8.3 names, derived rather than typed.
    expect(FROM_CLASS_NAME).toEqual([
      "AllPaperAnalysesFailedError",
      "ArxivUnavailableError",
      "JobCancelledError",
      "NoPapersFoundError",
      "SynthesizerOutputError",
    ]);
  });
});

describe("criterion 7 — every producible value is mapped or visibly falls through", () => {
  it("enumerates nine values", () => {
    expect(PRODUCIBLE).toHaveLength(9);
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

  it("maps all nine — the dictionary and the backend agree exactly", () => {
    // Both directions. A tenth backend value fails the first half; a
    // mapping entry for a value the backend can no longer produce fails
    // the second, which is what stops the table becoming folklore.
    expect([...MAPPED_ERROR_TYPES].sort()).toEqual(PRODUCIBLE);
  });

  it("would notice a tenth value", () => {
    const described = describeErrorType("SomeFutureExceptionName", "boom");
    expect(described.mapped).toBe(false);
    expect(MAPPED_ERROR_TYPES).not.toContain("SomeFutureExceptionName");
  });
});
