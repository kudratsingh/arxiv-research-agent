/**
 * WO-09's copy, held to WO-12's gate — and criterion 3, pinned to the
 * Python that makes it true.
 *
 * `web/lib/copy/recovery.ts` is a fifth surface file in WO-12's dictionary,
 * added under 06-WORK-ORDERS.md §5.6's one-file-per-surface rule so that
 * eight concurrent work orders do not queue on one module. A new file in
 * that directory is only safe if it is gated like the rest of it, so this
 * file re-uses WO-12's own exported machinery — `collectCopyStrings`,
 * `findForbidden`, `DENY_LIST`, `LEXICON_PHRASES` — rather than restating
 * any pattern. Nothing in `web/tests/copy/forbidden.test.ts` is touched; if
 * that gate's list grows, this one grows with it automatically, because
 * both read the same exports.
 *
 * THE SECOND HALF IS CRITERION 3, AND IT IS THE REASON THIS FILE IS LONGER
 * THAN `shell-copy.test.ts`. Honesty rule H8 says a 404 from
 * `GET /conversations/{id}` means "not available" and nothing more precise,
 * because the API answers identically for a thread that never existed and
 * for one belonging to another principal. That is not a style preference —
 * it is `_check_ownership` at `src/api/routes.py:59`, whose own docstring
 * says "leaking 'this exists but you can't touch it' is an info-disclosure
 * vector". So the assertions below read the Python, the way
 * `./errorTypeDrift.test.ts` reads `src/` rather than a transcription of
 * it, and hold the sentence against what the Python actually does. If the
 * backend ever stopped conflating the two cases, this file would go red and
 * the copy would be free to say which one happened.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  DENY_LIST,
  LEXICON_PHRASES,
  collectCopyStrings,
  findForbidden,
} from "@/lib/copy";
import * as globalErrorCopy from "@/lib/copy/globalError";
import { GLOBAL_ERROR } from "@/lib/copy/globalError";
import * as recoveryCopy from "@/lib/copy/recovery";
import { RECOVERY, ROUTE_ERROR } from "@/lib/copy/recovery";
import { THREAD } from "@/lib/copy/threads";

const WEB_ROOT = path.resolve(__dirname, "..", "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");

/**
 * BOTH of WO-09's copy modules, walked as one set.
 *
 * `./globalError.ts` is a separate module for a bundler reason recorded in
 * its own header — webpack inlines a shared module WHOLE into every entry
 * that touches it, so the global boundary's sentences were riding inside
 * both `error.tsx` chunks. Splitting the module must not split the gate,
 * which is what this union is for.
 */
const walked = [
  { name: "recovery", module: recoveryCopy },
  { name: "globalError", module: globalErrorCopy },
].map((entry) => ({ name: entry.name, ...collectCopyStrings(entry.module) }));

const strings = walked.flatMap((entry) =>
  entry.strings.map((found) => ({ ...found, path: `${entry.name}.${found.path}` })),
);
const functions = walked.flatMap((entry) =>
  entry.functions.map((found) => `${entry.name}.${found}`),
);

describe("WO-09's copy modules are inside WO-12's gate", () => {
  it("exports strings the walker can actually reach", () => {
    expect(strings.length).toBeGreaterThan(0);
    for (const entry of strings) {
      expect(entry.value.trim(), `${entry.path} is empty`).not.toBe("");
    }
  });

  it("exports no function, so there is no composed form to enumerate", () => {
    // The moment this file grows a composer, it owes the same
    // drive-every-function treatment forbidden.test.ts gives run.ts. Failing
    // here is how that obligation is noticed.
    expect(functions).toEqual([]);
  });

  it.each(strings.map((entry) => [entry.path, entry.value]))(
    "%s carries no forbidden phrase",
    (path_, value) => {
      expect(findForbidden(value, DENY_LIST), `${path_}: ${value}`).toEqual([]);
    },
  );

  it.each(strings.map((entry) => [entry.path, entry.value]))(
    "%s uses the RC-12 lexicon",
    (path_, value) => {
      expect(findForbidden(value, LEXICON_PHRASES), `${path_}: ${value}`).toEqual([]);
    },
  );
});

// ---------------------------------------------------------------------------
// Criterion 3 — the inline thread-not-found sentence, and the API fact.
// ---------------------------------------------------------------------------

describe("criterion 3 — a 404 means missing OR another principal's", () => {
  const routes = readFileSync(path.join(REPO_ROOT, "src", "api", "routes.py"), "utf8");
  const ownership = routes.slice(
    routes.indexOf("def _check_ownership("),
    routes.indexOf("def _principal_key_id("),
  );

  it("reads the real _check_ownership, not a transcription of it", () => {
    expect(ownership).not.toBe("");
    expect(ownership).toContain("resource_principal_key_id");
    expect(ownership).toContain("caller");
  });

  it("the backend really does answer 404 for an ownership mismatch", () => {
    // A 403 here would mean the client CAN tell the two cases apart, and
    // the copy below would then be under-informative rather than honest.
    //
    // ADR 0064 moved the status off the raise site and onto the error
    // class, and made the rule a type: `_check_ownership` accepts a
    // `type[NotFoundError]`, so passing a 403 is now a type error rather
    // than a review miss. Both halves are checked — the signature here,
    // and the family's status in `src/errors.py` — because either alone
    // could drift into meaning nothing.
    expect(ownership).toContain("error: type[NotFoundError]");
    expect(ownership).not.toMatch(/Forbidden|HTTP_403/);

    const errors = readFileSync(
      path.join(REPO_ROOT, "src", "errors.py"),
      "utf8",
    );
    const family = errors.slice(
      errors.indexOf("class NotFoundError(AppError):"),
      errors.indexOf("class UnauthorizedError(AppError):"),
    );
    expect(family).toContain("http_status = 404");
  });

  it("and does it deliberately, to avoid disclosing existence", () => {
    expect(ownership).toMatch(/info-disclosure|don't exist|doesn't exist/i);
  });

  it("names both causes", () => {
    expect(THREAD.notFoundBody).toMatch(/never have existed/i);
    expect(THREAD.notFoundBody).toMatch(/another principal/i);
  });

  it("claims neither: never 'deleted', never 'no permission' (H8)", () => {
    for (const sentence of [
      THREAD.notFoundHeading,
      THREAD.notFoundBody,
      THREAD.notFoundBackToStart,
      THREAD.notFoundBackToList,
      ROUTE_ERROR.notFoundHeading,
      ROUTE_ERROR.notFoundBody,
      ROUTE_ERROR.notFoundAction,
    ]) {
      expect(sentence, sentence).not.toMatch(/\bdeleted\b/i);
      expect(sentence, sentence).not.toMatch(/\bremoved\b/i);
      expect(sentence, sentence).not.toMatch(/no permission|not allowed|forbidden|access denied/i);
      // And it does not quietly become a login prompt either: there is no
      // user identity to sign in as (03 §6, D-009).
      expect(sentence, sentence).not.toMatch(/sign in|log in|log ?out/i);
    }
  });

  it("says the page cannot tell which, rather than guessing", () => {
    expect(THREAD.notFoundBody).toMatch(/cannot tell which|same way for both/i);
  });
});

// ---------------------------------------------------------------------------
// The surfaces' own sentences.
// ---------------------------------------------------------------------------

describe("the recovery surfaces say what they can actually promise", () => {
  it("the thread boundary promises no retry of anything (H6, R-01)", () => {
    expect(RECOVERY.threadErrorBody).toMatch(/sends nothing again/i);
    expect(RECOVERY.threadErrorBody).not.toMatch(/retry|retried|resend|re-?submit/i);
  });

  it("the global boundary names a reload, not a reset that would fail again", () => {
    expect(GLOBAL_ERROR.action).toMatch(/reload/i);
    expect(GLOBAL_ERROR.body).toMatch(/reload/i);
  });

  it("the loading heading titles a surface that has no title yet", () => {
    // Not the thread's name, which is exactly what has not arrived. A
    // placeholder title would be a claim about the thread.
    expect(RECOVERY.loadingHeading).toMatch(/^Loading/);
  });

  it("nothing in the dictionary's recovery half mentions an account", () => {
    // Seam S6, restated positively: this is the half of D-009 that copy can
    // break without rendering a control.
    for (const entry of strings) {
      expect(entry.value, entry.path).not.toMatch(/\baccount\b/i);
      expect(entry.value, entry.path).not.toMatch(/\bsign in\b/i);
    }
  });
});

// ---------------------------------------------------------------------------
// The modules that render them.
// ---------------------------------------------------------------------------

describe("WO-09's surfaces write no user-facing sentence of their own", () => {
  const sources = [
    "components/patterns/NotFound.tsx",
    "components/patterns/RouteError.tsx",
    "components/patterns/ThreadSkeleton.tsx",
    "components/patterns/GlobalErrorSurface.tsx",
    "app/not-found.tsx",
    "app/global-error.tsx",
    "app/(workspace)/error.tsx",
    "app/(workspace)/c/[id]/error.tsx",
    "app/(workspace)/c/[id]/loading.tsx",
  ];

  /**
   * `app/(workspace)/c/[id]/loading.tsx` is absent on purpose: it renders
   * `<ThreadSkeleton />` and nothing else, so it has no words to import and
   * no props to take them through. Everything that renders a sentence is
   * here.
   */
  const wordedSources = sources.filter(
    (file) => file !== "app/(workspace)/c/[id]/loading.tsx",
  );

  it.each(wordedSources)("%s imports its words rather than typing them", (file) => {
    const source = readFileSync(path.join(WEB_ROOT, file), "utf8");
    // `NotFound` takes every string as a prop. The Next error entries defer
    // to RouteError's error-only module so the dictionary does not enter
    // first-load JS; that delegation is the stronger form of the same rule.
    const importsCopy = /from "@\/lib\/copy\//.test(source);
    const takesCopyAsProps = /heading:\s*string/.test(source);
    const delegatesCopy = /components\/patterns\/RouteError/.test(source);
    expect(importsCopy || takesCopyAsProps || delegatesCopy, file).toBe(true);
  });

  it.each(sources)("%s contains no ownership phrasing anywhere, comments included", (file) => {
    const source = readFileSync(path.join(WEB_ROOT, file), "utf8");
    // Deliberately over-broad: the whole file, not only its rendered
    // strings. A comment that says "your threads" is a sentence somebody
    // will eventually paste into the UI.
    expect(
      findForbidden(
        source,
        DENY_LIST.filter(
          (entry) => entry.id.startsWith("your") || entry.id.startsWith("my"),
        ),
      ),
      file,
    ).toEqual([]);
  });
});
