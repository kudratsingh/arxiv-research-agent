/**
 * Types for `audit-gate.mjs` (WO-24, 05-MIGRATION.md C4).
 *
 * Same arrangement, and the same reason, as `route-budgets.d.mts`: the script
 * stays plain ESM JavaScript because `tsconfig.json` sets `allowJs: false` and
 * the build tool is pinned to `next build --webpack` (B4), so these
 * declarations are what let `tests/audit.test.ts` import it under
 * `tsc --noEmit` without loosening the project's TypeScript settings.
 */

export declare const BLOCKING_SEVERITIES: string[];
export declare const MIN_JUSTIFICATION: number;
export declare const REQUIRED_FIELDS: string[];
export declare const EXCEPTIONS_PATH: string;

export interface AuditAdvisory {
  source: number;
  name?: string;
  title?: string;
  url?: string;
  severity?: string;
}

export interface AuditVulnerability {
  name?: string;
  severity: string;
  isDirect?: boolean;
  via?: (string | AuditAdvisory)[];
  effects?: string[];
  nodes?: string[];
  fixAvailable?: boolean | Record<string, unknown>;
}

export interface AuditReport {
  vulnerabilities?: Record<string, AuditVulnerability>;
  metadata?: Record<string, unknown>;
}

export interface Finding {
  package: string;
  severity: string;
  isDirect: boolean;
  nodes: string[];
  advisories: number[];
  titles: string[];
}

export interface Exception {
  package: string;
  advisories: number[];
  path: string;
  date: string;
  owner: string | null;
  severity: string | null;
  justification: string;
}

export interface FullTreeResult {
  findings: Finding[];
  accepted: { finding: Finding; entry: Exception }[];
  unlisted: { finding: Finding; entry: Exception | null }[];
  stale: Exception[];
  ok: boolean;
}

export interface ProductionResult {
  findings: Finding[];
  ok: boolean;
}

export declare function runAudit(input: { cwd: string; omitDev?: boolean }): AuditReport;
export declare function advisoryIdsOf(
  report: AuditReport,
  name: string,
  seen?: Set<string>,
): Set<number>;
export declare function blockingFindings(report: AuditReport): Finding[];
export declare function parseExceptions(raw: unknown, source?: string): Exception[];
export declare function loadExceptions(webDir: string): Exception[];
export declare function evaluateFullTree(input: {
  report: AuditReport;
  exceptions: Exception[];
}): FullTreeResult;
export declare function evaluateProduction(input: { report: AuditReport }): ProductionResult;
export declare function renderSummary(input: {
  production: ProductionResult;
  full: FullTreeResult;
  exceptions: Exception[];
}): string;
export declare function run(input?: { webDir: string; reportPath?: string }): {
  exceptions: Exception[];
  production: ProductionResult;
  full: FullTreeResult;
  reportPath: string;
  ok: boolean;
};
