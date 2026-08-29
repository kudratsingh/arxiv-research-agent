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
 * `landmark-one-main` and `region` failed 12 of 12 baseline states and now
 * fail **none**: WO-08's shell fixed them outright. The other four rules still
 * fail on some states, and in every case the offending markup is a *legacy*
 * component that WO-20 has not yet replaced — `EventLog.tsx`,
 * `ConversationThread.tsx`, `PlanReview.tsx`. `PENDING_COMPOSITION` names
 * each one with its file, its line and the work order that removes it, and
 * two of the nine are marked 🔴 because the *baseline never had them*: one is
 * a legacy literal that only started failing when WO-08's shell moved it onto
 * `--canvas`, and one is a button the baseline's capture caught disabled. It
 * is deliberately
 * **not** an allowlist: an allowlist hides a finding, whereas each entry here
 * is a pinned expectation that goes red in both directions — when a new
 * gated violation appears anywhere, and equally when one of these is finally
 * fixed and the entry must be deleted. `axe-allowlist.json` stays empty, and
 * `parseAllowlist` refuses to let any of the six rules into it at all.
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

/** Does any axe target of this node contain `fragment`? */
function targetIncludes(node: AxeNode, fragment: string): boolean {
  return node.target.some((part) => String(part).includes(fragment));
}

/** The measured colour pair axe recorded on this node, if it recorded one. */
function measuredPair(node: AxeNode): { fg: string; bg: string } | null {
  for (const check of [...node.any, ...node.all, ...node.none]) {
    const data = check.data as { fgColor?: string; bgColor?: string } | undefined;
    if (data?.fgColor === undefined || data.bgColor === undefined) continue;
    return { fg: data.fgColor.toLowerCase(), bg: data.bgColor.toLowerCase() };
  }
  return null;
}

/**
 * Compare hex without caring about the `#` or the case.
 *
 * The three sources disagree on both: axe reports lower case with a sigil,
 * `tokens.json` reports upper case with a sigil, and the Tailwind values in
 * `LEGACY` carry no sigil at all so the literal-colour scan stays honest.
 */
function sameColour(a: string, b: string): boolean {
  return a.replace(/^#/, "").toLowerCase() === b.replace(/^#/, "").toLowerCase();
}

/** Recognise a `color-contrast` node by the colours axe actually measured. */
function pairIs(node: AxeNode, fg: string, bg: string): boolean {
  const pair = measuredPair(node);
  return pair !== null && sameColour(pair.fg, fg) && sameColour(pair.bg, bg);
}

/**
 * Every gated violation that survives on this commit, with its owner.
 *
 * WHAT THIS LIST IS. Nine findings in three legacy files — `EventLog.tsx`,
 * `ConversationThread.tsx` and `PlanReview.tsx` — none of which the redesign
 * has composed away yet. Three of them are the *same nodes the retained
 * baseline failed on*, selector for selector: `.ml-2`,
 * `.dark\:text-slate-500` and `.text-amber-600` appear in
 * `baseline/axe/plan-review.json` and `cancelled.json` with the same colours
 * and the same ratios. Those are exactly the three regressions `03 §3.1`
 * tabulates, and they are still live because the surfaces that replace them
 * are not on a route. Two more are NOT in the baseline and are flagged 🔴
 * below: one the shell's new canvas exposed, one the baseline's capture
 * missed.
 *
 * WHAT IT IS NOT. It is not an allowlist. An allowlist entry hides a finding
 * and keeps hiding it; each entry here is a two-way pin — the sweep goes red
 * if a gated rule fails on anything this list does not recognise, and the
 * register test below goes red when one of these stops being observable, at
 * which point the entry must be deleted rather than left to excuse a
 * regression later. `parseAllowlist` additionally refuses to put any of the
 * six gated rules into `axe-allowlist.json` at all.
 *
 * WHY NOTHING HERE IS FIXED IN THIS BRANCH. Every file named below is one
 * WO-20 replaces wholesale, and the replacements
 * (`components/patterns/Diagnostics.tsx`, `components/patterns/PlanEditor*`,
 * `components/app/*`) are already merged and already correct. Patching the
 * legacy copies would collide with that work and buy nothing that outlives it.
 *
 * HOW THE RECOGNISERS NAME COLOURS. Wherever a colour has a name somewhere
 * authoritative it is read from there, never typed here: the three baseline
 * pairs come out of `tokens.json`'s `regressionsFixed`, and `--canvas` and
 * `--surface` come out of its light palette. Only two values have no name
 * anywhere — Tailwind's `slate-500`, `emerald-600` and `slate-950`, hard-coded
 * inside the legacy components, which is the defect itself — and those are
 * written below without the leading sigil, because `web/tests/tokens.test.ts`
 * (rightly) treats a six-digit hex in any `.ts` file under `web/` as a token
 * leak, and there is no token here to leak.
 */

/** The three palette values the legacy components hard-code. Hex, no sigil. */
const LEGACY = {
  /** Tailwind `slate-500`: `ConversationThread.tsx:202`, `EventLog.tsx:42`. */
  slate500: "64748b",
  /** Tailwind `emerald-600`: `PlanReview.tsx:94`. */
  emerald600: "059669",
  /** Tailwind `slate-950`, the legacy dark event-log field. */
  slate950: "020617",
} as const;

/** The three pairs `03 §3.1` retired, by (fg, bg), read from tokens.json. */
const RETIRED = retiredPairs();

/** `RETIRED[index]`, with a message when tokens.json stops having three. */
function retired(index: number): { fg: string; bg: string } {
  const pair = RETIRED[index];
  if (pair === undefined) {
    throw new Error(
      `tokens.json regressionsFixed has ${RETIRED.length} entries; 03 §3.1 ` +
        "names three, and PENDING_COMPOSITION is written against them.",
    );
  }
  return pair;
}

const PENDING_COMPOSITION: readonly PendingDefect[] = [
  {
    rule: "color-contrast",
    source: "web/components/ConversationThread.tsx:224",
    removedBy: "WO-15 TraceSpine + WO-20 — `03 §3.1` row 1, `03 §7.1`",
    why:
      "The job-id label. This is regression row 1 of `03 §3.1` verbatim — " +
      "slate-400 on slate-50 at 10.4px, ratio 2.45 — and it is the same " +
      "`.ml-2` node `baseline/axe/running.json` failed on. The brief's " +
      "replacement is `ink-muted` on `sunken` at 12px (5.44), proven in a real " +
      "render by criterion 4 below and waiting for a surface to carry it.",
    recognises: (node) => pairIs(node, retired(0).fg, retired(0).bg),
  },
  {
    rule: "color-contrast",
    source: "web/components/EventLog.tsx:42 (light theme)",
    removedBy: "WO-16 Diagnostics + WO-20 — `03 §3.1` row 2, `03 §7.1`",
    why:
      "Event timestamps. Regression row 2 of `03 §3.1` verbatim — slate-400 " +
      "on white at 12px, ratio 2.56 — and the same `.dark\\:text-slate-500` " +
      "node `baseline/axe/plan-review.json` failed on. Replaced by `ink-muted` " +
      "on `surface` (6.39), which criterion 4 measures at 6.38 in the browser.",
    recognises: (node) => pairIs(node, retired(1).fg, retired(1).bg),
  },
  {
    rule: "color-contrast",
    source: "web/components/EventLog.tsx:42 (dark theme)",
    removedBy: "WO-16 Diagnostics + WO-20",
    why:
      "The dark twin of the row above: slate-500 on slate-950 measures 4.23. " +
      "The retained baseline never caught it — its only dark report is " +
      "`conversation-populated-dark`, a thread with no run panel and therefore " +
      "no event list. Sweeping both themes over all twenty states is what " +
      "surfaces it.",
    recognises: (node) => pairIs(node, LEGACY.slate500, LEGACY.slate950),
  },
  {
    rule: "color-contrast",
    source: "web/components/EventLog.tsx:13, :16, :17",
    removedBy: "WO-16 Diagnostics + WO-17 PlanEditor + WO-20 — `03 §3.1` row 3",
    why:
      "The review/plan-ready event label. Regression row 3 of `03 §3.1` " +
      "verbatim — amber-600 on white at 12px, ratio 3.18 — and the same " +
      "`.text-amber-600` node the baseline failed on. Replaced by " +
      "`review-text` on `surface` (6.08); criterion 4 measures it.",
    recognises: (node) => pairIs(node, retired(2).fg, retired(2).bg),
  },
  {
    rule: "color-contrast",
    source: "web/components/ConversationThread.tsx:202, :221, :297",
    removedBy: "WO-18/WO-19 surfaces + WO-20",
    why:
      "🔴 NOT IN THE BASELINE — a contrast pair that PASSED on `1f3f45a` and " +
      "fails now. The legacy thread header paints its captions with Tailwind's " +
      "`text-slate-500`, which measured 4.83 against the old white page and " +
      "measures 4.41 against WO-08's `--canvas`. The regression is the " +
      "un-migrated literal rather than the canvas — every token-driven caption " +
      "on the same page measures 6.38 — but it is live on eight states today " +
      "and the coordinator should route it rather than wait for WO-20.",
    recognises: (node) => pairIs(node, LEGACY.slate500, lightToken("canvas")),
  },
  {
    rule: "color-contrast",
    source: "web/components/PlanReview.tsx:94",
    removedBy: "WO-17 PlanEditor + WO-20",
    why:
      "🔴 NOT IN THE BASELINE. The legacy Approve button is white on " +
      "emerald-600, which measures 3.76 at 14px against a 4.5 requirement. " +
      "The baseline missed it because its plan-review capture caught the " +
      "button in its disabled state, which 1.4.3 exempts and axe skips.",
    recognises: (node) => pairIs(node, lightToken("surface"), LEGACY.emerald600),
  },
  {
    rule: "aria-allowed-role",
    source: "web/components/EventLog.tsx:33-35",
    removedBy: "WO-16 Diagnostics + WO-20 — `03 §4.5`, `03 §7.1`",
    why:
      "`role=\"log\"` is written onto the `<ul>` itself, which strips the list " +
      "semantics its `<li>` children need. The brief's fix — move the role to " +
      "a wrapper `<div>` — is already implemented in " +
      "`components/patterns/Diagnostics.tsx`; it is not on a route yet.",
    recognises: (node) => targetIncludes(node, "max-h-80"),
  },
  {
    rule: "listitem",
    source: "web/components/EventLog.tsx:38",
    removedBy: "WO-16 Diagnostics + WO-20 — same defect as the row above",
    why:
      "The second half of the `role=\"log\"` defect: with the parent's list " +
      "role overwritten, every `<li>` is orphaned.",
    recognises: (node) => targetIncludes(node, "grid-cols-"),
  },
  {
    rule: "page-has-heading-one",
    source: "web/components/ConversationThread.tsx:55, :84",
    removedBy: "WO-09 NotFoundInline + WO-20 — `03 §7.1`",
    why:
      "The inline not-found branch returns before the `<h1>` at :199, so the " +
      "page has no level-one heading. `03 §7.1` requires every state, " +
      "including inline not-found, to render one.",
    recognises: (node) => node.target.some((part) => String(part) === "html"),
  },
];

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

          // ---- criterion 2, minus the four defects PENDING_COMPOSITION pins.
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
      // `plan-review` in light carries five of the eight entries — both
      // `EventLog` role defects and three of the contrast pairs; the same
      // state in dark carries the sixth (`slate-500` on `slate-950`, which
      // only exists in the dark event log); the inline not-found carries the
      // missing `<h1>`. Three loads cover the register.
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
