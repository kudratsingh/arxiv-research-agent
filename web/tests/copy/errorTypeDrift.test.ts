/**
 * WO-12 criterion 7 — the `error_type` drift test.
 *
 * "A test enumerates the `error_type` values the backend can produce
 * (`runner.py:1506`, `:1536`, `:1564`, `:1629`, `redriver.py:518`, plus
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
 *   1. Five deliberate literals, assigned to `job.error_type` in
 *      `runner.py` and `redriver.py` (ADR 0057 added the fifth,
 *      `session_turn_timeout`).
 *   2. `type(exc).__name__` at `runner.py:1698`, for every exception class
 *      that can reach the generic handler. An exception the runner catches
 *      by name FIRST cannot: `HitlTimeoutError` becomes `hitl_timeout`,
 *      `SessionTurnTimeoutError` becomes `session_turn_timeout`,
 *      `CostBudgetExceeded` becomes `cost_budget_exceeded`, and
 *      `HitlCancelledError` sets no `error_type` at all because the job is
 *      `cancelled`, not `failed`. So the second half is "every exception
 *      class defined in src/, minus the ones runner.py intercepts", which
 *      is derived here rather than assumed.
 *
 * ONE SCOPE NARROWING, AND IT IS GUARDED. `error_type` is a field on a
 * research `Job`. An exception class in a package the job path never enters
 * cannot become one, and listing it here would force a copy entry for a
 * value the backend cannot produce — precisely the folklore the last test in
 * this file exists to prevent. `src/learning/` (ADR 0058) is such a package:
 * its `ValueError`s are raised in the HTTP profile handlers and converted to
 * a 422 body. The exclusion is not trusted either — `OFF_THE_JOB_PATH` is
 * re-checked against the runner and the graph on every run, so the day a
 * card wires the learning package into a graph node, this file fails and the
 * narrowing has to be revisited.
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

/**
 * Packages whose exceptions cannot reach `Job.error_type`.
 *
 * See the header. Guarded by "the off-the-job-path exclusion is still true"
 * below, which reads the runner and the graph rather than taking this on
 * faith.
 */
const OFF_THE_JOB_PATH = [path.join(SRC, "learning") + path.sep];

function onTheJobPath(file: string): boolean {
  return !OFF_THE_JOB_PATH.some((prefix) => file.startsWith(prefix));
}

/** Exception classes defined under `src/`, on the job path. */
const EXCEPTION_CLASSES = pythonFiles(SRC)
  .filter(onTheJobPath)
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
  it("finds the five deliberate values at their cited sites", () => {
    expect(DELIBERATE).toEqual([
      "cost_budget_exceeded",
      "hitl_timeout",
      "orphaned",
      "session_turn_timeout",
      "timeout",
    ]);
    // The citations themselves, so a moved assignment is noticed rather
    // than silently re-found somewhere the design brief never read. The
    // runner line numbers moved with ADR 0057's kind dispatch, which is
    // this assertion working: a re-citation is a deliberate act.
    expect(RUNNER.split("\n")[1505]).toContain('job.error_type = "session_turn_timeout"');
    expect(RUNNER.split("\n")[1535]).toContain('job.error_type = "hitl_timeout"');
    expect(RUNNER.split("\n")[1563]).toContain('job.error_type = "cost_budget_exceeded"');
    expect(RUNNER.split("\n")[1628]).toContain('job.error_type = "timeout"');
    expect(REDRIVER.split("\n")[517]).toContain("job.error_type = ORPHANED_ERROR_TYPE");
  });

  it("finds the generic branch that turns any other exception into a value", () => {
    expect(RUNNER).toContain("job.error_type = type(exc).__name__");
  });

  it("the off-the-job-path exclusion is still true of the runner and graph", () => {
    // The narrowing in the header, re-derived. Nothing the runner drives may
    // import the excluded package; the moment something does, its exceptions
    // become producible `error_type` values and this exclusion has to go
    // rather than quietly hide them from the copy table.
    const jobPathSources = [
      RUNNER,
      read("src", "api", "jobs.py"),
      read("src", "graph", "workflow.py"),
      read("src", "graph", "state.py"),
    ];
    for (const source of jobPathSources) {
      expect(source).not.toMatch(/\bsrc\.learning\b/);
    }
    // And the excluded package really does exist, so a rename cannot turn
    // the exclusion into a silent no-op that stops excluding anything.
    expect(pythonFiles(SRC).some((file) => !onTheJobPath(file))).toBe(true);
  });

  it("finds the exception classes, and the four the runner intercepts first", () => {
    expect(EXCEPTION_CLASSES).toEqual([
      "AllPaperAnalysesFailedError",
      "ArxivUnavailableError",
      "CostBudgetExceeded",
      "HitlCancelledError",
      "HitlTimeoutError",
      "JobCancelledError",
      "NoPapersFoundError",
      "SessionTurnTimeoutError",
      "SynthesizerOutputError",
    ]);
    for (const name of [
      "HitlTimeoutError",
      "CostBudgetExceeded",
      "HitlCancelledError",
      // ADR 0057. It has to stay a direct `Exception` subclass and it has
      // to stay intercepted: the regex above only recognises the builtin
      // bases, so a shared parking base class would drop both timeout
      // exceptions out of this enumeration entirely.
      "SessionTurnTimeoutError",
    ]) {
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
  it("enumerates ten values", () => {
    expect(PRODUCIBLE).toHaveLength(10);
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

  it("maps all ten — the dictionary and the backend agree exactly", () => {
    // Both directions. An eleventh backend value fails the first half; a
    // mapping entry for a value the backend can no longer produce fails
    // the second, which is what stops the table becoming folklore.
    expect([...MAPPED_ERROR_TYPES].sort()).toEqual(PRODUCIBLE);
  });

  it("would notice an eleventh value", () => {
    const described = describeErrorType("SomeFutureExceptionName", "boom");
    expect(described.mapped).toBe(false);
    expect(MAPPED_ERROR_TYPES).not.toContain("SomeFutureExceptionName");
  });
});
