#!/usr/bin/env node
/**
 * Dependency audit gate (WO-24, 05-MIGRATION.md C4).
 *
 * WHY THIS IS A SCRIPT AND NOT ONE `npm audit` LINE IN THE WORKFLOW.
 *
 * C4 was written against a baseline of "0 vulnerabilities across 669
 * dependencies" (`docs/revamp/baseline/npm-audit.json`), captured before WO-06
 * added Storybook. Storybook's Vite framework package pulls `image-size`, which
 * carries two unfixed high-severity advisories, so a bare
 * `npm audit --audit-level=high` is red on `main` today through no fault of any
 * shipped code. There were three ways out and only one of them is a gate:
 *
 *   - lower `--audit-level` to `critical`: silences every future high advisory,
 *     including one in a production dependency. Rejected.
 *   - `--omit=dev` and nothing else: silences the whole dev tree forever, which
 *     is where a supply-chain attack on a build tool would land. Rejected.
 *   - split the gate. Production dependencies are gated at ZERO with no
 *     exception mechanism at all; the dev tree is gated against an explicit,
 *     justified, dated exceptions file, and ANY advisory that file does not
 *     name fails the job. That is this script.
 *
 * The exceptions file follows WO-22's allowlist contract deliberately
 * (`web/e2e/support/axe.ts`): every entry needs a written justification, a
 * missing or perfunctory one is a hard error, and the check fails in BOTH
 * directions — a stale entry that no longer matches a reported advisory fails
 * too, so an exception cannot outlive the problem it documents.
 *
 * NO SKIP PATH, for the same reason `route-budgets.mjs` has none: this module
 * accepts no arguments that soften it and reads no environment variable that
 * could turn it off. The only way to make a new high advisory pass is to fix
 * it, or to write down why it is accepted and sign the entry.
 *
 * It also writes the full `npm audit --json` report to `npm-audit.json`, which
 * the `web` CI job uploads and WO-33 collects into the Gate 4 evidence pack.
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/** Severities this gate treats as blocking, matching `--audit-level=high`. */
export const BLOCKING_SEVERITIES = ["high", "critical"];

/** Same floor WO-22's axe allowlist uses. A one-word excuse is not a reason. */
export const MIN_JUSTIFICATION = 20;

/** Required on every exception entry. The ruling names all five. */
export const REQUIRED_FIELDS = ["package", "advisories", "path", "justification", "date"];

export const EXCEPTIONS_PATH = "web/audit-exceptions.json";

// ---------------------------------------------------------------------------
// Running npm audit
// ---------------------------------------------------------------------------

/**
 * `npm audit --json` in `cwd`, parsed.
 *
 * npm exits non-zero when it finds something at or above `--audit-level`, which
 * is exactly the case this script exists to inspect, so the exit status is
 * ignored and the JSON body is the source of truth. A non-JSON body (npm could
 * not resolve the tree, no lockfile, network failure) is re-thrown with the raw
 * output attached rather than being silently treated as "no vulnerabilities" —
 * an audit gate that goes green when the audit itself failed is worse than no
 * gate.
 */
export function runAudit({ cwd, omitDev = false }) {
  const args = ["audit", "--audit-level=high", "--json"];
  if (omitDev) args.push("--omit=dev");
  let stdout;
  try {
    stdout = execFileSync("npm", args, {
      cwd,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    stdout = error.stdout ?? "";
    if (stdout.trim() === "") {
      throw new Error(
        `\`npm ${args.join(" ")}\` produced no JSON:\n${error.stderr ?? error.message}`,
      );
    }
  }
  try {
    return JSON.parse(stdout);
  } catch {
    throw new Error(`\`npm ${args.join(" ")}\` did not emit JSON:\n${stdout.slice(0, 2000)}`);
  }
}

// ---------------------------------------------------------------------------
// Reading a report
// ---------------------------------------------------------------------------

/**
 * The root advisory ids one `npm audit` vulnerability entry rests on.
 *
 * npm's `via` is a mixed list: advisory objects for the package that actually
 * carries the defect, and plain package-name strings for anything that merely
 * depends on it. Resolving the name chain gives every entry the same key — the
 * set of GitHub advisory ids underneath it — so a dependent package and the
 * package at fault can be matched by the same mechanism instead of by two.
 */
export function advisoryIdsOf(report, name, seen = new Set()) {
  const ids = new Set();
  if (seen.has(name)) return ids;
  seen.add(name);
  const entry = report.vulnerabilities?.[name];
  for (const via of entry?.via ?? []) {
    if (typeof via === "string") {
      for (const id of advisoryIdsOf(report, via, seen)) ids.add(id);
    } else if (via && typeof via === "object" && via.source !== undefined) {
      ids.add(Number(via.source));
    }
  }
  return ids;
}

/**
 * Every blocking-severity finding in a report, flattened.
 *
 * `npm audit --audit-level=high` still reports lower severities in its JSON
 * body — the flag only governs the exit code — so the severity filter is
 * applied here rather than trusted from the invocation.
 */
export function blockingFindings(report) {
  const out = [];
  for (const [name, entry] of Object.entries(report.vulnerabilities ?? {})) {
    if (!BLOCKING_SEVERITIES.includes(entry.severity)) continue;
    out.push({
      package: name,
      severity: entry.severity,
      isDirect: Boolean(entry.isDirect),
      nodes: entry.nodes ?? [],
      advisories: [...advisoryIdsOf(report, name)].sort((a, b) => a - b),
      titles: (entry.via ?? [])
        .filter((via) => via && typeof via === "object" && via.title)
        .map((via) => via.title),
    });
  }
  return out.sort((a, b) => a.package.localeCompare(b.package));
}

// ---------------------------------------------------------------------------
// The exceptions file
// ---------------------------------------------------------------------------

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Parse and validate the exceptions file.
 *
 * Every failure here is a hard error, never a warning. An exceptions file the
 * script half-understands is a suppression nobody has to defend.
 */
export function parseExceptions(raw, source = EXCEPTIONS_PATH) {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error(`${source} must be a JSON object with an "exceptions" array.`);
  }
  const list = raw.exceptions;
  if (!Array.isArray(list)) {
    throw new Error(`${source}: "exceptions" must be an array (it may be empty).`);
  }

  const seen = new Set();
  return list.map((value, index) => {
    const at = `${source}.exceptions[${index}]`;
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new Error(`${at} must be an object.`);
    }
    for (const field of REQUIRED_FIELDS) {
      if (value[field] === undefined) throw new Error(`${at} is missing "${field}".`);
    }

    const name = value.package;
    if (typeof name !== "string" || name.trim() === "") {
      throw new Error(`${at} needs a non-empty "package".`);
    }
    if (seen.has(name)) {
      throw new Error(`${at}: "${name}" is listed twice; one entry per reported package.`);
    }
    seen.add(name);

    if (
      !Array.isArray(value.advisories) ||
      value.advisories.length === 0 ||
      value.advisories.some((id) => !Number.isInteger(id))
    ) {
      throw new Error(
        `${at} ("${name}") needs "advisories": a non-empty array of the integer npm ` +
          `advisory ids this exception covers, so it stops applying the moment the ` +
          `advisory set underneath the package changes.`,
      );
    }

    const dependencyPath = value.path;
    if (typeof dependencyPath !== "string" || dependencyPath.trim() === "") {
      throw new Error(`${at} ("${name}") needs a non-empty "path".`);
    }
    const last = dependencyPath.split(">").pop().trim();
    if (last !== name) {
      throw new Error(
        `${at}: "path" must end at the package it covers — it ends at "${last}", ` +
          `not "${name}". The path is how a reader sees which direct dependency ` +
          `drags the advisory in.`,
      );
    }

    if (typeof value.date !== "string" || !DATE.test(value.date)) {
      throw new Error(`${at} ("${name}") needs a "date" in YYYY-MM-DD form.`);
    }

    const justification = value.justification;
    if (typeof justification !== "string" || justification.trim().length < MIN_JUSTIFICATION) {
      throw new Error(
        `${at} ("${name}") has no written justification. Every exception needs a ` +
          `"justification" of at least ${MIN_JUSTIFICATION} characters saying why the ` +
          `advisory is accepted and what would remove it (05-MIGRATION.md C4). An ` +
          `exception without one is a suppression nobody has to defend.`,
      );
    }

    return {
      package: name,
      advisories: [...value.advisories].sort((a, b) => a - b),
      path: dependencyPath,
      date: value.date,
      owner: typeof value.owner === "string" ? value.owner : null,
      severity: typeof value.severity === "string" ? value.severity : null,
      justification: justification.trim(),
    };
  });
}

export function loadExceptions(webDir) {
  const file = path.join(webDir, "audit-exceptions.json");
  return parseExceptions(JSON.parse(fs.readFileSync(file, "utf8")), EXCEPTIONS_PATH);
}

function sameIds(a, b) {
  return a.length === b.length && a.every((id, index) => id === b[index]);
}

// ---------------------------------------------------------------------------
// Evaluation
// ---------------------------------------------------------------------------

/**
 * Compare a full-tree report against the exceptions file.
 *
 * Three outcomes, and the third is the one that keeps the file honest:
 *
 *   `unlisted`  — a blocking advisory no entry covers. The gate's whole point.
 *   `accepted`  — matched an entry exactly (package AND advisory id set).
 *   `stale`     — an entry that matched nothing in this report. Also a failure:
 *                 an exception that outlives its advisory is a standing
 *                 permission slip for whatever lands on that package next.
 *
 * A package whose advisory set has *changed* lands in `unlisted` rather than
 * `accepted`, because the ids no longer match — a new advisory on an
 * already-excepted package must be read and signed for, not inherited.
 */
export function evaluateFullTree({ report, exceptions }) {
  const findings = blockingFindings(report);
  const byPackage = new Map(exceptions.map((entry) => [entry.package, entry]));
  const matched = new Set();

  const accepted = [];
  const unlisted = [];
  for (const finding of findings) {
    const entry = byPackage.get(finding.package);
    if (entry && sameIds(entry.advisories, finding.advisories)) {
      matched.add(entry.package);
      accepted.push({ finding, entry });
    } else {
      unlisted.push({ finding, entry: entry ?? null });
    }
  }

  const stale = exceptions.filter((entry) => !matched.has(entry.package));
  return { findings, accepted, unlisted, stale, ok: unlisted.length === 0 && stale.length === 0 };
}

/** The production half. No exception mechanism: zero means zero. */
export function evaluateProduction({ report }) {
  const findings = blockingFindings(report);
  return { findings, ok: findings.length === 0 };
}

// ---------------------------------------------------------------------------
// Reporting
// ---------------------------------------------------------------------------

function describe(finding) {
  const advisories = finding.advisories.length > 0 ? finding.advisories.join(", ") : "none reported";
  const titles = finding.titles.length > 0 ? ` — ${finding.titles.join("; ")}` : "";
  return `${finding.package} (${finding.severity}, advisories ${advisories})${titles}`;
}

export function renderSummary({ production, full, exceptions }) {
  const lines = [];
  lines.push("Dependency audit gate (05-MIGRATION.md C4)");
  lines.push("");
  lines.push(
    `  production tree  (--omit=dev): ${
      production.ok ? "0 high/critical advisories" : `${production.findings.length} BLOCKING`
    }`,
  );
  for (const finding of production.findings) lines.push(`    ! ${describe(finding)}`);
  lines.push(
    `  full tree        (incl. dev): ${full.findings.length} high/critical advisor` +
      `${full.findings.length === 1 ? "y" : "ies"}, ${full.accepted.length} accounted for by ` +
      `${exceptions.length} exception${exceptions.length === 1 ? "" : "s"}`,
  );
  for (const { finding, entry } of full.accepted) {
    lines.push(`    ok ${describe(finding)}`);
    lines.push(`       accepted ${entry.date}${entry.owner ? ` by ${entry.owner}` : ""}: ${entry.path}`);
  }
  for (const { finding, entry } of full.unlisted) {
    lines.push(`    ! ${describe(finding)}`);
    lines.push(
      entry
        ? `       ${EXCEPTIONS_PATH} lists "${finding.package}" for advisories ` +
          `${entry.advisories.join(", ")}, not ${finding.advisories.join(", ")}.`
        : `       not listed in ${EXCEPTIONS_PATH}.`,
    );
  }
  for (const entry of full.stale) {
    lines.push(`    ! stale exception: "${entry.package}" matches nothing in this report.`);
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

export function run({ webDir, reportPath = path.join(webDir, "npm-audit.json") } = {}) {
  const exceptions = loadExceptions(webDir);
  const productionReport = runAudit({ cwd: webDir, omitDev: true });
  const fullReport = runAudit({ cwd: webDir, omitDev: false });

  fs.writeFileSync(reportPath, `${JSON.stringify(fullReport, null, 2)}\n`, "utf8");

  const production = evaluateProduction({ report: productionReport });
  const full = evaluateFullTree({ report: fullReport, exceptions });
  return { exceptions, production, full, reportPath, ok: production.ok && full.ok };
}

function main(argv) {
  if (argv.length > 0) {
    console.error(
      "audit-gate: this check takes no arguments. There is no flag that softens it; " +
        `accepted advisories are written down, with a reason, in ${EXCEPTIONS_PATH}.`,
    );
    return 2;
  }
  const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const result = run({ webDir });

  console.log(renderSummary(result));
  console.log(`\nFull report written to ${result.reportPath}`);

  if (!result.production.ok) {
    console.error(
      "\nA high or critical advisory is reachable from the PRODUCTION dependency tree. " +
        "That half of the gate has no exception mechanism: fix, upgrade, or remove the " +
        "dependency.",
    );
  }
  if (result.full.unlisted.length > 0) {
    console.error(
      `\nA high or critical advisory in the dev tree is not accounted for in ` +
        `${EXCEPTIONS_PATH}. Either fix it, or add an entry naming the advisory ids, the ` +
        `dependency path, today's date and a written justification.`,
    );
  }
  if (result.full.stale.length > 0) {
    console.error(
      `\n${EXCEPTIONS_PATH} carries an entry that no longer matches anything npm reports. ` +
        "Delete it: an exception that outlives its advisory is a standing permission slip.",
    );
  }
  return result.ok ? 0 : 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exit(main(process.argv.slice(2)));
}
