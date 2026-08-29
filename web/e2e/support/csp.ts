import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { Page, Response } from "@playwright/test";

/**
 * The browser half of WO-30's CSP evidence: what a violation IS, how it is
 * collected without being invented, and where the two runs are written down.
 *
 * TWO INDEPENDENT DETECTORS, AND BOTH ARE NEEDED.
 *
 *   1. `securitypolicyviolation` events. The spec-defined signal, fired for
 *      both dispositions, carrying the effective directive and the blocked
 *      URI. This is the precise one.
 *   2. Console messages matching the engines' CSP wording. Criterion 1 asks
 *      for "zero CSP **console** violations", and the two sets are not
 *      identical: a violation in a document the listener was never installed
 *      in — an iframe, an error page rendered before the init script — shows
 *      up in the console and nowhere else.
 *
 * A run is clean only when both are empty, and the failure message prints
 * whichever fired.
 *
 * WHY THE LISTENER CAN BE TRUSTED UNDER THE POLICY IT IS TESTING. It is
 * installed with `addInitScript`, which Playwright injects through CDP before
 * any page script — the same mechanism `installFirstPaintProbe` uses, and for
 * the same reason. CSP does not apply to it, so the collector cannot be
 * silenced by the thing it is collecting.
 */

/** One violation, flattened to the fields worth printing in a failure. */
export interface CspViolation {
  /** `script-src-elem`, `style-src-attr`, … */
  directive: string;
  /** `inline`, `eval`, or the refused URL. */
  blockedUri: string;
  /** `enforce` or `report` — which run this came from, per the browser. */
  disposition: string;
  /** First 60 characters of the refused source, when the engine supplies it. */
  sample: string;
  /** Where the violating document was. */
  documentUri: string;
  /**
   * The script that tripped it, and where in it.
   *
   * Not decoration. `blockedURI: "eval"` with no location is a finding
   * nobody can act on — the difference between "some bundle calls eval" and
   * "`static/chunks/363-*.js:1:196784` calls eval" is the difference between
   * a shrug and a fix. This is what located the `zod` `new Function` on the
   * plan-review state.
   */
  sourceFile: string;
  line: number;
  column: number;
}

declare global {
  interface Window {
    __wo30CspViolations?: CspViolation[];
  }
}

/** Install the collector. Must be called before `page.goto`. */
export async function installCspProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.__wo30CspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      window.__wo30CspViolations?.push({
        directive: event.effectiveDirective || event.violatedDirective,
        blockedUri: event.blockedURI,
        disposition: event.disposition,
        sample: (event.sample ?? "").slice(0, 60),
        documentUri: event.documentURI,
        sourceFile: event.sourceFile ?? "",
        line: event.lineNumber ?? 0,
        column: event.columnNumber ?? 0,
      });
    });
  });
}

/** Read what the collector recorded. */
export async function readCspViolations(page: Page): Promise<CspViolation[]> {
  return page.evaluate(() => window.__wo30CspViolations ?? []);
}

/**
 * Wait until Next's client runtime has actually executed.
 *
 * THE ASSERTION THIS EXISTS TO MAKE POSSIBLE. Under `'strict-dynamic'` an
 * un-nonced `<script src>` is refused *silently* — the server markup is
 * already in the document, so the page looks entirely correct and simply
 * never becomes interactive. A CSP sweep that only waited for a ready
 * condition would pass on a page whose every bundle chunk had been blocked,
 * which is the exact regression the sweep is for.
 *
 * `window.next` is created by the app-router client bootstrap, so its
 * presence means at least one nonced module script ran. The app publishes no
 * hydration sentinel of its own (`e2e/support/composer.ts` says so and works
 * around it differently), and adding one to the product for a test would be
 * the wrong direction.
 */
export async function waitForClientRuntime(page: Page, timeout = 20_000): Promise<void> {
  await page.waitForFunction(
    () =>
      (window as unknown as { next?: { router?: unknown } }).next?.router !== undefined,
    undefined,
    { timeout },
  );
}

/**
 * Whether a console message is the browser complaining about the CSP.
 *
 * Deliberately a wording match rather than "every console error": the suite
 * runs against a seeded stack where a state may legitimately log a failed
 * fetch, and a probe that failed on those would be testing the fixtures.
 */
export function isCspConsoleMessage(text: string): boolean {
  return /Content Security Policy|Content-Security-Policy|violates the following/i.test(
    text,
  );
}

// ------------------------------------------------------------------ the header

/** Which header the server sent, and its value. */
export interface CspHeaderReading {
  mode: "enforce" | "report-only" | "absent";
  policy: string;
  /** The nonce inside `script-src`, when there is one. */
  nonce: string | null;
}

/** Read the policy off a navigation response. */
export function readCspHeader(response: Response | null): CspHeaderReading {
  const headers = response?.headers() ?? {};
  const enforcing = headers["content-security-policy"];
  const reporting = headers["content-security-policy-report-only"];
  const policy = enforcing ?? reporting ?? "";
  const nonce = /'nonce-([^']+)'/.exec(policy);
  return {
    mode: enforcing !== undefined ? "enforce" : reporting !== undefined ? "report-only" : "absent",
    policy,
    nonce: nonce === null ? null : (nonce[1] as string),
  };
}

// --------------------------------------------------------------- the evidence

const HEADER = "state\trows\tmode\tviolations\tconsole\tdirectives";

/**
 * Append one row to `build/e2e/csp/sweep.tsv`.
 *
 * Criterion 1 asks for BOTH runs to be recorded, and a run that leaves no
 * artifact is a run somebody has to take on trust. The file lands beside the
 * axe reports under the directory WO-24 already uploads whole, and under
 * `build/` because `web/tests/tokens.test.ts` scans everything else in `web/`
 * for literal colours.
 */
export function appendCspRow(
  outputDir: string,
  row: {
    state: string;
    rows: readonly string[];
    mode: string;
    violations: CspViolation[];
    consoleMessages: string[];
  },
): string {
  const directory = join(outputDir, "..", "..", "csp");
  mkdirSync(directory, { recursive: true });
  const file = join(directory, "sweep.tsv");
  try {
    writeFileSync(file, `${HEADER}\n`, { encoding: "utf8", flag: "wx" });
  } catch {
    // Another worker created it first, which is the expected case.
  }
  appendFileSync(
    file,
    [
      row.state,
      row.rows.join("+"),
      row.mode,
      String(row.violations.length),
      String(row.consoleMessages.length),
      row.violations.map((violation) => violation.directive).join(",") || "—",
    ].join("\t") + "\n",
    "utf8",
  );
  return file;
}

/** A failure message that names the directive and the source, not just a count. */
export function describeViolations(
  violations: CspViolation[],
  consoleMessages: string[],
): string {
  const lines = violations.map(
    (violation) =>
      `  ${violation.disposition} ${violation.directive} blocked=${violation.blockedUri}` +
      (violation.sourceFile === ""
        ? ""
        : ` at ${violation.sourceFile}:${violation.line}:${violation.column}`) +
      (violation.sample === "" ? "" : ` sample=${JSON.stringify(violation.sample)}`),
  );
  for (const message of consoleMessages) lines.push(`  console: ${message}`);
  return lines.join("\n");
}
