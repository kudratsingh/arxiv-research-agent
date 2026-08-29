import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import RAW_ALLOWLIST from "../axe-allowlist.json";

/**
 * WO-22 — the axe gate (04-ARCHITECTURE.md §7.4).
 *
 * This module is the *mechanism*; `axe.spec.ts` is the gate that uses it, and
 * WO-24 will use it again to run the same analysis over Storybook stories
 * (WO-22 criterion 5). Nothing here knows about the state table, about
 * Storybook, or about CI — it takes a `Page`, runs axe with the one sanctioned
 * tag set, and returns data. Everything policy-shaped is a named export so
 * both callers assert against the same constants rather than two copies that
 * can drift.
 *
 * WHY THE TAG SET IS A CONSTANT AND NOT AN ARGUMENT. Criterion 1 is
 * comparability: the twelve retained reports in `docs/revamp/baseline/axe/`
 * were taken with WCAG 2 A/AA + 2.1 A/AA + 2.2 AA + best-practice, and a
 * report taken with a different set is not a "better" report, it is an
 * incomparable one. `axe.spec.ts` proves the equality against the retained
 * JSON rather than trusting this list (`toolOptions.runOnly.values` is
 * recorded in every baseline file), so this constant cannot silently drift
 * away from the evidence it is supposed to be diffable against.
 */

/**
 * The baseline's tag set, verbatim.
 *
 * `docs/revamp/baseline/README.md`: "axe was injected by Playwright from local
 * `axe-core@4.13.0` and run with WCAG 2 A/AA, WCAG 2.1 A/AA, WCAG 2.2 AA, and
 * best-practice tags."
 */
export const AXE_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
  "best-practice",
] as const;

/**
 * The six rules criterion 2 gates at **zero**, and the reason each is here.
 *
 * These are exactly the rules the retained baseline fails
 * (`baseline/README.md` "Standalone axe results"), which is what makes the
 * gate a red→green claim rather than a wish: each one is a defect that exists
 * on `1f3f45a` and must not exist on any state of the redesign.
 *
 * They are NOT suppressible. The allowlist below can silence a rule the
 * baseline never failed — a new rule, a new surface, a genuinely accepted
 * risk — but silencing one of these six would silence the work order.
 */
export const GATED_RULES = [
  "landmark-one-main",
  "region",
  "aria-allowed-role",
  "listitem",
  "color-contrast",
  "page-has-heading-one",
] as const;

/** `03 §2.2` row 8: dark mode is an axis over every other state, not a state. */
export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

/**
 * `AxeResults` without importing `axe-core` directly.
 *
 * `axe-core` is a transitive dependency of `@axe-core/playwright`, not a
 * declared one of this package. Importing its types would work today and break
 * the day the resolution changes; deriving them from the function that
 * actually returns them cannot.
 */
export type AxeResults = Awaited<ReturnType<AxeBuilder["analyze"]>>;
export type AxeViolation = AxeResults["violations"][number];
export type AxeNode = AxeViolation["nodes"][number];

// --------------------------------------------------------------- the run

export interface AnalyzeOptions {
  /**
   * CSS selector to scope the analysis to.
   *
   * Unused by `axe.spec.ts`, which audits whole documents exactly as the
   * baseline exporter did. It exists for WO-24: a Storybook story is one
   * component inside a harness page, and auditing the harness would report
   * Storybook's own chrome as product defects.
   */
  include?: string;
  /** Selectors to cut out of the analysis. Same reasoning as `include`. */
  exclude?: readonly string[];
}

/**
 * Run axe over `page` with the baseline tag set.
 *
 * `resultTypes` is deliberately left at its default, so `passes` comes back
 * populated. That is not decoration: criterion 4's contrast proof reads the
 * measured `fgColor`/`bgColor`/`contrastRatio` axe recorded for the pairs that
 * PASSED, which is the only way to confirm a replacement colour "in a real
 * render" rather than arithmetically. A results object trimmed to violations
 * would make the tokens unprovable.
 */
export async function analyze(
  page: Page,
  options: AnalyzeOptions = {},
): Promise<AxeResults> {
  let builder = new AxeBuilder({ page }).withTags([...AXE_TAGS]);
  if (options.include !== undefined) builder = builder.include(options.include);
  for (const selector of options.exclude ?? []) builder = builder.exclude(selector);
  return builder.analyze();
}

/**
 * The tag set a results object was actually produced with.
 *
 * `toolOptions.runOnly` is a union — axe accepts a bare tag string, an array
 * of them, or the `{type, values}` object this gate uses — so the narrowing is
 * real work, not a cast. Reading it back off the run is what turns criterion
 * 1 from "we passed the right tags" into "the report in front of you was
 * produced with them".
 */
export function tagsOf(results: AxeResults): string[] | null {
  const runOnly = results.toolOptions?.runOnly;
  if (runOnly === undefined) return null;
  if (typeof runOnly === "string") return [runOnly];
  if (Array.isArray(runOnly)) return [...runOnly];
  return runOnly.values === undefined ? null : runOnly.values.map(String);
}

/**
 * Wait until the document has stopped changing, then audit.
 *
 * WHY A GATE NEEDS THIS. Every state in `support/states.ts` carries a ready
 * condition, and those conditions are correct — but "the heading is visible"
 * is not "the page has finished arriving". A thread route paints its header
 * from cache and then fills the run panel from `GET /research/{id}` and the
 * event list from the replayed stream. An axe run that lands between those
 * two moments finds fewer nodes and reports fewer violations, and a gate that
 * under-reports is worse than no gate: it is a green tick over an unaudited
 * surface.
 *
 * A fixed sleep would trade one guess for another, so this samples instead:
 * the run starts as soon as two consecutive samples of the serialised DOM
 * agree, and gives up after `timeoutMs` rather than failing, because a page
 * that genuinely never settles (a live stream) still has to be audited.
 */
export async function settleForAudit(
  page: Page,
  { quietMs = 400, timeoutMs = 6_000 }: { quietMs?: number; timeoutMs?: number } = {},
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let previous = -1;
  while (Date.now() < deadline) {
    const size = await page.evaluate(() => document.documentElement.outerHTML.length);
    if (size === previous) return;
    previous = size;
    await page.waitForTimeout(quietMs);
  }
}

// --------------------------------------------------------------- allowlist

/**
 * One suppressed finding.
 *
 * `justification` is required and must be prose a reviewer can disagree with.
 * 04 §7.4: "Any other rule may be suppressed only via a checked-in
 * `web/e2e/axe-allowlist.json`, which starts empty and requires a written
 * justification per entry in review." The parser below enforces the mechanical
 * half of that sentence so the review half is about the argument, not about
 * whether an argument was made at all.
 */
export interface AllowlistEntry {
  /** axe rule id. Never one of `GATED_RULES`. */
  rule: string;
  /** State id from `support/states.ts`, or `"*"` for every state. */
  state: string;
  /**
   * axe node target (the CSS selector axe reports), or `"*"`.
   *
   * Pinning the selector is what stops an entry written for one element from
   * silently covering a second occurrence of the same defect elsewhere.
   */
  selector: string;
  /** Why this is accepted, in prose. Enforced non-empty. */
  justification: string;
  /** Who accepted it, so the entry has an owner rather than a passive voice. */
  owner: string;
}

/** Where the checked-in allowlist lives, for error messages. */
export const ALLOWLIST_PATH = "web/e2e/axe-allowlist.json";

const MIN_JUSTIFICATION = 20;

/**
 * Parse and validate an allowlist document.
 *
 * Exported separately from `loadAllowlist` so criterion 3's *other* half —
 * "the harness fails on a non-empty allowlist without a justification field
 * per entry" — is provable. With the real file empty, an assertion that the
 * validator rejects a bad entry can only be made against a synthetic one, and
 * a validator that is never exercised is a comment.
 *
 * Throws rather than returning errors: an unreadable allowlist must stop the
 * gate, not degrade it to "suppress nothing" (which would look like a pass) or
 * to "suppress everything" (which would look like one too).
 */
export function parseAllowlist(raw: unknown, source = ALLOWLIST_PATH): AllowlistEntry[] {
  if (!Array.isArray(raw)) {
    throw new Error(`${source} must be a JSON array of allowlist entries.`);
  }

  const gated = new Set<string>(GATED_RULES);
  return raw.map((value, index) => {
    const at = `${source}[${index}]`;
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new Error(`${at} must be an object.`);
    }
    const entry = value as Record<string, unknown>;

    for (const field of ["rule", "state", "selector", "owner"] as const) {
      if (typeof entry[field] !== "string" || (entry[field] as string).trim() === "") {
        throw new Error(`${at} is missing a non-empty "${field}".`);
      }
    }

    const justification = entry.justification;
    if (typeof justification !== "string" || justification.trim().length < MIN_JUSTIFICATION) {
      throw new Error(
        `${at} (rule "${String(entry.rule)}") has no written justification. ` +
          `Every allowlist entry needs a "justification" of at least ` +
          `${MIN_JUSTIFICATION} characters saying why this finding is accepted ` +
          "(04-ARCHITECTURE.md §7.4). An allowlist entry without one is a " +
          "suppression nobody has to defend.",
      );
    }

    const rule = entry.rule as string;
    if (gated.has(rule)) {
      throw new Error(
        `${at} tries to suppress "${rule}", which WO-22 criterion 2 gates at ` +
          "zero across every state. These six rules are the defects the " +
          "redesign exists to fix; allowlisting one would allowlist the work " +
          "order. Fix the surface instead.",
      );
    }

    return {
      rule,
      state: entry.state as string,
      selector: entry.selector as string,
      justification: justification.trim(),
      owner: entry.owner as string,
    };
  });
}

/** The checked-in allowlist. Empty, and criterion 3 says it stays that way. */
export function loadAllowlist(): AllowlistEntry[] {
  return parseAllowlist(RAW_ALLOWLIST as unknown);
}

/** Does `entry` cover this violation node in this state? */
function covers(entry: AllowlistEntry, rule: string, state: string, node: AxeNode): boolean {
  if (entry.rule !== rule) return false;
  if (entry.state !== "*" && entry.state !== state) return false;
  if (entry.selector === "*") return true;
  return node.target.some((part) => String(part) === entry.selector);
}

// ------------------------------------------------------------- partitioning

export interface Partitioned {
  /** Violations of the six rules criterion 2 gates. Never suppressible. */
  gated: AxeViolation[];
  /** Violations of any other rule that no allowlist entry covers. */
  unlisted: AxeViolation[];
  /** Nodes an allowlist entry accounted for, kept so evidence names them. */
  suppressed: { rule: string; selector: string; justification: string }[];
}

/**
 * Split a run's violations into "breaks criterion 2", "breaks the allowlist
 * contract", and "consciously accepted".
 *
 * The three-way split matters for the failure message. "axe found 4
 * violations" tells a reader nothing about whether the redesign regressed on
 * a rule it promised to fix or tripped a rule nobody had considered, and those
 * two findings go to different people.
 */
export function partition(
  results: AxeResults,
  state: string,
  allowlist: readonly AllowlistEntry[],
): Partitioned {
  const gatedRules = new Set<string>(GATED_RULES);
  const out: Partitioned = { gated: [], unlisted: [], suppressed: [] };

  for (const violation of results.violations) {
    if (gatedRules.has(violation.id)) {
      out.gated.push(violation);
      continue;
    }
    const remaining: AxeNode[] = [];
    for (const node of violation.nodes) {
      const match = allowlist.find((entry) => covers(entry, violation.id, state, node));
      if (match === undefined) {
        remaining.push(node);
        continue;
      }
      out.suppressed.push({
        rule: violation.id,
        selector: node.target.map(String).join(" "),
        justification: match.justification,
      });
    }
    if (remaining.length > 0) out.unlisted.push({ ...violation, nodes: remaining });
  }

  return out;
}

/**
 * A failure message that can be pasted into a bug report unedited.
 *
 * Names the rule, the impact, every offending selector, and — for
 * `color-contrast`, the rule whose failures are otherwise impossible to
 * reproduce from a selector alone — the measured foreground, background,
 * ratio and font size axe actually saw.
 */
export function describe(violations: readonly AxeViolation[]): string {
  return violations
    .map((violation) => {
      const nodes = violation.nodes
        .map((node) => {
          const target = node.target.map(String).join(" ");
          const measured = contrastData(node);
          const detail =
            measured === null
              ? (node.failureSummary ?? "").replace(/\n+/g, " | ")
              : `${measured.fg} on ${measured.bg} at ${measured.fontSize} ` +
                `= ${measured.ratio} (needs ${measured.expected})`;
          return `      - ${target}\n        ${detail}`;
        })
        .join("\n");
      return (
        `  ${violation.id} [${violation.impact ?? "n/a"}] ` +
        `${violation.nodes.length} node(s) — ${violation.help}\n${nodes}`
      );
    })
    .join("\n");
}

// --------------------------------------------------------- contrast samples

/**
 * What axe measured for one `color-contrast` check, in the browser.
 *
 * These numbers come from the composited render — axe walks up the ancestor
 * chain resolving the actual painted background — which is exactly the thing
 * `03 §3.1` says the token table does *not* establish: "They are arithmetic on
 * the token set, not a browser measurement — so the axe gate in Phase 4 must
 * confirm them in a real render before the tokens are considered proven."
 */
export interface ContrastSample {
  /** Lowercase hex, as axe reports it. */
  fg: string;
  /** Lowercase hex, as axe reports it. */
  bg: string;
  ratio: number;
  /** Computed font size in CSS px, parsed from axe's `"9pt (12px)"`. */
  fontSizePx: number | null;
  fontWeight: string;
  /** The axe node target this was measured on. */
  target: string;
  /** Which axe bucket it came from. */
  outcome: "pass" | "violation" | "incomplete";
}

interface ContrastCheckData {
  fgColor: string;
  bgColor: string;
  contrastRatio: number;
  fontSize: string;
  fontWeight: string;
  expectedContrastRatio: string;
}

function contrastData(node: AxeNode): {
  fg: string;
  bg: string;
  ratio: number;
  fontSize: string;
  expected: string;
  fontWeight: string;
} | null {
  for (const check of [...node.any, ...node.all, ...node.none]) {
    if (check.id !== "color-contrast" && check.id !== "color-contrast-enhanced") continue;
    const data = check.data as Partial<ContrastCheckData> | undefined;
    if (data?.fgColor === undefined || data.bgColor === undefined) continue;
    return {
      fg: data.fgColor.toLowerCase(),
      bg: data.bgColor.toLowerCase(),
      ratio: Number(data.contrastRatio ?? 0),
      fontSize: data.fontSize ?? "unknown",
      expected: data.expectedContrastRatio ?? "unknown",
      fontWeight: data.fontWeight ?? "unknown",
    };
  }
  return null;
}

/** `"9pt (12px)"` → `12`. Returns null rather than guessing. */
function pxFrom(fontSize: string): number | null {
  const match = /\(([\d.]+)px\)/.exec(fontSize);
  return match?.[1] === undefined ? null : Number(match[1]);
}

/**
 * Every colour pair axe actually measured on this page, whatever the outcome.
 *
 * Passes are included on purpose. A gate that only reads violations can prove
 * "nothing is broken"; it cannot prove "this specific replacement token is on
 * screen and measures 5.44". Criterion 4 asks for the second thing.
 */
export function contrastSamples(results: AxeResults): ContrastSample[] {
  const out: ContrastSample[] = [];
  const buckets = [
    ["pass", results.passes],
    ["violation", results.violations],
    ["incomplete", results.incomplete],
  ] as const;

  for (const [outcome, group] of buckets) {
    for (const result of group) {
      if (result.id !== "color-contrast") continue;
      for (const node of result.nodes) {
        const measured = contrastData(node);
        if (measured === null) continue;
        out.push({
          fg: measured.fg,
          bg: measured.bg,
          ratio: measured.ratio,
          fontSizePx: pxFrom(measured.fontSize),
          fontWeight: measured.fontWeight,
          target: node.target.map(String).join(" "),
          outcome,
        });
      }
    }
  }
  return out;
}

/** Find every measurement of one exact foreground/background pair. */
export function samplesFor(
  samples: readonly ContrastSample[],
  pair: { fg: string; bg: string },
): ContrastSample[] {
  const fg = pair.fg.toLowerCase();
  const bg = pair.bg.toLowerCase();
  return samples.filter((sample) => sample.fg === fg && sample.bg === bg);
}

// ----------------------------------------------------------- contrast probe

/** One colour pair to render, named by the custom properties that carry it. */
export interface ContrastProbe {
  /** Stable id, used in failure messages. */
  id: string;
  /** e.g. `--color-ink-muted`. */
  fgProperty: string;
  /** e.g. `--color-sunken`. */
  bgProperty: string;
  /** e.g. `--text-ui-xs-size`. */
  sizeProperty: string;
}

/** The container `analyze()` should be scoped to when a probe is mounted. */
export const CONTRAST_PROBE_ROOT = "[data-axe-contrast-probe]";

/**
 * Render the token pairs into the live document and let axe measure them.
 *
 * WHY THIS EXISTS AT ALL. `03 §3.1` is explicit that its ratios "are
 * arithmetic on the token set, not a browser measurement — so the axe gate in
 * Phase 4 must confirm them in a real render before the tokens are considered
 * proven". Two of the three replacement pairs have no product surface yet:
 * `review-text` belongs to WO-17's plan editor and `ink-muted` on `sunken`
 * belongs to WO-16's diagnostics well, and WO-20 has not composed either into
 * a route. Waiting for them would mean shipping the axe gate with criterion 4
 * unproven, which is the exact deferral `03 §3.1` refuses.
 *
 * WHAT IT DOES AND DOES NOT PROVE. It mounts the pairs *in the running
 * application*, referencing the shipped custom properties rather than any
 * value written here, and lets axe resolve the composited colours and the
 * computed font size the same way it does for every other node on the page.
 * That is a real render: the cascade, the theme resolution, the type scale and
 * axe's own measurement are all the product's. What it does not prove is that
 * a *surface* uses the pair — `axe.spec.ts` asserts that separately for the
 * one pair that is already on screen, and the sweep will pick the other two up
 * automatically once WO-20 composes them.
 */
export async function mountContrastProbe(
  page: Page,
  probes: readonly ContrastProbe[],
): Promise<void> {
  await page.evaluate((entries) => {
    document.querySelectorAll("[data-axe-contrast-probe]").forEach((old) => old.remove());
    const root = document.createElement("div");
    root.setAttribute("data-axe-contrast-probe", "");
    for (const probe of entries) {
      const field = document.createElement("div");
      field.setAttribute("data-axe-contrast-pair", probe.id);
      field.style.backgroundColor = `var(${probe.bgProperty})`;
      field.style.padding = "12px";
      const line = document.createElement("p");
      line.style.color = `var(${probe.fgProperty})`;
      line.style.fontSize = `var(${probe.sizeProperty})`;
      line.style.fontWeight = "400";
      line.style.margin = "0";
      // Real words, because axe skips nodes whose content is punctuation or
      // whitespace only — the same reason its `incomplete` bucket exists.
      line.textContent = `${probe.id} contrast probe`;
      field.append(line);
      root.append(field);
    }
    document.body.append(root);
  }, probes as ContrastProbe[]);
}

// ---------------------------------------------------------------- artifacts

/**
 * Where the reports go, derived from Playwright's `outputDir` for the same
 * reason `paid-path.ts` derives its own path that way: `outputDir` is already
 * absolute and already honours `E2E_ARTIFACT_DIR`, whereas `process.cwd()`
 * depends on where the operator happened to type `npm run e2e`.
 *
 * Under `build/` — `web/tests/tokens.test.ts` walks all of `web/` for literal
 * colours, and an axe report is nothing but literal colours. It skips `build`.
 */
export function axeDirFrom(outputDir: string): string {
  // `testInfo.outputDir` is `<config.outputDir>/<test-slug>` and
  // `config.outputDir` is `${ARTIFACT_DIR}/test-results`, so two levels up is
  // `build/e2e` — the directory `e2e/README.md` documents as the artifact
  // root and the one WO-24 uploads whole.
  return join(outputDir, "..", "..", "axe");
}

/** Absolute path of one artifact inside that directory, created on demand. */
export function axeArtifact(outputDir: string, name: string): string {
  const directory = axeDirFrom(outputDir);
  mkdirSync(directory, { recursive: true });
  return join(directory, name);
}

/**
 * Write one report in the same shape as the retained baseline files, so a
 * reviewer (and WO-26's `axe-diff.md`) can diff `build/e2e/axe/running.light.json`
 * against `docs/revamp/baseline/axe/running.json` directly.
 */
export function writeReport(outputDir: string, name: string, results: AxeResults): string {
  const directory = axeDirFrom(outputDir);
  mkdirSync(directory, { recursive: true });
  const file = join(directory, `${name}.json`);
  writeFileSync(file, `${JSON.stringify(results, null, 2)}\n`, "utf8");
  return file;
}

/** The header for the collected evidence table. */
const SUMMARY_HEADER = [
  "# WO-22 axe gate — one row per §4 state per theme.",
  `# axe-core tags: ${AXE_TAGS.join(", ")}`,
  `# gated at zero: ${GATED_RULES.join(", ")}`,
  "state\ttheme\t§4 rows\tviolations\tgated\tunlisted\tincomplete\tcontrast-passes",
].join("\n");

export interface SummaryRow {
  state: string;
  theme: Theme;
  rows: readonly string[];
  violations: number;
  gated: number;
  unlisted: number;
  incomplete: number;
  contrastPasses: number;
}

/**
 * One line per state per theme, appended as each test finishes.
 *
 * Written with `appendFileSync` from several worker processes, the same way
 * `paid-path.ts` writes its count file: `O_APPEND` makes a single short write
 * atomic, so lines interleave in completion order but never tear. The header
 * is created with the exclusive `wx` flag so exactly one worker can win the
 * race to write it and the rest carry on rather than truncating the file.
 */
export function appendSummaryRow(outputDir: string, row: SummaryRow): string {
  const directory = axeDirFrom(outputDir);
  mkdirSync(directory, { recursive: true });
  const file = join(directory, "summary.tsv");
  try {
    writeFileSync(file, `${SUMMARY_HEADER}\n`, { encoding: "utf8", flag: "wx" });
  } catch {
    // Another worker created it first, which is the expected case.
  }
  appendFileSync(
    file,
    [
      row.state,
      row.theme,
      row.rows.join("+"),
      row.violations,
      row.gated,
      row.unlisted,
      row.incomplete,
      row.contrastPasses,
    ].join("\t") + "\n",
    "utf8",
  );
  return file;
}
