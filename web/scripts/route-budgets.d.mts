/**
 * Types for `route-budgets.mjs` (WO-23).
 *
 * The script itself stays plain ESM JavaScript — `tsconfig.json` sets
 * `allowJs: false`, and the repo's build tool is pinned to `next build
 * --webpack` (B4), so adding a compile step for one build script would be the
 * wrong trade. These declarations let `tests/budgets.test.ts` import it under
 * `tsc --noEmit` without loosening the project's TypeScript settings.
 */

export declare const GZIP_LEVEL: 6;

export type RowKind =
  | "route-first-load-js"
  | "shared-first-load-js"
  | "emitted-css"
  | "self-hosted-fonts"
  | "external-total-transferred-js"
  | "derived-total-first-load";

export type Enforcement = "gated" | "external" | "reported";

export interface BudgetRow {
  id: string;
  kind: RowKind;
  label: string;
  budgetBytes: number;
  budgetLabel?: string;
  baselineBytes?: number | null;
  gate?: string;
  enforcement: Enforcement;
  enforcedBy?: string;
  definition?: string;
  route?: string;
  derivedFrom?: string[];
}

export interface BudgetsFile {
  source: string;
  method?: Record<string, unknown>;
  rows: BudgetRow[];
}

export interface MeasuredFile {
  file: string;
  bytes: number;
  rawBytes: number;
}

export interface Measurement {
  row: BudgetRow;
  files: MeasuredFile[];
  measuredBytes: number | null;
  notes: string[];
  fontsPresent?: boolean;
  derivedFrom?: string[];
}

export interface EvaluatedRow extends Measurement {
  budgetBytes: number;
  headroomBytes: number | null;
  baselineBytes: number | null;
  baselineDeltaBytes: number | null;
  baselineExact: boolean | null;
  status: "PASS" | "BREACH" | "EXTERNAL" | "REPORTED";
  breached: boolean;
}

export interface EvaluationResult {
  rows: EvaluatedRow[];
  breached: boolean;
}

export interface CrossCheck {
  route: string;
  checked: boolean;
  reason?: string;
  match?: boolean;
  onlyInHtml?: string[];
  onlyInManifest?: string[];
}

export declare function parseBudgetBytes(value: unknown, context?: string): number;
export declare function gzipBytes(buffer: Buffer | string): number;
export declare function gzipFileBytes(absPath: string): number;
export declare function formatBytes(bytes: number | null | undefined): string;
export declare function formatDelta(bytes: number | null | undefined): string;
export declare function loadBudgets(budgetsPath: string): BudgetsFile;
export declare function readClientReferenceManifest(file: string): Record<string, unknown>;
export declare function isOnRouteSegmentPath(modulePath: string, entryKey: string): boolean;
export declare function routeFirstLoadFiles(nextDir: string, route: string): string[];
export declare function sharedFirstLoadFiles(nextDir: string): string[];
export declare function emittedCssFiles(nextDir: string): string[];
export declare function selfHostedFontFiles(webDir: string): string[];
export declare function verifyAgainstPrerenderedHtml(
  nextDir: string,
  route: string,
  manifestFiles: string[],
): CrossCheck;
export declare function measure(input: { webDir: string; budgets: BudgetsFile }): {
  measurements: Measurement[];
  crossChecks: CrossCheck[];
};
export declare function evaluate(measurements: Measurement[]): EvaluationResult;
export declare function renderReport(input: {
  result: EvaluationResult;
  budgets: BudgetsFile;
  crossChecks: CrossCheck[];
  generatedAt: string;
  nextVersion: string;
}): string;
export declare function run(input: { webDir: string; now?: Date }): {
  result: EvaluationResult;
  report: string;
  reportPath: string;
};
