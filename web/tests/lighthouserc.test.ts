/**
 * WO-29 — the §8.2 budgets, asserted against `web/lighthouserc.json` and
 * `.github/workflows/nightly.yml` themselves.
 *
 * WHY THIS FILE EXISTS. `lighthouserc.json` is only ever executed by a nightly
 * workflow against a full Compose stack, so a typo in it — a `minScore` of
 * 0.9 where §8.2 says 1, a `bf-cache` line deleted from one of the ten cells,
 * a form factor that stopped being desktop — is invisible for up to a day and
 * then surfaces as a *green* run that asserted less than it claims to. That is
 * the failure mode a budget file has, and it is the one a per-PR test can
 * close. Same arrangement, and the same reason, as `tests/budgets.test.ts` for
 * `budgets.json` and `tests/ci.test.ts` for `ci.yml`.
 *
 * The numbers below are re-stated from
 * `docs/revamp/04-ARCHITECTURE.md` §8.2 by hand, on purpose. A test that read
 * its expectations out of the file under test would assert that JSON parses.
 *
 * 04 §8.4's ratchet rule is what makes this a gate rather than a nuisance: a
 * ceiling may only move in a PR that edits `lighthouserc.json` and says why in
 * the PR body. Moving one without touching this file fails here; moving both
 * is a two-file diff a reviewer cannot miss.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const WEB_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const RC_PATH = path.join(WEB_ROOT, "lighthouserc.json");
const WORKFLOW_PATH = path.join(REPO_ROOT, ".github", "workflows", "nightly.yml");
const LHCI_README_PATH = path.join(
  REPO_ROOT,
  "docs",
  "revamp",
  "evidence",
  "gate-4",
  "lhci",
  "README.md",
);

type Assertion = [level: string, options: Record<string, number | string>];
type MatrixEntry = { matchingUrlPattern: string; assertions: Record<string, Assertion> };
type CiConfig = {
  collect: { numberOfRuns: number; url: string[]; settings: Record<string, unknown> };
  assert: { assertMatrix: MatrixEntry[]; includePassedAssertions?: boolean };
  upload: { target: string; outputDir: string };
};
type Rc = {
  ci: CiConfig;
  states: { id: string; path: string }[];
  profiles: { id: string; label: string; ci: CiConfig }[];
};

const rcText = readFileSync(RC_PATH, "utf8");
const rc = JSON.parse(rcText) as Rc;
const workflow = readFileSync(WORKFLOW_PATH, "utf8");
const lhciReadme = readFileSync(LHCI_README_PATH, "utf8");

/** The three form-factor profiles, with `ci` named as the mobile-412 one. */
const PROFILES: { id: string; ci: CiConfig }[] = [
  { id: "mobile-412", ci: rc.ci },
  ...rc.profiles.map((profile) => ({ id: profile.id, ci: profile.ci })),
];

/**
 * 04-ARCHITECTURE.md §8.2, transcribed. Mobile and desktop columns.
 *
 * `total-blocking-time` is absent from this table on purpose — it is the one
 * audit whose `error` level is NOT the ratified number, and it has its own
 * describe block below. Every other row here is gated at §8.2's figure exactly.
 */
const BUDGETS = {
  mobile: {
    "categories:performance": { minScore: 0.95 },
    "categories:accessibility": { minScore: 1 },
    "categories:best-practices": { minScore: 1 },
    "largest-contentful-paint": { maxNumericValue: 2500 },
    "cumulative-layout-shift": { maxNumericValue: 0.02 },
  },
  desktop: {
    "categories:performance": { minScore: 0.98 },
    "categories:accessibility": { minScore: 1 },
    "categories:best-practices": { minScore: 1 },
    "largest-contentful-paint": { maxNumericValue: 1200 },
    "cumulative-layout-shift": { maxNumericValue: 0.02 },
  },
} as const;

/**
 * §8.2's ratified TBT ceiling, and the runner ceiling the nightly is gated on.
 *
 * The ruling (WO-29 follow-up, to be recorded in DECISIONS.md at Gate 4 close):
 * TBT is the only metric in the table that is real main-thread time rather than
 * a Lantern simulation, so it is the only one that scales with the runner's
 * actual CPU. The ratified ceiling stays, as a `warn`; the `error` sits at
 * **twice** it — per form factor, so desktop is 100 and not a flat 300, because
 * a flat 300 would be 6× a ceiling whose measured value on the runner is zero.
 */
const TBT = {
  mobile: { ratified: 150, runner: 300 },
  desktop: { ratified: 50, runner: 100 },
} as const;

/** Which §8.2 column each profile is gated by, and how many states it audits. */
const PROFILE_SHAPE: Record<string, { column: "mobile" | "desktop"; states: number }> = {
  // 320 px is 04 §8.3's narrow strip. §8.2 has one mobile column, not one per
  // width, so the 320 profile carries the same ceilings as the 412 one.
  "mobile-412": { column: "mobile", states: 4 },
  "desktop-1350": { column: "desktop", states: 4 },
  "mobile-320": { column: "mobile", states: 2 },
};

/** The seven assertions §8.2 (six rows) plus RC-18 (bf-cache) require. */
const REQUIRED_ASSERTIONS = [
  "categories:performance",
  "categories:accessibility",
  "categories:best-practices",
  "largest-contentful-paint",
  "total-blocking-time",
  "cumulative-layout-shift",
  "bf-cache",
];

/**
 * A profile's `assertMatrix` holds two kinds of entry, and telling them apart
 * by shape rather than by array position keeps these tests from depending on
 * the order somebody happened to write them in.
 *
 *   * a **state** entry — one per audited URL, carrying all seven audits;
 *   * the **runner-ceiling** entry — one per profile, a catch-all pattern
 *     carrying only the `warn`-level `total-blocking-time` row.
 */
const stateEntries = (entries: MatrixEntry[]): MatrixEntry[] =>
  entries.filter((entry) => "categories:performance" in entry.assertions);

const runnerEntries = (entries: MatrixEntry[]): MatrixEntry[] =>
  entries.filter((entry) => !("categories:performance" in entry.assertions));

describe("every §8.2 assertion is encoded, per state and per form factor", () => {
  it("carries exactly the three form-factor profiles", () => {
    expect(PROFILES.map((profile) => profile.id)).toEqual([
      "mobile-412",
      "desktop-1350",
      "mobile-320",
    ]);
  });

  it.each(PROFILES)("$id audits the expected number of states, once each", ({ id, ci }) => {
    const shape = PROFILE_SHAPE[id];
    expect(shape, `${id} has no expected shape in this test`).toBeDefined();
    expect(ci.collect.url).toHaveLength(shape!.states);
    // One entry per state, plus the single catch-all TBT runner-ceiling entry.
    expect(ci.assert.assertMatrix).toHaveLength(shape!.states + 1);
    // Every URL must match exactly one state entry and exactly one runner-ceiling
    // entry — no URL left ungated, and no state gated twice. LHCI silently
    // asserts nothing about a URL that matches no pattern, which is the one way
    // this file could go green while measuring nothing.
    for (const url of ci.collect.url) {
      const matching = ci.assert.assertMatrix.filter((entry) =>
        new RegExp(entry.matchingUrlPattern).test(url),
      );
      expect(stateEntries(matching), `state entries matching ${url} in ${id}`).toHaveLength(1);
      expect(runnerEntries(matching), `runner entries matching ${url} in ${id}`).toHaveLength(1);
      expect(matching, `unexpected extra entry matching ${url} in ${id}`).toHaveLength(2);
    }
  });

  it.each(PROFILES)("$id gates all seven audits on every state", ({ id, ci }) => {
    for (const entry of stateEntries(ci.assert.assertMatrix)) {
      expect(
        Object.keys(entry.assertions).sort(),
        `${id} / ${entry.matchingUrlPattern}`,
      ).toEqual([...REQUIRED_ASSERTIONS].sort());
    }
  });

  it.each(PROFILES)("$id's runner-ceiling entry carries TBT and nothing else", ({ id, ci }) => {
    // If this entry ever grew a second audit it would silently downgrade that
    // audit's gate across every state in the profile, which is precisely the
    // failure a catch-all pattern makes easy.
    const runner = runnerEntries(ci.assert.assertMatrix);
    expect(runner, id).toHaveLength(1);
    expect(Object.keys(runner[0]!.assertions), id).toEqual(["total-blocking-time"]);
  });

  it.each(PROFILES)("$id records the assertions that passed, not only the ones that failed", ({ ci }) => {
    // Without this, a green run's assertion-results.json is `[]` — which reads
    // identically to a run that matched no URL and asserted nothing. The
    // evidence pack's whole claim is "80 assertions were evaluated"; this flag
    // is what makes the artifact able to show it.
    expect(ci.assert.includePassedAssertions).toBe(true);
  });

  it("evaluates 80 assertions in total — 32 + 32 + 16", () => {
    // Stated as a number so that deleting a state, or a form factor, is a
    // deliberate edit to this line rather than a quieter run. Eight per cell,
    // not seven: TBT is asserted twice (see the TBT describe block below), and
    // LHCI evaluates every matching matrix entry rather than picking one — so
    // the count must be summed across matching entries and never merged by
    // audit id, which would hide ten assertions.
    const total = PROFILES.reduce(
      (sum, { ci }) =>
        sum +
        ci.collect.url.reduce(
          (inner, url) =>
            inner +
            ci.assert.assertMatrix
              .filter((entry) => new RegExp(entry.matchingUrlPattern).test(url))
              .reduce((n, entry) => n + Object.keys(entry.assertions).length, 0),
          0,
        ),
      0,
    );
    expect(total).toBe(80);
  });

  it.each(PROFILES)("$id's ceilings are §8.2's, to the number", ({ id, ci }) => {
    const column = PROFILE_SHAPE[id]!.column;
    const expected = BUDGETS[column];
    for (const entry of stateEntries(ci.assert.assertMatrix)) {
      for (const [auditId, budget] of Object.entries(expected)) {
        const [level, options] = entry.assertions[auditId]!;
        expect(level, `${id} / ${entry.matchingUrlPattern} / ${auditId}`).toBe("error");
        for (const [key, value] of Object.entries(budget)) {
          expect(options[key], `${id} / ${entry.matchingUrlPattern} / ${auditId}.${key}`).toBe(
            value,
          );
        }
      }
    }
  });
});

describe("total-blocking-time carries a runner ceiling, and only TBT does", () => {
  // The WO-29 follow-up ruling. Nightly run 33262680039 measured 180 ms
  // (runs: 216, 159, 180) on `?job=baseline-plan-review` mobile against the
  // ratified 150 ms, on a commit that measures 52–63 ms locally; 69 of 70
  // assertions passed and that was the only failure.

  it.each(PROFILES)("$id gates the error level at exactly 2× the ratified ceiling", ({ id, ci }) => {
    const { ratified, runner } = TBT[PROFILE_SHAPE[id]!.column];
    // 2×, per form factor — the property that makes this a rule rather than a
    // number somebody picked. Desktop is 100, not a flat 300.
    expect(runner).toBe(ratified * 2);
    for (const entry of stateEntries(ci.assert.assertMatrix)) {
      const [level, options] = entry.assertions["total-blocking-time"]!;
      expect(level, `${id} / ${entry.matchingUrlPattern}`).toBe("error");
      expect(options["maxNumericValue"], `${id} / ${entry.matchingUrlPattern}`).toBe(runner);
      expect(options["aggregationMethod"]).toBe("median");
    }
  });

  it.each(PROFILES)("$id keeps the ratified ceiling as a warn on every cell", ({ id, ci }) => {
    // The ratified number is not deleted, only demoted. If this row ever
    // disappeared, 04 §8.2's actual budget would stop appearing in the nightly
    // summary and the runner ceiling would silently become the only budget.
    const { ratified } = TBT[PROFILE_SHAPE[id]!.column];
    const runner = runnerEntries(ci.assert.assertMatrix);
    expect(runner, id).toHaveLength(1);
    const [level, options] = runner[0]!.assertions["total-blocking-time"]!;
    expect(level, id).toBe("warn");
    expect(options["maxNumericValue"], id).toBe(ratified);
    expect(options["aggregationMethod"]).toBe("median");
    // And it really does apply to every audited URL in the profile.
    for (const url of ci.collect.url) {
      expect(new RegExp(runner[0]!.matchingUrlPattern).test(url), `${id} / ${url}`).toBe(true);
    }
  });

  it("no other audit was granted a runner ceiling", () => {
    // LCP, CLS and the category scores are computed under simulated throttling
    // (`throttlingMethod: "simulate"`), so Lantern models the CPU from the
    // trace rather than measuring the host's — they all passed unchanged on the
    // runner. TBT is real main-thread time and is the sole exception. Every
    // other audit is still gated at §8.2's own figure, which the
    // "ceilings are §8.2's, to the number" test above asserts directly.
    for (const { id, ci } of PROFILES) {
      for (const entry of runnerEntries(ci.assert.assertMatrix)) {
        expect(Object.keys(entry.assertions), id).toEqual(["total-blocking-time"]);
      }
    }
  });

  it("the mechanics are documented in the config and in the evidence pack", () => {
    for (const text of [rcText, lhciReadme]) {
      expect(text).toMatch(/total.blocking.time/i);
      expect(text).toContain("33262680039");
    }
  });
});

describe("criterion 2 — Accessibility 100 and Best Practices 100, met and not approximated", () => {
  it.each(PROFILES)("$id asserts both at minScore 1 with pessimistic aggregation", ({ ci }) => {
    for (const entry of stateEntries(ci.assert.assertMatrix)) {
      for (const auditId of ["categories:accessibility", "categories:best-practices"]) {
        const [level, options] = entry.assertions[auditId]!;
        expect(level).toBe("error");
        // 1, not 0.99: a Lighthouse category score is capped at 1, so minScore 1
        // is the exact 100 §8.2 asks for rather than a rounding of it.
        expect(options["minScore"]).toBe(1);
        // And on the WORST of the three runs, not the friendliest. These two
        // audits carry no throttling term, so pessimistic costs nothing here
        // and is what "not approximated" means when a run is repeated.
        expect(options["aggregationMethod"]).toBe("pessimistic");
      }
    }
  });
});

describe("criterion 3 — CLS is gated at ≤ 0.02 everywhere (RC-06)", () => {
  it.each(PROFILES)("$id gates CLS at 0.02 on every state", ({ ci }) => {
    for (const entry of stateEntries(ci.assert.assertMatrix)) {
      const [level, options] = entry.assertions["cumulative-layout-shift"]!;
      expect(level).toBe("error");
      expect(options["maxNumericValue"]).toBe(0.02);
    }
  });

  it("RC-06's split between the 0.02 gate and the 0.000 intent is written down", () => {
    // RC-06 keeps both numbers and says they answer different questions. The
    // file has to carry that, or the next reader reconciles them by lowering
    // one of them.
    expect(rcText).toContain("RC-06");
    expect(rcText).toContain("0.000");
  });
});

describe("criterion 4 — the bf-cache audit (RC-18)", () => {
  it("is an error on every mobile cell, `/c/[id]` included", () => {
    // RC-18 requires the audit to PASS on `/c/[id]`. It does, on both mobile
    // profiles, so it is gated there rather than merely observed.
    for (const { id, ci } of PROFILES) {
      if (PROFILE_SHAPE[id]!.column !== "mobile") continue;
      for (const entry of stateEntries(ci.assert.assertMatrix)) {
        const [level, options] = entry.assertions["bf-cache"]!;
        expect(level, `${id} / ${entry.matchingUrlPattern}`).toBe("error");
        expect(options["minScore"]).toBe(1);
      }
    }
  });

  it("is a warning on every desktop cell, and the reason is documented", () => {
    // The documented deviation. Since WO-30 every document route is
    // dynamically rendered for the per-request CSP nonce and therefore served
    // `Cache-Control: no-store`, and Chrome refuses bfcache for a no-store
    // main resource under desktop emulation. Lighthouse itself classifies the
    // reason "Not actionable". `warn` keeps the audit running and printing;
    // `off` would delete the question.
    const desktop = PROFILES.find((profile) => profile.id === "desktop-1350")!;
    for (const entry of stateEntries(desktop.ci.assert.assertMatrix)) {
      const [level, options] = entry.assertions["bf-cache"]!;
      expect(level, entry.matchingUrlPattern).toBe("warn");
      expect(options["minScore"]).toBe(1);
    }
    expect(rcText).toContain("MainResourceHasCacheControlNoStore");
    expect(rcText).toContain("RC-18");
  });

  it("the deviation is restated in the evidence pack, not only in the config", () => {
    expect(lhciReadme).toContain("MainResourceHasCacheControlNoStore");
    expect(lhciReadme).toContain("bf-cache");
  });
});

describe("criterion 6 — the lab-versus-field caveat is restated", () => {
  it("the lhci README says there is no field data", () => {
    expect(lhciReadme).toMatch(/no field data/i);
    expect(lhciReadme).toMatch(/lab/i);
  });
});

describe("the collect settings are the ones the retained corpus was taken with", () => {
  it("mobile-412 is Lighthouse's default mobile emulation, written out", () => {
    const settings = rc.ci.collect.settings as Record<string, any>;
    expect(settings["formFactor"]).toBe("mobile");
    expect(settings["throttlingMethod"]).toBe("simulate");
    expect(settings["screenEmulation"]).toEqual({
      mobile: true,
      width: 412,
      height: 823,
      deviceScaleFactor: 1.75,
      disabled: false,
    });
    // Lighthouse's `mobileSlow4G`, which is what every retained baseline and
    // every Gate 3 rerun was measured under
    // (docs/revamp/evidence/gate-3/lighthouse-diff.md §1).
    expect(settings["throttling"]).toEqual({
      rttMs: 150,
      throughputKbps: 1638.4,
      requestLatencyMs: 562.5,
      downloadThroughputKbps: 1474.5600000000002,
      uploadThroughputKbps: 675,
      cpuSlowdownMultiplier: 4,
    });
  });

  it("desktop-1350 is Lighthouse's `--preset=desktop`, written out", () => {
    // @lhci/cli has no `preset` option, so the preset's four settings are
    // transcribed into the config. These are core/config/desktop-config.js +
    // core/config/constants.js (`desktopDense4G`,
    // `screenEmulationMetrics.desktop`, `userAgents.desktop`). Pinning them
    // here means a Lighthouse bump that changes the preset shows up as a
    // failing test rather than as a shifted measurement.
    const settings = rc.profiles.find((p) => p.id === "desktop-1350")!.ci.collect.settings as Record<
      string,
      any
    >;
    expect(settings["formFactor"]).toBe("desktop");
    expect(settings["screenEmulation"]).toEqual({
      mobile: false,
      width: 1350,
      height: 940,
      deviceScaleFactor: 1,
      disabled: false,
    });
    expect(settings["throttling"]).toEqual({
      rttMs: 40,
      throughputKbps: 10240,
      requestLatencyMs: 0,
      downloadThroughputKbps: 0,
      uploadThroughputKbps: 0,
      cpuSlowdownMultiplier: 1,
    });
    expect(settings["emulatedUserAgent"]).toContain("Macintosh");
  });

  it("mobile-320 differs from mobile-412 in the viewport and nothing else", () => {
    // 04 §8.3's narrow strip is a width, not a different device profile. If
    // the throttling ever diverged, the 320 row would stop being comparable to
    // the 412 row and to `conversation-populated-320.gate3.json`.
    const wide = rc.ci.collect.settings as Record<string, any>;
    const narrow = rc.profiles.find((p) => p.id === "mobile-320")!.ci.collect.settings as Record<
      string,
      any
    >;
    expect(narrow["formFactor"]).toBe(wide["formFactor"]);
    expect(narrow["throttling"]).toEqual(wide["throttling"]);
    expect(narrow["screenEmulation"]).toEqual({
      mobile: true,
      width: 320,
      height: 568,
      deviceScaleFactor: 2,
      disabled: false,
    });
  });

  it("every profile repeats each audit, so an aggregation method means something", () => {
    for (const { ci } of PROFILES) expect(ci.collect.numberOfRuns).toBe(3);
  });

  it("every matchingUrlPattern is host-agnostic", () => {
    // The stack's port is whatever was free. A pattern that pinned 127.0.0.1
    // would detach every assertion from its state the first time the port
    // moved — silently, because LHCI asserts nothing about an unmatched URL.
    for (const { id, ci } of PROFILES) {
      for (const entry of ci.assert.assertMatrix) {
        expect(entry.matchingUrlPattern, `${id}`).toContain("[^/]+");
        expect(entry.matchingUrlPattern, `${id}`).not.toContain("127.0.0.1");
      }
    }
  });

  it("audits the four states the retained corpus covers", () => {
    expect(rc.states.map((state) => state.path)).toEqual([
      "/",
      "/c/baseline-empty",
      "/c/baseline-populated",
      "/c/baseline-populated?job=baseline-plan-review",
    ]);
    for (const state of rc.states) {
      const url = new URL(state.path, "http://127.0.0.1:13210");
      expect(rc.ci.collect.url, `${state.path} is declared but not collected`).toContain(
        url.toString(),
      );
    }
  });
});

describe("criterion 5 and the cost boundary — nightly.yml", () => {
  it("hands the stack the disabled sentinel, hard-coded", () => {
    expect(workflow).toContain("ANTHROPIC_API_KEY: local-preview-disabled");
  });

  it("never gives the job the repository's Anthropic secret", () => {
    // The secret exists — `eval-nightly.yml` is the only workflow allowed to
    // spend it. A `${{ secrets.ANTHROPIC_API_KEY }}` here would put a real key
    // in front of a tier whose whole design assumes it cannot have one.
    expect(workflow).not.toMatch(/secrets\.ANTHROPIC_API_KEY/);
  });

  it("says in its own text that a regression blocks the next evidence run", () => {
    // WO-29 criterion 5. Both as a comment at the top of the file and as the
    // annotation a red run prints, so it is legible from the Actions UI too.
    expect(workflow).toMatch(/BLOCKS THE NEXT\s+# GATE 3 \/ GATE 4 EVIDENCE RUN/);
    expect(workflow).toContain("BLOCKS the next Gate 3 / Gate 4 evidence run");
  });

  it("runs on a schedule and can be dispatched", () => {
    expect(workflow).toMatch(/^\s+- cron: /m);
    expect(workflow).toContain("workflow_dispatch:");
  });

  it("brings the seeded stack up and always tears it down through stack.sh", () => {
    expect(workflow).toContain("npm run e2e:stack:up");
    expect(workflow).toContain("npm run e2e:stack:seed");
    expect(workflow).toContain("npm run e2e:stack:down");
  });
});
