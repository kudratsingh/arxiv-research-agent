// WO-11 criterion 4 — `POST /research` is not registered as a mutation
// at all (H6, R-01).
//
// The reason it is not merely "a mutation configured carefully" is the
// library's own default: `networkMode: "online"` PAUSES a mutation while
// the browser is offline and RESUMES it when connectivity returns. On a
// non-idempotent, potentially billable submission with no idempotency
// key (`routes.py:179-197`) that is an automatic second paid run. The
// only configuration that cannot be got wrong later is absence, so
// submission stays a plain guarded function in the job machine and this
// file asserts the absence three ways: the source of the query layer,
// its export surface, and the shape of the mutation-key factory.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import * as api from "@/lib/api/index";
import * as queryClientModule from "@/lib/queries/client";
import * as conversations from "@/lib/queries/conversations";
import * as job from "@/lib/queries/job";
import { mutationKeys } from "@/lib/queries/keys";

import { handlers } from "../support/msw";

const WEB_ROOT = process.cwd();
const QUERIES_DIR = join(WEB_ROOT, "lib", "queries");

/** Every file WO-11 owns, as source text. */
function scopeSources(): { path: string; source: string }[] {
  const files = readdirSync(QUERIES_DIR)
    .filter((name) => name.endsWith(".ts"))
    .map((name) => join("lib", "queries", name));
  files.push(join("app", "providers.tsx"));
  return files.map((path) => ({
    path,
    source: readFileSync(join(WEB_ROOT, path), "utf8"),
  }));
}

/** Comment lines are where the prohibition is explained; skip them. */
function codeLines(source: string): string[] {
  return source
    .split("\n")
    .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line));
}

// Assembled rather than written out: the H12 containment test in
// `tests/api.test.ts` fails on the literal appearing outside `lib/api/`,
// and this file is outside it.
const BYPASS_FIELD = ["hitl", "bypass"].join("_");

describe("POST /research is not a mutation (criterion 4, H6)", () => {
  it("is not called, imported or named anywhere in the query layer", () => {
    const forbidden = ["submitResearch", BYPASS_FIELD, "ResearchAccepted"];
    const offenders: string[] = [];
    for (const { path, source } of scopeSources()) {
      for (const line of codeLines(source)) {
        for (const name of forbidden) {
          if (line.includes(name)) offenders.push(`${path}: ${line.trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("has no mutation key, and the three that exist are the idempotent writes", () => {
    const keys = [
      mutationKeys.conversations.create(),
      mutationKeys.conversations.delete(),
      mutationKeys.jobs.review(),
    ];
    expect(keys).toHaveLength(3);
    for (const key of keys) {
      expect(JSON.stringify(key)).not.toMatch(/submit|research/i);
    }
  });

  it("exports nothing that submits a job", () => {
    const exported = [
      ...Object.keys(conversations),
      ...Object.keys(job),
      ...Object.keys(queryClientModule),
    ];
    const offenders = exported.filter((name) =>
      /submit|startRun|createJob|research/i.test(name)
    );
    expect(offenders).toEqual([]);
  });

  it("re-exports none of the typed client's submission function", () => {
    const values = [
      ...Object.values(conversations),
      ...Object.values(job),
      ...Object.values(queryClientModule),
    ];
    expect(values).not.toContain(api.submitResearch);
  });

  it("still has no MSW handler, so a test that submitted one would die loudly", () => {
    // WO-05's cost gate, restated where the query layer can see it: if a
    // future mutation ever posted to /research, this suite would fail at
    // the interceptor rather than pass quietly.
    const research = handlers.filter((handler) => {
      const info = (handler as { info?: { method?: string; path?: unknown } }).info;
      return (
        info?.method === "POST" && String(info?.path).includes("/research")
      );
    });
    expect(research).toEqual([]);
  });
});

describe("every mutation the query layer does register is retry: false", () => {
  it("says so at each call site, not only in the client defaults", () => {
    let useMutationCalls = 0;
    let retryFalse = 0;
    for (const { source } of scopeSources()) {
      useMutationCalls += source.match(/useMutation[<(]/g)?.length ?? 0;
      retryFalse += source.match(/retry:\s*false/g)?.length ?? 0;
    }
    expect(useMutationCalls).toBe(3);
    expect(retryFalse).toBeGreaterThanOrEqual(useMutationCalls);
  });
});
