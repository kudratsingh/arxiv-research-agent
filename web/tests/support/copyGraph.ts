/**
 * Which copy modules does a route group actually render? (WO-W14)
 *
 * The pedagogy gate in `tests/copy/forbidden.test.ts` has to hold for
 * **every** `(learn)` copy module, and the work order is explicit that it
 * must be designed over the module *set* rather than over a hard-coded list
 * of one. A list would be wrong within a work order: WO-W13's session
 * strings land in `lib/copy/learn.ts` and a future surface will add a file
 * nobody has named yet.
 *
 * So the set is DERIVED, from the only source that cannot lie about it —
 * the import graph. Starting at every file under `app/(learn)/`, this
 * module follows first-party imports (`@/…` and relative), resolves them
 * the way the bundler does, and reports every module under `lib/copy/` it
 * can reach. A copy module the learning routes render is in that set by
 * construction; one they do not render is not.
 *
 * WHY A REGEX AND NOT THE TYPESCRIPT COMPILER. The graph is only used to
 * decide which files to hold to a list of forbidden words, and the failure
 * mode of over-collecting is a stricter gate rather than a weaker one. The
 * pattern matches `from "…"`, `import("…")` and `export * from "…"`, which
 * is every shape this codebase uses; a `require` or a computed specifier
 * would be missed, and neither exists in `web/` (the ESLint config and
 * `tests/api.test.ts` both assume ES modules throughout). Bare package
 * specifiers are skipped: `node_modules` holds no copy of ours.
 *
 * `tests/copy/forbidden.test.ts` asserts that the walk finds a non-empty
 * set and that every module in it is in the gate's own table, so a walk
 * that silently stopped finding files fails the suite rather than quietly
 * gating nothing.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

/** `web/`. */
export const WEB_ROOT = path.resolve(__dirname, "..", "..");

/** Source extensions the walk resolves and follows. */
const EXTENSIONS = [".ts", ".tsx"];

/**
 * Every module specifier in a source file.
 *
 * `from "x"` covers static imports, `export … from "x"` and re-exports;
 * `import("x")` covers the dynamic ones (`react-markdown` is loaded that
 * way, and a copy module could be).
 */
const SPECIFIER = /(?:\bfrom\s*|\bimport\s*\(\s*)["']([^"']+)["']/g;

/** Resolve a specifier the way the `@` alias and Node's resolution do. */
export function resolveSpecifier(specifier: string, fromFile: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) base = path.join(WEB_ROOT, specifier.slice(2));
  else if (specifier.startsWith(".")) base = path.resolve(path.dirname(fromFile), specifier);
  else return null;

  const candidates = [
    base,
    ...EXTENSIONS.map((extension) => base + extension),
    ...EXTENSIONS.map((extension) => path.join(base, `index${extension}`)),
  ];
  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue;
    if (!statSync(candidate).isFile()) continue;
    if (!EXTENSIONS.includes(path.extname(candidate))) continue;
    return candidate;
  }
  return null;
}

/** Every `.ts`/`.tsx` file under `dir`, recursively. */
export function sourceFilesUnder(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir).sort()) {
    const absolute = path.join(dir, entry);
    if (statSync(absolute).isDirectory()) {
      found.push(...sourceFilesUnder(absolute));
      continue;
    }
    if (EXTENSIONS.includes(path.extname(absolute))) found.push(absolute);
  }
  return found;
}

/** Every first-party module reachable from `entries`, including them. */
export function reachableFrom(entries: readonly string[]): Set<string> {
  const seen = new Set<string>(entries);
  const queue = [...entries];
  while (queue.length > 0) {
    const file = queue.shift() as string;
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(SPECIFIER)) {
      const target = resolveSpecifier(match[1] as string, file);
      if (target === null || seen.has(target)) continue;
      seen.add(target);
      queue.push(target);
    }
  }
  return seen;
}

/**
 * The copy modules one route group renders, by module name.
 *
 * `routeGroup` is a directory under `app/`, parentheses and all —
 * `"(learn)"`. The names come back sorted and de-duplicated, spelled the
 * way the gate's table spells them (`lib/copy/ledger.ts` → `ledger`).
 */
export function copyModulesRenderedBy(routeGroup: string): string[] {
  const root = path.join(WEB_ROOT, "app", routeGroup);
  const copyDir = path.join(WEB_ROOT, "lib", "copy") + path.sep;
  const modules = [...reachableFrom(sourceFilesUnder(root))]
    .filter((file) => file.startsWith(copyDir))
    .map((file) => path.basename(file, path.extname(file)));
  return [...new Set(modules)].sort();
}
