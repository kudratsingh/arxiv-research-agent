/**
 * Types for `healthcheck.mjs` (WO-30, 05-MIGRATION.md C5).
 *
 * Same arrangement, and the same reason, as `audit-gate.d.mts` and
 * `route-budgets.d.mts`: the script stays plain ESM JavaScript because
 * `tsconfig.json` sets `allowJs: false` and because the runtime image runs it
 * with bare `node`, so these declarations are what let
 * `tests/healthcheck.test.ts` import it under `tsc --noEmit` without
 * loosening the project's TypeScript settings.
 */

export declare const DEFAULT_URL: string;
export declare const DEFAULT_TIMEOUT_MS: number;
export declare const HEALTHY_STATUS: number;

export declare const REPORT: {
  OK: "ok";
  DEGRADED: "degraded";
  UNKNOWN: "unknown";
  UNREACHABLE: "unreachable";
};

export type HealthReport = "ok" | "degraded" | "unknown" | "unreachable";

export interface ProbeResult {
  statusCode?: number;
  body?: string;
  error?: string;
}

export interface Classification {
  /** 0 iff the HTTP status was 200. Never influenced by `report`. */
  exitCode: number;
  report: HealthReport;
  status: string | null;
  dependencies: Record<string, string>;
  /** The JSON line written to stdout. */
  line: string;
}

export declare function classify(result: ProbeResult): Classification;
export declare function probe(url?: string, timeoutMs?: number): Promise<ProbeResult>;
export declare function main(url?: string): Promise<number>;
