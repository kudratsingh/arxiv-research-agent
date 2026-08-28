/**
 * Source-text helpers shared by `bundle.test.ts` and `egress.test.ts`.
 *
 * Both files make claims about the MODULE GRAPH — "web-vitals is not
 * statically reachable from either route entry", "no client module calls
 * `sendBeacon`" — and both have to make them against real files rather than
 * against a build that may not exist when `npm run test` runs. So the two
 * primitives they share live here: a comment stripper and a static import
 * walker.
 *
 * COMMENTS ARE STRIPPED BEFORE ANY SCAN. The prohibitions being enforced
 * are on code, not on prose: `lib/diagnostics/vitals.ts` documents in its
 * header that it does not call `sendBeacon`, and a scanner that failed on
 * that sentence would be one nobody could write documentation around.
 *
 * The walker follows STATIC imports only, which is exactly the right
 * granularity for both claims: a static import is the only way a module
 * enters a route's first-load chunk union, and a dynamic `import()` is the
 * code-split point whose absence from that union is the thing being proved.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

export const WEB_ROOT = path.resolve(__dirname, "..", "..", "..");

const EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs"];

/** Block and line comments removed. String contents are left alone. */
export function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/(^|\s)\/\/.*$/gm, "$1");
}

/** Every `from "…"` specifier in a file, static imports and re-exports. */
export function staticSpecifiers(source: string): string[] {
  const stripped = stripComments(source);
  const out: string[] = [];
  for (const match of stripped.matchAll(/\bfrom\s*["']([^"']+)["']/g)) {
    out.push(match[1] as string);
  }
  // `import "./primitives.css";` — a side-effect import with no `from`.
  for (const match of stripped.matchAll(/\bimport\s*["']([^"']+)["']/g)) {
    out.push(match[1] as string);
  }
  return out;
}

/** Every `import("…")` specifier — the code-split points. */
export function dynamicSpecifiers(source: string): string[] {
  const stripped = stripComments(source);
  return [...stripped.matchAll(/\bimport\s*\(\s*["']([^"']+)["']\s*\)/g)].map(
    (match) => match[1] as string,
  );
}

/** Resolve a specifier to a file under `web/`, or `null` if it is a package. */
export function resolveSpecifier(fromFile: string, specifier: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) base = path.join(WEB_ROOT, specifier.slice(2));
  else if (specifier.startsWith(".")) base = path.resolve(path.dirname(fromFile), specifier);
  else return null;

  if (existsSync(base) && statSync(base).isFile()) return base;
  for (const extension of EXTENSIONS) {
    const candidate = `${base}${extension}`;
    if (existsSync(candidate)) return candidate;
  }
  for (const extension of EXTENSIONS) {
    const candidate = path.join(base, `index${extension}`);
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

export interface ModuleGraph {
  /** Every file reachable by STATIC imports from the entries. */
  files: string[];
  /** Bare package specifiers reached statically, deduplicated. */
  packages: string[];
  /** Bare package specifiers reached only through `import()`. */
  dynamicPackages: string[];
}

/** Walk static imports from a set of entry files. */
export function moduleGraph(entries: string[]): ModuleGraph {
  const seen = new Set<string>();
  const packages = new Set<string>();
  const dynamicPackages = new Set<string>();
  const queue = [...entries];

  while (queue.length > 0) {
    const file = queue.pop() as string;
    if (seen.has(file)) continue;
    seen.add(file);
    if (!/\.(?:tsx?|jsx?|mjs)$/.test(file)) continue;
    const source = readFileSync(file, "utf8");

    for (const specifier of staticSpecifiers(source)) {
      const resolved = resolveSpecifier(file, specifier);
      if (resolved === null) packages.add(specifier);
      else queue.push(resolved);
    }
    for (const specifier of dynamicSpecifiers(source)) {
      const resolved = resolveSpecifier(file, specifier);
      if (resolved === null) dynamicPackages.add(specifier);
      // A dynamically imported LOCAL module is a code-split point too, and
      // its own static imports belong to that chunk, not to the entry's.
      // It is deliberately not queued.
    }
  }

  return {
    files: [...seen].sort(),
    packages: [...packages].sort(),
    dynamicPackages: [...dynamicPackages].sort(),
  };
}

/** Every `.ts`/`.tsx` file under a directory, recursively. */
export function sourceFilesUnder(dir: string): string[] {
  const out: string[] = [];
  const walk = (current: string): void => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry.name)) out.push(full);
    }
  };
  walk(dir);
  return out.sort();
}
