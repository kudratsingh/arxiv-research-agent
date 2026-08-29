#!/usr/bin/env node
/**
 * WO-29 — run every Lighthouse CI profile in `web/lighthouserc.json` and record
 * what was measured.
 *
 * WHY A SCRIPT AND NOT THREE `lhci autorun` LINES IN THE WORKFLOW.
 *
 * Three reasons, in the order they mattered.
 *
 *   1. **One form factor per run.** `collect.settings` is global to an
 *      `lhci autorun` invocation, so 04-ARCHITECTURE.md §8.2's "per state AND
 *      per form factor" cannot be one command. It is three: mobile-412,
 *      desktop-1350, mobile-320. This file is the loop, and nothing else.
 *      Each profile is still executed by a plain
 *      `lhci autorun --config=<file>` — the configs handed to it are written
 *      to `build/lhci/configs/` byte-for-byte from `lighthouserc.json`, so
 *      what ran is on disk beside what it produced.
 *
 *   2. **The measured value has to survive a red run.** RC-06 requires the
 *      measured CLS to be recorded and any state above 0.000 to carry a
 *      justification, which is impossible if a breach leaves nothing behind
 *      but an exit code. `lhci autorun` already uploads after a failed
 *      assertion (`@lhci/cli/src/autorun/autorun.js` runs assert, remembers
 *      the failure, uploads, and only then exits 1), so the reports exist;
 *      this script turns them into `build/lhci/summary.md`, which is the
 *      artifact the nightly uploads and the evidence pack keeps.
 *
 *   3. **The base URL is not knowable at commit time.** `lighthouserc.json`
 *      hard-codes `stack.sh`'s default port, which is what CI gets. A desk
 *      run, or a second stack on the same machine, is on another port.
 *      `LHCI_BASE_URL` substitutes it here rather than making every URL in
 *      the committed config a placeholder that no `lhci autorun` could use on
 *      its own.
 *
 * WHAT IT DOES NOT DO. It sets no threshold and reads no threshold from
 * anywhere but `lighthouserc.json`. There is no skip flag and no environment
 * variable that turns an assertion off: this script takes no arguments, and
 * `LHCI_BASE_URL` can only change *where* the same assertions are evaluated.
 * That is 04 §8.4's ratchet rule, in the same shape `scripts/route-budgets.mjs`
 * gives it for the bundle budgets.
 *
 * USAGE
 *
 *   node scripts/lhci-run.mjs                       # stack.sh's default port
 *   LHCI_BASE_URL=http://127.0.0.1:13295 node scripts/lhci-run.mjs
 *
 * Exits non-zero if any profile's assertions failed.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const RC_PATH = path.join(WEB_ROOT, "lighthouserc.json");
const BUILD_DIR = path.join(WEB_ROOT, "build", "lhci");
const CONFIG_DIR = path.join(BUILD_DIR, "configs");
const LHCI_WORK_DIR = path.join(WEB_ROOT, ".lighthouseci");

/** The seven §8.2 assertions, in the order they appear in every report table. */
export const ASSERTION_IDS = [
  "categories:performance",
  "categories:accessibility",
  "categories:best-practices",
  "largest-contentful-paint",
  "total-blocking-time",
  "cumulative-layout-shift",
  "bf-cache",
];

/**
 * @param {number[]} values
 * @returns {number}
 */
function median(values) {
  // The same definition @lhci/utils/src/assertions.js uses for
  // `aggregationMethod: "median"`, so the number printed in the summary is the
  // number the assertion was evaluated against, not a second opinion about it.
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return /** @type {number} */ (sorted[mid]);
  return ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2;
}

/**
 * @param {unknown} value
 * @returns {value is Record<string, any>}
 */
function isRecord(value) {
  return typeof value === "object" && value !== null;
}

/** @returns {{rc: Record<string, any>, profiles: {id: string, label: string, ci: Record<string, any>}[]}} */
function loadProfiles() {
  const rc = JSON.parse(readFileSync(RC_PATH, "utf8"));
  if (!isRecord(rc.ci)) throw new Error(`${RC_PATH}: no "ci" block`);
  const profiles = [
    // `ci` IS the mobile-412 profile: a bare `npx lhci autorun` from web/ runs
    // exactly this one. It is listed first so the console output opens on the
    // form factor §8.2's tightest budgets belong to.
    { id: "mobile-412", label: "Mobile, 412 x 823", ci: rc.ci },
  ];
  for (const profile of rc.profiles ?? []) {
    if (!isRecord(profile.ci)) throw new Error(`${RC_PATH}: profile ${profile.id} has no "ci" block`);
    profiles.push({ id: profile.id, label: profile.label ?? profile.id, ci: profile.ci });
  }
  return { rc, profiles };
}

/**
 * Rewrites every collected URL onto `LHCI_BASE_URL`, preserving path + query.
 *
 * The assertions are untouched: every `matchingUrlPattern` in
 * `lighthouserc.json` is host-agnostic by construction, so moving the stack to
 * another port cannot silently detach a state from its budget. If one ever
 * did, the assertion would report zero matching audits rather than pass.
 *
 * @param {Record<string, any>} ci
 * @param {string | undefined} baseUrl
 * @returns {Record<string, any>}
 */
function withBaseUrl(ci, baseUrl) {
  const clone = JSON.parse(JSON.stringify(ci));
  if (!baseUrl) return clone;
  const base = new URL(baseUrl);
  clone.collect.url = clone.collect.url.map((/** @type {string} */ raw) => {
    const url = new URL(raw);
    url.protocol = base.protocol;
    url.host = base.host;
    return url.toString();
  });
  return clone;
}

/**
 * @param {string} configPath
 * @returns {number} the `lhci autorun` exit status
 */
function runAutorun(configPath) {
  // `.lighthouseci` is the working directory `lhci collect` writes into and
  // `lhci assert` reads back. `collect` clears it on every run, but clearing it
  // here too means a profile can never assert against the previous profile's
  // reports if `collect` ever fails halfway.
  rmSync(LHCI_WORK_DIR, { recursive: true, force: true });
  try {
    execFileSync("npx", ["--no-install", "lhci", "autorun", `--config=${configPath}`], {
      cwd: WEB_ROOT,
      stdio: "inherit",
      env: {
        ...process.env,
        // Never a real key, and never read by anything downstream of here —
        // the stack under audit is the seeded one, which reaches no provider.
        // Stated so a stray value in the operator's shell cannot be inherited
        // into a browser the audit drives. (06-WORK-ORDERS.md §0.)
        ANTHROPIC_API_KEY: "local-preview-disabled",
      },
    });
    return 0;
  } catch (error) {
    const status = /** @type {{status?: number}} */ (error).status;
    return typeof status === "number" ? status : 1;
  }
}

/**
 * @param {string} outputDir absolute path to the profile's upload directory
 * @returns {Map<string, {runs: Record<string, any>[]}>} keyed by requested URL
 */
function readManifest(outputDir) {
  const manifestPath = path.join(outputDir, "manifest.json");
  /** @type {Map<string, {runs: Record<string, any>[]}>} */
  const byUrl = new Map();
  if (!existsSync(manifestPath)) return byUrl;
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  for (const entry of manifest) {
    const lhr = JSON.parse(readFileSync(entry.jsonPath, "utf8"));
    const url = lhr.requestedUrl ?? entry.url;
    const bucket = byUrl.get(url) ?? { runs: [] };
    bucket.runs.push(lhr);
    byUrl.set(url, bucket);
  }
  return byUrl;
}

/**
 * @param {Record<string, any>[]} runs
 * @returns {Record<string, {median: number, values: number[]}>}
 */
function measure(runs) {
  /** @type {Record<string, number[]>} */
  const values = {
    "categories:performance": [],
    "categories:accessibility": [],
    "categories:best-practices": [],
    "largest-contentful-paint": [],
    "total-blocking-time": [],
    "cumulative-layout-shift": [],
    "bf-cache": [],
  };
  for (const lhr of runs) {
    values["categories:performance"]?.push(lhr.categories["performance"].score);
    values["categories:accessibility"]?.push(lhr.categories["accessibility"].score);
    values["categories:best-practices"]?.push(lhr.categories["best-practices"].score);
    values["largest-contentful-paint"]?.push(lhr.audits["largest-contentful-paint"].numericValue);
    values["total-blocking-time"]?.push(lhr.audits["total-blocking-time"].numericValue);
    values["cumulative-layout-shift"]?.push(lhr.audits["cumulative-layout-shift"].numericValue);
    values["bf-cache"]?.push(lhr.audits["bf-cache"].score);
  }
  /** @type {Record<string, {median: number, values: number[]}>} */
  const out = {};
  for (const [id, list] of Object.entries(values)) out[id] = { median: median(list), values: list };
  return out;
}

/**
 * The `bf-cache` failure reasons, deduplicated across the profile's runs.
 * RC-18's evidence is the reason, not just the score.
 *
 * @param {Record<string, any>[]} runs
 * @returns {string[]}
 */
function bfCacheReasons(runs) {
  /** @type {Set<string>} */
  const reasons = new Set();
  for (const lhr of runs) {
    for (const item of lhr.audits["bf-cache"]?.details?.items ?? []) {
      reasons.add(`${item.protocolReason} (${item.failureType})`);
    }
  }
  return [...reasons];
}

/**
 * Every assertion LHCI will evaluate for one URL, as a flat list.
 *
 * A LIST AND NOT A MERGED MAP, DELIBERATELY. LHCI applies *every* matrix entry
 * whose pattern matches the URL — `@lhci/utils/src/assertions.js` loops the
 * whole matrix per URL rather than picking one — and `lighthouserc.json` uses
 * that to assert `total-blocking-time` twice on every cell: `error` at the
 * runner ceiling in the per-state entry, `warn` at 04 §8.2's ratified ceiling
 * in the catch-all entry. Keying this by audit id would collapse those two
 * into one and under-report the inventory by ten, which is exactly the kind of
 * quiet miscount the evidence pack exists to rule out.
 *
 * @param {Record<string, any>} ci
 * @param {string} url
 * @returns {{auditId: string, level: string, options: Record<string, number | string>}[]}
 */
function assertionsForUrl(ci, url) {
  /** @type {{auditId: string, level: string, options: Record<string, number | string>}[]} */
  const all = [];
  for (const entry of ci.assert.assertMatrix) {
    if (!new RegExp(entry.matchingUrlPattern).test(url)) continue;
    for (const [auditId, [level, options]] of Object.entries(entry.assertions)) {
      all.push({ auditId, level, options });
    }
  }
  return all;
}

function main() {
  const baseUrl = process.env["LHCI_BASE_URL"];
  const { profiles } = loadProfiles();

  rmSync(BUILD_DIR, { recursive: true, force: true });
  mkdirSync(CONFIG_DIR, { recursive: true });

  /** @type {{profile: {id: string, label: string}, status: number, rows: any[]}[]} */
  const results = [];
  let assertionCount = 0;

  for (const profile of profiles) {
    const ci = withBaseUrl(profile.ci, baseUrl);
    const configPath = path.join(CONFIG_DIR, `${profile.id}.json`);
    writeFileSync(configPath, `${JSON.stringify({ ci }, null, 2)}\n`);

    process.stdout.write(`\n=== ${profile.id} — ${profile.label} ===\n`);
    const status = runAutorun(configPath);

    const outputDir = path.resolve(WEB_ROOT, ci.upload.outputDir);
    const byUrl = readManifest(outputDir);

    /** @type {any[]} */
    const rows = [];
    for (const url of ci.collect.url) {
      const bucket = byUrl.get(url);
      const assertions = assertionsForUrl(ci, url);
      assertionCount += assertions.length;
      if (!bucket) {
        rows.push({ url, error: "no report collected", assertions });
        continue;
      }
      rows.push({
        url,
        runs: bucket.runs.length,
        lighthouseVersion: bucket.runs[0]?.lighthouseVersion,
        measured: measure(bucket.runs),
        bfCacheReasons: bfCacheReasons(bucket.runs),
        assertions,
      });
    }

    // `lhci assert` writes its per-assertion verdicts here. Keeping a copy
    // beside the reports is what makes a red nightly readable a week later.
    const assertionResults = path.join(LHCI_WORK_DIR, "assertion-results.json");
    if (existsSync(assertionResults)) {
      writeFileSync(
        path.join(outputDir, "assertion-results.json"),
        readFileSync(assertionResults, "utf8"),
      );
    }

    results.push({ profile, status, rows });
  }

  writeFileSync(
    path.join(BUILD_DIR, "summary.json"),
    `${JSON.stringify({ generatedAt: new Date().toISOString(), baseUrl: baseUrl ?? null, assertionCount, results }, null, 2)}\n`,
  );
  writeFileSync(path.join(BUILD_DIR, "summary.md"), renderSummary(results, assertionCount, baseUrl));

  const failed = results.filter((result) => result.status !== 0);
  process.stdout.write(`\n${readFileSync(path.join(BUILD_DIR, "summary.md"), "utf8")}\n`);
  if (failed.length > 0) {
    process.stderr.write(
      `\nlhci: ${failed.length} of ${results.length} profiles failed their §8.2 assertions ` +
        `(${failed.map((f) => f.profile.id).join(", ")}). See build/lhci/summary.md.\n`,
    );
    process.exitCode = 1;
    return;
  }
  process.stdout.write(`\nlhci: all ${results.length} profiles passed (${assertionCount} assertions).\n`);
}

/**
 * @param {{profile: {id: string, label: string}, status: number, rows: any[]}[]} results
 * @param {number} assertionCount
 * @param {string | undefined} baseUrl
 * @returns {string}
 */
function renderSummary(results, assertionCount, baseUrl) {
  const lines = [];
  lines.push("# Lighthouse CI — §8.2 assertion run");
  lines.push("");
  lines.push(
    "Produced by `node scripts/lhci-run.mjs` (WO-29). Every number below is a **local lab " +
      "measurement** against the seeded Compose stack — a Lighthouse simulated-throttling run on " +
      "one machine, not field p75. See `docs/revamp/evidence/gate-4/lhci/README.md` §1.",
  );
  lines.push("");
  lines.push(`- Generated: \`${new Date().toISOString()}\``);
  lines.push(`- Base URL: \`${baseUrl ?? "(lighthouserc.json default)"}\``);
  lines.push(`- Assertions evaluated: **${assertionCount}**`);
  lines.push("");

  for (const { profile, status, rows } of results) {
    lines.push(`## ${profile.id} — ${profile.label}`);
    lines.push("");
    lines.push(`Result: **${status === 0 ? "PASS" : "FAIL"}** (\`lhci autorun\` exit ${status})`);
    lines.push("");
    lines.push("| State | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |");
    lines.push("|---|---:|---:|---:|---:|---:|---:|:-:|");
    for (const row of rows) {
      const label = new URL(row.url).pathname + new URL(row.url).search;
      if (row.error) {
        lines.push(`| \`${label}\` | — | — | — | — | — | — | ${row.error} |`);
        continue;
      }
      const m = row.measured;
      const score = (/** @type {string} */ id) => Math.round(m[id].median * 100);
      const bf = m["bf-cache"].median === 1 ? "pass" : "**fail**";
      // TBT carries two ceilings (see lighthouserc.json's TBT comment): the
      // ratified §8.2 number as a `warn`, and 2x it as the `error` the runner
      // is actually gated on. Flagging the warn breach in the table is the
      // point of keeping the ratified number at all — otherwise a run that
      // drifted past 04 §8.2 and stayed under the runner ceiling would read as
      // an unremarkable green row.
      const warnTbt = row.assertions.find(
        (/** @type {{auditId: string, level: string}} */ a) =>
          a.auditId === "total-blocking-time" && a.level === "warn",
      );
      const tbtMedian = Math.round(m["total-blocking-time"].median);
      const ratified = warnTbt ? Number(warnTbt.options["maxNumericValue"]) : Infinity;
      const tbt = tbtMedian > ratified ? `**${tbtMedian} ms** ⚠️` : `${tbtMedian} ms`;
      lines.push(
        `| \`${label}\` | ${score("categories:performance")} | ${score("categories:accessibility")} ` +
          `| ${score("categories:best-practices")} | ${(m["largest-contentful-paint"].median / 1000).toFixed(2)} s ` +
          `| ${tbt} | ${m["cumulative-layout-shift"].median.toFixed(5)} | ${bf} |`,
      );
    }
    lines.push("");
    const warnCeiling = rows
      .flatMap((/** @type {any} */ row) => row.assertions ?? [])
      .find(
        (/** @type {{auditId: string, level: string}} */ a) =>
          a.auditId === "total-blocking-time" && a.level === "warn",
      );
    if (warnCeiling) {
      lines.push(
        `⚠️ on TBT means the measured median is past 04 §8.2's ratified ceiling of ` +
          `${warnCeiling.options["maxNumericValue"]} ms without breaching the runner ceiling the run ` +
          `is gated on. It is a warning, not a failure — see \`web/lighthouserc.json\`'s ` +
          `"TOTAL BLOCKING TIME" comment.`,
      );
      lines.push("");
    }
    lines.push("Per-run spread (median is what the assertions were evaluated against):");
    lines.push("");
    lines.push("| State | LCP runs (ms) | TBT runs (ms) | CLS runs | bf-cache reasons |");
    lines.push("|---|---|---|---|---|");
    for (const row of rows) {
      if (row.error) continue;
      const label = new URL(row.url).pathname + new URL(row.url).search;
      const m = row.measured;
      const list = (/** @type {string} */ id, /** @type {(n: number) => string} */ fmt) =>
        m[id].values.map(fmt).join(", ");
      lines.push(
        `| \`${label}\` | ${list("largest-contentful-paint", (n) => n.toFixed(0))} ` +
          `| ${list("total-blocking-time", (n) => n.toFixed(0))} ` +
          `| ${list("cumulative-layout-shift", (n) => n.toFixed(5))} ` +
          `| ${row.bfCacheReasons.length ? row.bfCacheReasons.join("; ") : "—"} |`,
      );
    }
    lines.push("");
  }
  return `${lines.join("\n")}\n`;
}

main();
