/**
 * WO-W13b — the start-refusal dictionary, pinned.
 *
 * Two claims this file makes that the forbidden-string gate cannot:
 *
 *   1. **Which refusal maps to which sentence.** The gate proves no sentence
 *      says a banned thing; it does not prove that a flag-off refusal reads
 *      as a flag-off refusal rather than as "something went wrong".
 *   2. **That the mapping table covers exactly what the endpoint raises.**
 *      The `detail` codes are re-derived from `src/api/sessions.py` on every
 *      run, so a new refusal on the backend fails here rather than reaching a
 *      reader as the generic sentence.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { ApiFailure } from "@/lib/api";
import { LEARN, describeSessionStart } from "@/lib/copy/learn";

import { WEB_ROOT } from "../support/copyGraph";

const SESSIONS_PY = join(WEB_ROOT, "..", "src", "api", "sessions.py");
const ERRORS_PY = join(WEB_ROOT, "..", "src", "errors.py");

function failure(detail: unknown, kind: ApiFailure["kind"] = "not_found"): ApiFailure {
  return {
    kind,
    status: 404,
    message: "",
    raw: detail === undefined ? undefined : { detail },
  } as ApiFailure;
}

describe("describeSessionStart", () => {
  it("maps the flag-off refusal to its own sentence", () => {
    expect(describeSessionStart(failure("session_loop_disabled"))).toEqual({
      message: LEARN.startRefusedDisabled,
      detail: null,
    });
  });

  it("maps both principal refusals to one sentence, because they are one situation", () => {
    // `src/config.py`'s ladder: the session loop needs the learner profile,
    // which needs API auth. A reader cannot tell the two apart and the copy
    // does not pretend otherwise.
    for (const detail of ["session_loop_requires_auth", "learner_profile_required"]) {
      expect(describeSessionStart(failure(detail)).message).toBe(
        LEARN.startRefusedPrincipal
      );
    }
  });

  it("maps every content refusal to the content sentence", () => {
    for (const detail of [
      "learn_content_invalid",
      "learn_path_not_found",
      "learn_resource_not_found",
      "briefing_companion_required",
    ]) {
      expect(describeSessionStart(failure(detail)).message).toBe(
        LEARN.startRefusedContent
      );
    }
  });

  it("maps a rate limit and a transport failure to their own sentences", () => {
    expect(
      describeSessionStart({
        kind: "rate_limited",
        status: 429,
        retryAfterSec: 60,
        message: "",
        raw: null,
      }).message
    ).toBe(LEARN.startRefusedRateLimited);
    for (const kind of ["offline", "timeout"] as const) {
      expect(
        describeSessionStart({ kind, message: "", raw: null }).message
      ).toBe(LEARN.startRefusedUnreachable);
    }
  });

  it("falls through to the generic sentence and quotes the service unedited", () => {
    expect(describeSessionStart(failure("something_new_from_the_backend"))).toEqual({
      message: LEARN.startRefusedGeneric,
      detail: "something_new_from_the_backend",
    });
  });

  it("quotes nothing when the service said nothing", () => {
    expect(describeSessionStart(null)).toEqual({
      message: LEARN.startRefusedGeneric,
      detail: null,
    });
    expect(describeSessionStart(failure(undefined)).detail).toBeNull();
    // A non-string `detail` (FastAPI's 422 list, the 429 object) is not a
    // code and is never rendered as one.
    expect(describeSessionStart(failure([{ loc: ["body"], msg: "x" }])).detail).toBeNull();
    expect(describeSessionStart(failure({ error: "rate_limited" })).detail).toBeNull();
  });

  it("never renders a raw sentence this dictionary did not write", () => {
    const sentences = new Set<string>(Object.values(LEARN));
    const cases: ApiFailure[] = [
      failure("session_loop_disabled"),
      failure("learner_profile_required"),
      failure("learn_path_not_found"),
      failure("briefing_companion_required"),
      failure("anything_else"),
      { kind: "server_error", status: 500, message: "boom", raw: "boom" },
      { kind: "unknown", status: null, message: "boom", raw: null },
      {
        kind: "rate_limited",
        status: 429,
        retryAfterSec: 1,
        message: "boom",
        raw: null,
      },
    ];
    for (const one of cases) {
      expect(sentences.has(describeSessionStart(one).message)).toBe(true);
    }
  });
});

describe("the mapping table covers what the endpoint can raise", () => {
  /**
   * Every `detail=` constant `POST /learn/sessions` can answer with.
   *
   * Re-derived from the Python source rather than listed, for the reason
   * `errorTypeDrift.test.ts` re-derives `error_type`: a refusal added on the
   * backend must fail a test here, not arrive at a reader as "The service did
   * not start a session."
   */
  const CREATE_DETAILS = [
    "session_loop_disabled",
    "session_loop_requires_auth",
    "learner_profile_required",
    "learn_content_invalid",
    "learn_path_not_found",
    "learn_resource_not_found",
    "briefing_companion_required",
  ];

  it("is still the complete list of refusals in src/api/sessions.py", () => {
    // ADR 0064 replaced `raise HTTPException(..., detail="...")` with
    // typed `AppError` subclasses, so the derivation follows the raise
    // sites through `src/errors.py` to their codes instead of reading a
    // string literal. Same claim, one indirection deeper — and the
    // indirection is the point: the code IS the `detail`, so the two can
    // no longer disagree.
    const source = readFileSync(SESSIONS_PY, "utf8");
    const errors = readFileSync(ERRORS_PY, "utf8");

    const codeFor = new Map<string, string>();
    for (const match of errors.matchAll(
      /^class (\w+)\([^)]*\):\n(?:.|\n)*?^ {4}code = "([a-z_]+)"$/gm
    )) {
      codeFor.set(match[1]!, match[2]!);
    }

    const found = new Set<string>();
    for (const match of source.matchAll(/raise (\w+)\(/g)) {
      const code = codeFor.get(match[1]!);
      if (code !== undefined) found.add(code);
    }

    // The derivation has to actually resolve something, or every
    // assertion below would pass by finding nothing.
    expect(codeFor.size).toBeGreaterThan(20);
    // `session_not_found` and `session_not_awaiting_learner` belong to the
    // read and turn routes, not to create; they are not this surface's.
    for (const detail of CREATE_DETAILS) {
      expect(found, `${detail} is no longer raised by sessions.py`).toContain(
        detail
      );
    }
  });

  it("gives every one of them a sentence rather than the fall-through", () => {
    for (const detail of CREATE_DETAILS) {
      const described = describeSessionStart(failure(detail));
      expect(described.message, detail).not.toBe(LEARN.startRefusedGeneric);
      expect(described.detail, detail).toBeNull();
    }
  });
});
