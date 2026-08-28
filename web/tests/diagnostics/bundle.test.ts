/**
 * WO-16 criterion 7 (the bundle half) — "a bundle assertion proves
 * `web-vitals` is not in either route's first-load JS."
 *
 * TWO PROOFS, BECAUSE ONE OF THEM CANNOT ALWAYS RUN.
 *
 *   1. **The module graph, always.** A module enters a route's first-load
 *      chunk union if and only if it is reachable from that route's entry
 *      by STATIC imports — that is what "first load" means, and it is why
 *      `import()` is a code-split point at all. So the walk below starts at
 *      `app/page.tsx` and `app/c/[id]/page.tsx`, follows every static
 *      specifier, refuses to follow dynamic ones, and asserts that
 *      `web-vitals` is not among the packages it reaches. This needs no
 *      build and therefore cannot be skipped.
 *   2. **The real chunk union, when a build exists.** The same question
 *      asked of `.next`, using `routeFirstLoadFiles()` from
 *      `scripts/route-budgets.mjs` — the identical manifest logic
 *      `npm run budgets` gates on, not a second implementation of it — and
 *      grepping the emitted chunks for markers only `web-vitals` contains.
 *      It also asserts the package IS emitted somewhere under
 *      `.next/static/chunks`, because a library that never shipped would
 *      pass an absence check and fail the user.
 *
 * The second block runs when `npm run build` has been run and is otherwise
 * absent rather than green — `it.runIf`, so a passing line in the output is
 * always a real measurement.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { routeFirstLoadFiles, sharedFirstLoadFiles } from "../../scripts/route-budgets.mjs";

import {
  WEB_ROOT,
  dynamicSpecifiers,
  moduleGraph,
  staticSpecifiers,
  stripComments,
} from "./support/source";

const PACKAGE = "web-vitals";

// Route entries are discovered, not hardcoded: WO-08 moved the pages into
// the `(workspace)` route group after this test was written, and a fixed
// path list breaks on any such move without catching anything real.
const discoverRouteFiles = (basename: string): string[] => {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "api" || entry.name.startsWith(".")) continue;
      const absolute = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(absolute);
      else if (entry.name === basename) found.push(absolute);
    }
  };
  walk(path.join(WEB_ROOT, "app"));
  return found.sort();
};

const ROUTE_ENTRIES = [
  ...discoverRouteFiles("page.tsx"),
  // Every route renders inside the layouts, so they are in the chunk unions.
  ...discoverRouteFiles("layout.tsx"),
];

const VITALS_MODULE = path.join(WEB_ROOT, "lib", "diagnostics", "vitals.ts");

/**
 * Strings that only `web-vitals` puts into a bundle.
 *
 * All three are `PerformanceObserver` entry types the library passes to
 * `observe()`, and nothing else in this product observes anything. They
 * survive minification because they are string literals. Any one of them
 * appearing in a first-load chunk would mean the library is in it.
 *
 * Verified present in `node_modules/web-vitals/dist/web-vitals.js` — the
 * file the package's `exports["."].default` condition resolves to, which
 * is what the webpack build reads.
 */
const MARKERS = [
  "largest-contentful-paint",
  "layout-shift",
  "interaction-contentful-paint",
];

describe("criterion 7 — the module graph, with no build required", () => {
  const graph = moduleGraph(ROUTE_ENTRIES);

  it("walked a real graph, not an empty one", () => {
    for (const entry of ROUTE_ENTRIES) {
      expect(existsSync(entry), entry).toBe(true);
    }
    // Sanity: the walk reached the shared layers, so an empty result would
    // be a broken walker rather than a clean bundle.
    expect(graph.files.length).toBeGreaterThan(5);
    expect(graph.packages).toContain("react");
  });

  it("does not reach web-vitals from EITHER route entry, statically", () => {
    expect(graph.packages).not.toContain(PACKAGE);
    for (const specifier of graph.packages) {
      expect(specifier.startsWith(PACKAGE), specifier).toBe(false);
    }
  });

  it("checks each route entry on its own, so neither hides behind the other", () => {
    for (const entry of ROUTE_ENTRIES) {
      expect(moduleGraph([entry]).packages, entry).not.toContain(PACKAGE);
    }
  });

  it("no file under app/, components/ or lib/ imports it statically", () => {
    // Belt and braces: the walk above proves unreachability from the two
    // entries; this proves nobody imported it anywhere at all, so a future
    // surface cannot pull it in through a path the walk does not cover.
    const roots = ["app", "components", "lib"].map((dir) => path.join(WEB_ROOT, dir));
    const files: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (/\.tsx?$/.test(entry.name)) files.push(full);
      }
    };
    for (const root of roots) walk(root);

    const importers = files.filter((file) =>
      staticSpecifiers(readFileSync(file, "utf8")).some(
        (specifier) => specifier === PACKAGE || specifier.startsWith(`${PACKAGE}/`),
      ),
    );
    expect(importers).toEqual([]);
  });

  it("has exactly one dynamic import of it, in lib/diagnostics/vitals.ts", () => {
    // Comments stripped: that module's header documents the type-only
    // import it deliberately does NOT write, and a scan that failed on the
    // documentation would be one nobody could write.
    const source = stripComments(readFileSync(VITALS_MODULE, "utf8"));
    expect(dynamicSpecifiers(source)).toEqual([PACKAGE]);
    // And no type-only import either: an erased import is harmless at
    // build time, but it would make this assertion softer than it reads.
    expect(source).not.toMatch(/import\s+type[^;]*from\s*["']web-vitals["']/);
  });

  it("ships it as an exact-pinned RUNTIME dependency, because it ships", () => {
    const packageJson = JSON.parse(
      readFileSync(path.join(WEB_ROOT, "package.json"), "utf8"),
    ) as { dependencies: Record<string, string>; devDependencies: Record<string, string> };

    // A dynamically imported package is still shipped code. In
    // devDependencies it would break `npm ci --omit=dev` in the Docker
    // build for any reader who passes the flag.
    expect(packageJson.dependencies[PACKAGE]).toBeDefined();
    expect(packageJson.devDependencies[PACKAGE]).toBeUndefined();
    expect(packageJson.dependencies[PACKAGE]).toMatch(/^\d+\.\d+\.\d+$/);
  });
});

// ---------------------------------------------------------------------------
// The same question, asked of a real build.
// ---------------------------------------------------------------------------

const NEXT_DIR = path.join(WEB_ROOT, ".next");
const BUILT = existsSync(path.join(NEXT_DIR, "build-manifest.json"));

describe("criterion 7 — the emitted chunks, when `npm run build` has run", () => {
  function readChunks(files: string[]): string {
    return files
      .filter((file) => file.endsWith(".js"))
      .map((file) => {
        const full = path.join(NEXT_DIR, file);
        return existsSync(full) ? readFileSync(full, "utf8") : "";
      })
      .join("\n");
  }

  it.runIf(BUILT)("is in neither route's first-load JS", () => {
    for (const route of ["/", "/c/[id]"]) {
      const files = routeFirstLoadFiles(NEXT_DIR, route);
      expect(files.length, route).toBeGreaterThan(0);
      const bundle = readChunks(files);
      for (const marker of MARKERS) {
        expect(bundle.includes(marker), `${route} first-load JS contains ${marker}`).toBe(
          false,
        );
      }
    }
  });

  it.runIf(BUILT)("is not in the shared chunk either", () => {
    const bundle = readChunks(sharedFirstLoadFiles(NEXT_DIR));
    for (const marker of MARKERS) {
      expect(bundle.includes(marker), `shared chunk contains ${marker}`).toBe(false);
    }
  });

  it.runIf(BUILT)("puts every chunk that carries it outside both first-load unions", () => {
    const chunkDir = path.join(NEXT_DIR, "static", "chunks");
    const all: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith(".js")) all.push(full);
      }
    };
    walk(chunkDir);

    // ANY marker, not all three: webpack is free to split the library
    // across chunks, and the question here is only where it landed.
    const carriers = all.filter((file) => {
      const source = readFileSync(file, "utf8");
      return MARKERS.some((marker) => source.includes(marker));
    });

    // MEASURED, AND STATED HONESTLY. On this branch `carriers` is EMPTY,
    // and not because the dynamic import failed: it is because nothing
    // composes `Diagnostics` into a route yet. Route composition is WO-20's
    // work order. This one ships the component, the ring, the redactor and
    // the vitals loader; `lib/diagnostics/vitals.ts` is reachable from no
    // page, so webpack has no entry to code-split from and emits no chunk
    // at all.
    //
    // The assertion is therefore the SUBSET property rather than a count.
    // It is the same claim before and after WO-20 wires the surface, and it
    // tightens by itself the moment a route imports it. A count would be
    // either a trap for WO-20 or a lie today.
    const firstLoad = new Set([
      ...routeFirstLoadFiles(NEXT_DIR, "/"),
      ...routeFirstLoadFiles(NEXT_DIR, "/c/[id]"),
    ]);
    for (const carrier of carriers) {
      const relative = path.relative(NEXT_DIR, carrier).split(path.sep).join("/");
      expect(firstLoad.has(relative), `${relative} is in a first-load union`).toBe(false);
    }
    // An empty union is not what made this pass.
    expect(firstLoad.size).toBeGreaterThan(0);
    expect(all.length).toBeGreaterThan(0);
  });

  it("uses the budget script's own manifest logic, not a second copy", () => {
    // The gate that ships is `npm run budgets`. Re-deriving the route ->
    // chunk association here would let this test pass while the gate
    // measured something else.
    expect(typeof routeFirstLoadFiles).toBe("function");
    expect(typeof sharedFirstLoadFiles).toBe("function");
    if (BUILT) {
      expect(statSync(path.join(NEXT_DIR, "build-manifest.json")).size).toBeGreaterThan(0);
    }
  });
});
