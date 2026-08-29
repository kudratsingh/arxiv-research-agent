import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
  ALLOWLIST_PATH,
  AXE_TAGS,
  CONTRAST_PROBE_ROOT,
  GATED_RULES,
  THEMES,
  analyze,
  appendSummaryRow,
  axeArtifact,
  contrastSamples,
  describe as describeViolations,
  loadAllowlist,
  mountContrastProbe,
  parseAllowlist,
  partition,
  samplesFor,
  settleForAudit,
  tagsOf,
  writeReport,
} from "./support/axe";
import type {
  AxeNode,
  AxeViolation,
  ContrastProbe,
  ContrastSample,
  Theme,
} from "./support/axe";
import { STATES, readyLocator } from "./support/states";

/**
 * WO-22 — the axe gate.
 *
 * WHAT IS BEING CLAIMED. Four things, and each has its own test below so a
 * red run says which one broke:
 *
 *   1. The tag set and the engine are the baseline's, asserted against the
 *      twelve retained reports rather than against a constant in this repo, so
 *      "directly comparable" is a checked property and not a claim.
 *   2. Zero violations of `landmark-one-main`, `region`, `aria-allowed-role`,
 *      `listitem`, `color-contrast` and `page-has-heading-one` on every §4
 *      state, in both themes.
 *   3. `axe-allowlist.json` is empty, and the parser that reads it refuses an
 *      entry with no written justification — proven on a synthetic entry,
 *      because a validator exercised only by an empty file is a comment.
 *   4. The three replacement colour pairs in `03 §3.1` measure their
 *      documented ratio in a real browser render.
 *
 * WHAT IS NOT BEING CLAIMED. Keyboard order, focus restoration, announcement
 * quality and screen-reader comprehension. Automation cannot establish any of
 * them; they are WO-27's manual Gate 4 evidence and this file does not
 * pretend otherwise (04 §7.4, `baseline/README.md`).
 *
 * WHERE CRITERION 2 STANDS TODAY — READ THIS BEFORE THE FIRST FAILURE.
 * `landmark-one-main` and `region` failed 12 of 12 baseline states and fail
 * **none** now: WO-08's shell fixed them outright. WO-22 opened this file with
 * nine further findings still live, every one of them in a *legacy* component
 * WO-20 had not yet replaced — `EventLog.tsx`, `ConversationThread.tsx`,
 * `PlanReview.tsx` — pinned in `PENDING_COMPOSITION` with a file, a line and
 * the work order that removed it. **WO-20 removed all nine**, the register
 * test went red on every entry at once, and the entries were deleted. So
 * criterion 2 is now an unqualified zero: no gated rule fails on any §4 state,
 * in either theme, with nothing pinned and nothing excused.
 *
 * The register is deliberately **not** an allowlist: an allowlist hides a
 * finding, whereas each entry is a pinned expectation that goes red in both
 * directions — when a new gated violation appears anywhere, and equally when
 * one of the pinned defects is finally fixed and the entry must be deleted.
 * That second direction is what happened here. `axe-allowlist.json` stays
 * empty, and `parseAllowlist` refuses to let any of the six rules into it at
 * all.
 */

const REPO_ROOT = join(__dirname, "..", "..");
const BASELINE_AXE = join(REPO_ROOT, "docs", "revamp", "baseline", "axe");
const TOKENS_JSON = join(REPO_ROOT, "docs", "revamp", "design", "tokens.json");

/**
 * The baseline audit viewport (`baseline/fixtures/axe-baseline.spec.ts:47`).
 *
 * Comparability is not only about the tag set: `color-contrast` and
 * `landmark-one-main` both depend on what is on screen, and a report taken at
 * a different width can differ from the baseline for reasons that have
 * nothing to do with the redesign.
 */
const AUDIT_VIEWPORT = { width: 1440, height: 1200 } as const;

// -------------------------------------------------- the baseline correspondence

/**
 * Which live state each retained baseline report corresponds to.
 *
 * The map is what makes a diff possible at all — `home.json` and
 * `landing.light.json` are the same page under two names — and asserting that
 * every retained report has a counterpart is what stops the redesign from
 * quietly dropping a state the baseline audited. WO-26 diffs these pairs.
 */
const BASELINE_COUNTERPART: Readonly<Record<string, { state: string; theme: Theme }>> = {
  home: { state: "landing", theme: "light" },
  "conversation-empty": { state: "thread-empty", theme: "light" },
  "conversation-populated": { state: "thread-populated", theme: "light" },
  "conversation-populated-dark": { state: "thread-populated", theme: "dark" },
  "plan-review": { state: "plan-review", theme: "light" },
  running: { state: "running", theme: "light" },
  "failed-partial": { state: "failed-partial", theme: "light" },
  cancelled: { state: "cancelled", theme: "light" },
  "expired-job": { state: "expired", theme: "light" },
  "backend-offline": { state: "rail-error-upstream", theme: "light" },
  "conversation-not-found": { state: "thread-not-found-inline", theme: "light" },
  "framework-not-found": { state: "route-not-found", theme: "light" },
};

// ------------------------------------------------------------------ tokens

interface ContrastCheck {
  pair: string;
  fg: string;
  bg: string;
  ratio: number;
}

interface Regression {
  baseline: string;
  ratio: number;
  source: string;
  replacedBy: string;
}

interface TokensJson {
  color: Record<"light" | "dark", Record<string, string>>;
  contrastChecks: ContrastCheck[];
  regressionsFixed: Regression[];
}

function tokens(): TokensJson {
  return JSON.parse(readFileSync(TOKENS_JSON, "utf8")) as TokensJson;
}

/** A light-theme token value, read from the source of truth rather than typed. */
function lightToken(name: string): string {
  const value = tokens().color.light[name];
  if (value === undefined) throw new Error(`tokens.json has no light colour "${name}"`);
  return value.toLowerCase();
}

/**
 * `"light ink-muted / sunken"` → the two custom properties that carry it.
 *
 * Derived rather than written out, so this file contains no colour value at
 * all: `web/tests/tokens.test.ts` fails the build on any literal colour
 * outside `app/tokens.css`, and — more to the point — a hard-coded hex here
 * would let the gate keep passing after somebody changed the token.
 */
function propertiesFor(pair: string): { fgProperty: string; bgProperty: string } {
  const match = /^(?:light|dark)\s+(\S+)\s+\/\s+(\S+)$/.exec(pair);
  if (match?.[1] === undefined || match[2] === undefined) {
    throw new Error(`cannot derive custom properties from contrast pair "${pair}"`);
  }
  return { fgProperty: `--color-${match[1]}`, bgProperty: `--color-${match[2]}` };
}

/** The three pairs `03 §3.1` names as replacements, read from tokens.json. */
function replacementPairs(): (ContrastCheck & ContrastProbe)[] {
  const { contrastChecks, regressionsFixed } = tokens();
  const wanted = [
    "light ink-muted / sunken",
    "light ink-muted / surface",
    "light review-text / surface",
  ];

  return wanted.map((name) => {
    const check = contrastChecks.find((entry) => entry.pair === name);
    if (check === undefined) {
      throw new Error(`tokens.json has no contrastChecks entry for "${name}"`);
    }
    // Anchor to §3.1's regression table, not merely to "some passing pair":
    // criterion 4 is about the three colours that REPLACED a failure.
    const regression = regressionsFixed.find((entry) =>
      entry.replacedBy.includes(`= ${check.ratio}`),
    );
    if (regression === undefined) {
      throw new Error(
        `"${name}" (ratio ${check.ratio}) is not the replacement for any entry in ` +
          "tokens.json regressionsFixed — 03 §3.1 and the token file disagree.",
      );
    }
    return {
      ...check,
      ...propertiesFor(name),
      id: name.replace(/[^a-z-]+/g, "-").replace(/^-|-$/g, ""),
      sizeProperty: "--text-ui-xs-size",
    };
  });
}

/** The three pairs §3.1 says were REMOVED. They must appear nowhere. */
function retiredPairs(): { fg: string; bg: string; describe: string }[] {
  return tokens().regressionsFixed.map((entry) => {
    const match = /^(#[0-9a-fA-F]{6})\s+on\s+(#[0-9a-fA-F]{6})/.exec(entry.baseline);
    if (match?.[1] === undefined || match[2] === undefined) {
      throw new Error(`cannot parse a colour pair out of "${entry.baseline}"`);
    }
    return {
      fg: match[1].toLowerCase(),
      bg: match[2].toLowerCase(),
      describe: `${entry.baseline} (ratio ${entry.ratio}, ${entry.source})`,
    };
  });
}

// ------------------------------------------------- the pending-composition register

/**
 * A gated violation that exists on this commit, in a component the redesign
 * has already written a replacement for but not yet composed into a route.
 *
 * Every field is load-bearing. `recognises` is what distinguishes "the known
 * defect" from "a new defect that happens to trip the same rule" — without it
 * this would be a rule-level mute, which is the thing 04 §7.4 forbids.
 */
interface PendingDefect {
  rule: (typeof GATED_RULES)[number];
  /** Where the markup lives today. */
  source: string;
  /** The work order whose surface removes it. */
  removedBy: string;
  /** Why it is not fixed in this branch. */
  why: string;
  /** Recognise this exact defect — never the whole rule. */
  recognises: (node: AxeNode) => boolean;
}

/** The three pairs `03 §3.1` retired, by (fg, bg), read from tokens.json. */
const RETIRED = retiredPairs();

/**
 * THE REGISTER IS EMPTY, AND WO-20 IS WHY.
 *
 * WO-22 opened it with nine entries: six `color-contrast` findings, the
 * `aria-allowed-role` / `listitem` pair from `EventLog`'s `role="log"` on a
 * `<ul>`, and the missing `<h1>` on the inline not-found branch. Every one of
 * them lived in `EventLog.tsx`, `ConversationThread.tsx` or `PlanReview.tsx` —
 * modules whose replacements were already merged and already correct, and
 * which only a route composition could stop rendering. WO-22 said so in as
 * many words: "Every file named below is one WO-20 replaces wholesale."
 *
 * WO-20 replaced them. `app/(workspace)/c/[id]/page.tsx` renders
 * `ThreadTimeline` and `ActiveRunPanel` — `Diagnostics` instead of
 * `EventLog`, `PlanEditor` instead of `PlanReview`, `ReportReader` +
 * `MetricsStrip` + `ExportDisclosure` instead of `ReportView` + `JobSummary` +
 * `ExportDropdown`, and WO-09's `NotFound` for the 404 — and the register test
 * below went red on all nine at once, which is exactly the signal it was
 * built to give. They are deleted rather than kept, so criterion 2 is now an
 * unqualified zero on every §4 state in both themes.
 *
 * IT STAYS EMPTY UNLESS SOMETHING IS BOTH BROKEN AND SCHEDULED. An entry here
 * is not a suppression: it is a two-way pin that fails when the defect goes
 * away. Adding one without a named owner and a dated replacement would turn
 * it into the allowlist `parseAllowlist` refuses to be.
 */
const PENDING_COMPOSITION: readonly PendingDefect[] = [];

/** Split gated violations into "known and pinned" and "new". */
function splitPending(violations: readonly AxeViolation[]): {
  pinned: { defect: PendingDefect; node: AxeNode }[];
  unexpected: AxeViolation[];
} {
  const pinned: { defect: PendingDefect; node: AxeNode }[] = [];
  const unexpected: AxeViolation[] = [];

  for (const violation of violations) {
    const left: AxeNode[] = [];
    for (const node of violation.nodes) {
      const defect = PENDING_COMPOSITION.find(
        (entry) => entry.rule === violation.id && entry.recognises(node),
      );
      if (defect === undefined) left.push(node);
      else pinned.push({ defect, node });
    }
    if (left.length > 0) unexpected.push({ ...violation, nodes: left });
  }
  return { pinned, unexpected };
}

// ============================================================== criterion 1

test.describe("WO-22 criterion 1 — comparability with the retained baseline", () => {
  test(
    "every retained baseline report used this gate's tag set, engine and a live state",
    { tag: "@axe" },
    async () => {
      const missing: string[] = [];
      const rows: string[] = ["baseline report\tlive report\t§4 rows"];
      const known = new Map(STATES.map((state) => [state.id, state]));

      for (const [report, counterpart] of Object.entries(BASELINE_COUNTERPART)) {
        const file = join(BASELINE_AXE, `${report}.json`);
        const results = JSON.parse(readFileSync(file, "utf8")) as {
          testEngine: { name: string; version: string };
          toolOptions: { runOnly?: { type: string; values: string[] } };
        };

        expect(
          results.toolOptions.runOnly?.values,
          `baseline/axe/${report}.json was taken with a different tag set, so a ` +
            "diff against it would report tag differences as redesign " +
            "differences. Criterion 1 is exactly this equality.",
        ).toEqual([...AXE_TAGS]);
        expect(results.testEngine.name).toBe("axe-core");

        const state = known.get(counterpart.state);
        if (state === undefined) {
          missing.push(`${report} -> ${counterpart.state} (not in STATES)`);
          continue;
        }
        rows.push(
          `${report}\t${counterpart.state}.${counterpart.theme}\t${state.rows.join("+")}`,
        );
      }

      expect(
        missing,
        "a retained baseline report has no live counterpart. Either the state " +
          "was dropped from support/states.ts — in which case the redesign has " +
          "stopped auditing something the baseline audited — or the name in " +
          "BASELINE_COUNTERPART is stale.",
      ).toEqual([]);

      // The map itself, written where WO-26's axe-diff can read it.
      writeFileSync(
        axeArtifact(test.info().outputDir, "baseline-map.tsv"),
        `${rows.join("\n")}\n`,
        { encoding: "utf8" },
      );
      expect(Object.keys(BASELINE_COUNTERPART)).toHaveLength(12);
    },
  );
});

// ============================================================== criterion 3

test.describe("WO-22 criterion 3 — the allowlist", () => {
  test("is empty, and starts that way", { tag: "@axe" }, () => {
    expect(
      loadAllowlist(),
      `${ALLOWLIST_PATH} must be empty. Criterion 3 is not "the allowlist is ` +
        'small" — it is "the allowlist is empty", and a first entry is a ' +
        "decision that belongs in review with a written justification, not in " +
        "a passing test run.",
    ).toEqual([]);
  });

  test("refuses an entry with no written justification", { tag: "@axe" }, () => {
    const entry = {
      rule: "heading-order",
      state: "landing",
      selector: "h3",
      owner: "somebody",
    };
    expect(() => parseAllowlist([entry], "synthetic")).toThrow(/written justification/);
    expect(() => parseAllowlist([{ ...entry, justification: "later" }], "synthetic")).toThrow(
      /written justification/,
    );
    // …and accepts one that carries a real argument.
    expect(
      parseAllowlist(
        [
          {
            ...entry,
            justification:
              "Storybook's own docs chrome emits an h3 before the story root; " +
              "the product markup under test has correct heading order.",
          },
        ],
        "synthetic",
      ),
    ).toHaveLength(1);
  });

  test("refuses to suppress any of the six gated rules", { tag: "@axe" }, () => {
    for (const rule of GATED_RULES) {
      expect(
        () =>
          parseAllowlist(
            [
              {
                rule,
                state: "*",
                selector: "*",
                owner: "somebody",
                justification:
                  "a justification long enough to pass the length check but " +
                  "not long enough to be a good idea",
              },
            ],
            "synthetic",
          ),
        `allowlisting "${rule}" must be impossible: it is one of the six rules ` +
          "criterion 2 gates at zero.",
      ).toThrow(/gates at zero/);
    }
  });

  test("refuses a malformed document", { tag: "@axe" }, () => {
    expect(() => parseAllowlist({}, "synthetic")).toThrow(/JSON array/);
    expect(() => parseAllowlist([null], "synthetic")).toThrow(/must be an object/);
    expect(() => parseAllowlist([{ rule: "x" }], "synthetic")).toThrow(/non-empty "state"/);
  });
});

// ============================================================== criterion 2

test.describe("WO-22 criterion 2 — zero gated violations on every §4 state", () => {
  const allowlist = loadAllowlist();

  for (const theme of THEMES) {
    for (const state of STATES) {
      test(
        `${state.id} · ${theme} (§4 ${state.rows.join(", ")})`,
        { tag: "@axe" },
        async ({ page }, info) => {
          await page.setViewportSize(AUDIT_VIEWPORT);
          await page.emulateMedia({ colorScheme: theme });
          await state.arrange?.(page);
          await page.goto(state.path, { waitUntil: "domcontentloaded" });

          // Never audit a blank page — the same guard the reflow sweep uses,
          // for the same reason: axe finds nothing wrong with nothing.
          await expect(readyLocator(page, state.ready)).toBeVisible();
          // …and never audit the wrong theme. `color-contrast` is the whole
          // point of the dark half of this sweep, so a silent fall back to
          // light would turn twenty tests into duplicates of the other twenty.
          await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
          // …and never audit a half-arrived page. See `settleForAudit`.
          await settleForAudit(page);

          const results = await analyze(page);
          writeReport(info.outputDir, `${state.id}.${theme}`, results);

          // Comparability asserted on the run that just happened, not on a
          // constant this repo controls (criterion 1).
          expect(
            tagsOf(results),
            "this report was produced with a different tag set from the twelve " +
              "retained baseline reports, so it cannot be diffed against them.",
          ).toEqual([...AXE_TAGS]);
          expect(results.testEngine.version).toMatch(/^4\.13\./);

          const split = partition(results, state.id, allowlist);
          const pending = splitPending(split.gated);
          const samples = contrastSamples(results);

          appendSummaryRow(info.outputDir, {
            state: state.id,
            theme,
            rows: state.rows,
            violations: results.violations.length,
            gated: split.gated.length,
            unlisted: split.unlisted.length,
            incomplete: results.incomplete.length,
            contrastPasses: samples.filter((sample) => sample.outcome === "pass").length,
          });

          // ---- criterion 2. `PENDING_COMPOSITION` is empty since WO-20, so
          // `pending.unexpected` is every gated violation there is, and this
          // is the unqualified zero the criterion asks for.
          expect(
            pending.unexpected,
            "a gated rule failed on markup no PENDING_COMPOSITION entry " +
              "recognises. These six rules are the defects the redesign exists " +
              "to fix and none of them may be allowlisted:\n" +
              describeViolations(pending.unexpected),
          ).toEqual([]);

          // ---- anything outside the six: zero, because the allowlist is empty.
          expect(
            split.unlisted,
            "axe found a violation of a rule the baseline never failed. It " +
              `cannot be ignored silently — fix it, or add an entry to ${ALLOWLIST_PATH} ` +
              "with a written justification and defend it in review:\n" +
              describeViolations(split.unlisted),
          ).toEqual([]);

          // ---- criterion 4, product-wide half: no NEW surface reintroduces a
          // pair 03 §3.1 retired. The legacy nodes that still carry them are
          // excluded here only because the two entries above already assert
          // them, node by node, with an owner — dropping them from this loop
          // would double-report the same finding, not hide it.
          const pinnedTargets = new Set(
            pending.pinned.map(({ node }) => node.target.map(String).join(" ")),
          );
          for (const pair of RETIRED) {
            const elsewhere = samplesFor(samples, pair).filter(
              (sample) => !pinnedTargets.has(sample.target),
            );
            expect(
              elsewhere,
              `${state.id} · ${theme} renders ${pair.describe} on a node ` +
                "PENDING_COMPOSITION does not account for. 03 §3.1 names this " +
                "pair as replaced; measuring it on a new surface means the " +
                "replacement did not reach that surface.",
            ).toEqual([]);
          }
        },
      );
    }
  }
});

/**
 * The register cannot rot.
 *
 * Without this, a `PENDING_COMPOSITION` entry would survive the fix it is
 * waiting for: WO-20 lands, the defect disappears, and the entry sits here
 * forever quietly excusing a violation that no longer exists — and would
 * excuse it again if it came back. So every entry is asserted to be **still
 * observable**. When WO-20 composes the new surfaces this test goes red, and
 * the correct response is to delete the entries it names.
 */
test.describe("WO-22 — the pending-composition register is still true", () => {
  test(
    "every pinned legacy defect is still observable, or the entry must be deleted",
    { tag: "@axe" },
    async ({ page }) => {
      const seen = new Set<string>();
      // The three loads that covered WO-22's nine entries: `plan-review` in
      // light carried five of them, the same state in dark carried the sixth
      // (`slate-500` on `slate-950`, which only existed in the dark event
      // log), and the inline not-found carried the missing `<h1>`. The
      // register is empty now, so these three loads observe nothing and the
      // assertion below is trivially true — which is the correct shape for a
      // ratchet with nothing left to hold. They are kept rather than deleted
      // so the next entry anyone adds is checked the moment it is written.
      for (const [stateId, theme] of [
        ["plan-review", "light"],
        ["plan-review", "dark"],
        ["thread-not-found-inline", "light"],
      ] as const) {
        const state = STATES.find((entry) => entry.id === stateId);
        expect(state, `states.ts no longer has "${stateId}"`).toBeDefined();
        if (state === undefined) continue;

        await page.setViewportSize(AUDIT_VIEWPORT);
        await page.emulateMedia({ colorScheme: theme });
        await state.arrange?.(page);
        await page.goto(state.path, { waitUntil: "domcontentloaded" });
        await expect(readyLocator(page, state.ready)).toBeVisible();
        await settleForAudit(page);

        const results = await analyze(page);
        for (const { defect } of splitPending(results.violations).pinned) {
          seen.add(defect.source);
        }
      }

      const stale = PENDING_COMPOSITION.filter((defect) => !seen.has(defect.source));
      expect(
        stale.map((defect) => `${defect.rule} @ ${defect.source} (${defect.removedBy})`),
        "these PENDING_COMPOSITION entries no longer match anything on the " +
          "page. That is good news — the surface was composed or the defect " +
          "was fixed — and it means the entries must be DELETED from " +
          "axe.spec.ts so criterion 2 becomes an unqualified zero for them.",
      ).toEqual([]);
    },
  );
});

// ============================================================== criterion 4

test.describe("WO-22 criterion 4 — the replacement colours, measured in a browser", () => {
  test(
    "the three §3.1 replacement pairs measure their documented ratio in a real render",
    { tag: "@axe" },
    async ({ page }, info) => {
      const pairs = replacementPairs();
      expect(pairs).toHaveLength(3);

      await page.setViewportSize(AUDIT_VIEWPORT);
      await page.emulateMedia({ colorScheme: "light" });
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
      await settleForAudit(page);

      // Half one: whatever the shipped surfaces already paint, unmodified.
      const surface = contrastSamples(await analyze(page));

      // Half two: the pairs the product has no surface for yet, rendered
      // through the shipped custom properties. See `mountContrastProbe`.
      await mountContrastProbe(page, pairs);
      const probed = contrastSamples(
        await analyze(page, { include: CONTRAST_PROBE_ROOT }),
      );

      const evidence: string[] = [
        "pair\tfg\tbg\tdocumented\tmeasured\tfont-size\tsource",
      ];

      for (const pair of pairs) {
        const onProbe = samplesFor(probed, pair);
        expect(
          onProbe.length,
          `the probe rendered no measurable text for ${pair.pair}. Expected ` +
            `${pair.fgProperty} on ${pair.bgProperty}; axe measured ` +
            `${probed.map((s) => `${s.fg} on ${s.bg}`).join(", ") || "nothing"}. ` +
            "Either the custom property was renamed or tokens.json and " +
            "app/tokens.css have drifted apart.",
        ).toBeGreaterThan(0);

        const sample = onProbe[0] as ContrastSample;
        // axe truncates its ratio to two decimals, so the documented value
        // and the measured one agree to within one ulp of that.
        expect(
          sample.ratio,
          `${pair.pair}: 03 §3.1 computes ${pair.ratio} arithmetically; the ` +
            `browser measured ${sample.ratio}. A gap larger than rounding means ` +
            "the token table describes colours the cascade does not produce.",
        ).toBeGreaterThanOrEqual(pair.ratio - 0.02);
        expect(sample.ratio).toBeLessThanOrEqual(pair.ratio + 0.02);
        // And the thing the ratio is for.
        expect(
          sample.ratio,
          `${pair.pair} does not clear WCAG 1.4.3 AA for normal text.`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          sample.fontSizePx,
          `${pair.pair} must be measured at the 12px type step the brief names ` +
            "— the baseline failure it replaces was partly a 10.4px caption.",
        ).toBe(12);

        const onSurface = samplesFor(surface, pair);
        evidence.push(
          [
            pair.pair,
            sample.fg,
            sample.bg,
            pair.ratio,
            sample.ratio,
            `${sample.fontSizePx}px`,
            onSurface.length > 0
              ? `product surface (${onSurface.length} node(s), e.g. ${onSurface[0]?.target})`
              : "token probe only — no composed surface uses it yet",
          ].join("\t"),
        );
      }

      // The one pair a shipped surface already paints. Asserted, so the claim
      // "confirmed in a real render" is not carried entirely by the probe.
      const inkOnSurface = pairs.find((pair) => pair.pair === "light ink-muted / surface");
      if (inkOnSurface === undefined) throw new Error("tokens.json lost ink-muted / surface");
      expect(
        samplesFor(surface, inkOnSurface),
        "`ink-muted` on `surface` is painted by WO-08's shell today, so at " +
          "least one node of the landing page must measure it. If this is empty " +
          "the probe is measuring a pair nothing on screen uses.",
      ).not.toEqual([]);

      writeFileSync(
        axeArtifact(info.outputDir, "contrast-proof.tsv"),
        `${evidence.join("\n")}\n`,
        { encoding: "utf8" },
      );
    },
  );
});
