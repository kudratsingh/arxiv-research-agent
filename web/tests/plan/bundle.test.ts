/**
 * WO-17 criterion 10 — React Hook Form is DYNAMICALLY imported and is not in
 * a route's first-load JavaScript (R-11, 04 §8.1) — and, since
 * `known-gaps.md` §19, Zod IS NOT IN THE CLIENT AT ALL.
 *
 * TWO CLAIMS, NOT ONE, BECAUSE THEY ARE NOT THE SAME STRENGTH.
 *
 *   * `react-hook-form` is BEHIND THE BOUNDARY. It ships, in the chunk
 *     `React.lazy(() => import("./PlanEditorFields"))` fetches, and the
 *     assertion is that no route reaches it without crossing that `import()`.
 *   * `zod` is ABSENT. `planResolver` replaced `buildPlanSchema` as the
 *     form's validator, so no shipped module imports the package in any way
 *     — not statically, not through an `import()` either — and its signature
 *     is in no emitted chunk. That is what took 296,426 B raw / 73,605 B gzip
 *     and a ~250 ms long task out of the plan-review state. The Zod schema
 *     survives as the unit test's differential oracle, in
 *     `tests/plan/schema.test.ts`, which is not shipped code and is outside
 *     `coverage.include`.
 *
 * TWO PROOFS, BECAUSE ONE OF THEM CANNOT ALWAYS RUN.
 *
 *   1. THE MODULE GRAPH (always). The graph is walked from the real route
 *      entrypoints and from `PlanEditor` itself with TypeScript's own parser
 *      — not a regular expression — following exactly the edges a bundler
 *      follows: static `import`/`export … from`, and side-effect imports.
 *      `import type` is not followed, because the compiler erases it, and
 *      `import()` is not followed, because that is the boundary being
 *      proved. If the package is not reachable that way, it cannot be in a
 *      first-load chunk.
 *
 *   2. THE BUILD MANIFESTS (when `.next` exists). `npm run build` writes the
 *      route → chunk association WO-23's script already knows how to read,
 *      so the same claim is re-checked against the bytes that actually ship.
 *      CI runs `npm run test` before `npm run build`, so this half is
 *      skipped there and is exercised locally and in the PR evidence; the
 *      graph proof above is the one that gates every run.
 *
 * PROOF 1 IS SELF-TESTED. A graph walk that silently resolved nothing would
 * pass vacuously, so the same walker is pointed at `PlanEditorFields` — the
 * module behind the boundary — and REQUIRED to find React Hook Form. Proof 2
 * is self-tested the same way: its signature must be found somewhere in the
 * build before its absence from the first load means anything. The absence
 * claim about Zod needs no such anchor and could not have one: it is
 * asserted against a build whose self-test — React Hook Form's signature —
 * proves the chunks were read.
 *
 * WHY THIS DOES NOT REUSE `tests/diagnostics/support/source.ts`. WO-16 ships
 * a module-graph walker for the same shape of claim about `web-vitals`, and
 * one walker for both would be the better arrangement — except that its
 * `staticSpecifiers()` matches `from "…"` textually, which cannot tell
 * `import type { Resolver } from "react-hook-form"` from a value import.
 * That distinction is not incidental here — it is more load-bearing than it
 * was: `lib/plan/schema.ts` is ON `/c/[id]`'s first-load path and names
 * React Hook Form's types, so type-only erasure is the only thing standing
 * between the library and the route's chunk union. A walker that could not
 * model it would fail this file for the wrong reason. Hence the TypeScript
 * parser below. The route-entry
 * DISCOVERY is shared in spirit and copied deliberately — see the note on
 * `discoverRouteFiles`.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

const WEB_ROOT = path.resolve(__dirname, "..", "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const NEXT_DIR = path.join(WEB_ROOT, ".next");

/** Ships, but only behind the `import()`. */
const DYNAMIC_ONLY = ["react-hook-form"] as const;

/** Does not ship at all. */
const ABSENT_FROM_CLIENT = ["zod"] as const;

/** Both packages WO-17 added, for the assertions about package.json. */
const WO17_PACKAGES = [...DYNAMIC_ONLY, ...ABSENT_FROM_CLIENT] as const;

// ---------------------------------------------------------------------------
// A module graph, walked the way a bundler walks it.
// ---------------------------------------------------------------------------

interface ModuleEdges {
  /** Specifiers a bundler would follow into the importing chunk. */
  statics: string[];
  /** Specifiers that open a NEW chunk. Never followed here. */
  dynamics: string[];
}

/**
 * Every import in one file, split by whether it survives compilation.
 *
 * `import type` and a clause whose every binding is `type` are both erased
 * by TypeScript, so neither is an edge. That is not a technicality here — it
 * is exactly how `lib/plan/schema.ts` names Zod's types without importing
 * Zod.
 */
function edgesOf(file: string): ModuleEdges {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.ESNext,
    true,
    ts.ScriptKind.TSX,
  );

  const statics: string[] = [];
  const dynamics: string[] = [];

  const specifierOf = (node: ts.Node | undefined): string | null =>
    node !== undefined && ts.isStringLiteral(node) ? node.text : null;

  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node)) {
      const clause = node.importClause;
      const typeOnly =
        clause?.isTypeOnly === true ||
        (clause?.namedBindings !== undefined &&
          ts.isNamedImports(clause.namedBindings) &&
          clause.namedBindings.elements.length > 0 &&
          clause.namedBindings.elements.every((element) => element.isTypeOnly));
      const specifier = specifierOf(node.moduleSpecifier);
      if (!typeOnly && specifier !== null) statics.push(specifier);
    } else if (ts.isExportDeclaration(node) && !node.isTypeOnly) {
      const specifier = specifierOf(node.moduleSpecifier);
      if (specifier !== null) statics.push(specifier);
    } else if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword
    ) {
      const specifier = specifierOf(node.arguments[0]);
      if (specifier !== null) dynamics.push(specifier);
    }
    ts.forEachChild(node, visit);
  };

  visit(source);
  return { statics, dynamics };
}

const EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs"];

/** A first-party specifier → a file on disk, or `null` for a package. */
function resolve(fromFile: string, specifier: string): string | null {
  const base = specifier.startsWith("@/")
    ? path.join(WEB_ROOT, specifier.slice(2))
    : specifier.startsWith(".")
      ? path.resolve(path.dirname(fromFile), specifier)
      : null;
  if (base === null) return null;

  const candidates = [
    base,
    ...EXTENSIONS.map((extension) => `${base}${extension}`),
    ...EXTENSIONS.map((extension) => path.join(base, `index${extension}`)),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

interface Reached {
  files: Set<string>;
  packages: Set<string>;
  /** `importer → specifier`, for a failure message that names the edge. */
  via: Map<string, string>;
}

/** Everything reachable from `roots` WITHOUT crossing an `import()`. */
function walk(roots: string[]): Reached {
  const files = new Set<string>();
  const packages = new Set<string>();
  const via = new Map<string, string>();
  const queue = [...roots];

  while (queue.length > 0) {
    const file = queue.pop() as string;
    if (files.has(file)) continue;
    files.add(file);
    if (!EXTENSIONS.some((extension) => file.endsWith(extension))) continue;

    for (const specifier of edgesOf(file).statics) {
      const resolved = resolve(file, specifier);
      if (resolved === null) {
        // A bare specifier. `@scope/name` keeps two segments; everything
        // else keeps one, so a deep import counts as its package.
        const parts = specifier.split("/");
        const name = specifier.startsWith("@")
          ? parts.slice(0, 2).join("/")
          : (parts[0] as string);
        packages.add(name);
        if (!via.has(name)) via.set(name, path.relative(WEB_ROOT, file));
        continue;
      }
      if (!files.has(resolved)) queue.push(resolved);
    }
  }

  return { files, packages, via };
}

/** Every shipped `.ts`/`.tsx` under a directory. Stories are harness, not ship. */
function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) sourceFiles(full, acc);
    else if (
      /\.tsx?$/.test(entry.name) &&
      !entry.name.endsWith(".d.ts") &&
      !entry.name.endsWith(".stories.tsx")
    ) {
      acc.push(full);
    }
  }
  return acc;
}

/**
 * The route entries, DISCOVERED rather than hardcoded.
 *
 * WO-08 moved the pages into an `app/(workspace)/` route group and WO-16's
 * own bundle test had to learn the same lesson: a fixed path list breaks on
 * a move without catching anything real, and — worse — a list that points at
 * files which no longer exist proves nothing while still going green if the
 * walker is forgiving. Every `page.tsx` and every `layout.tsx` under `app/`
 * is a root, because every route renders inside its layouts and all of them
 * are in that route's chunk union. `app/api/` is skipped: it is server code
 * and ships no client chunk.
 */
function discoverRouteFiles(basename: string): string[] {
  const found: string[] = [];
  const walkDir = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "api" || entry.name.startsWith(".")) continue;
      const absolute = path.join(dir, entry.name);
      if (entry.isDirectory()) walkDir(absolute);
      else if (entry.name === basename) found.push(absolute);
    }
  };
  walkDir(path.join(WEB_ROOT, "app"));
  return found.sort();
}

const ROUTE_ROOTS = [
  ...discoverRouteFiles("page.tsx"),
  ...discoverRouteFiles("layout.tsx"),
];

const PLAN_EDITOR = path.join(WEB_ROOT, "components", "patterns", "PlanEditor.tsx");
const PLAN_EDITOR_FIELDS = path.join(
  WEB_ROOT,
  "components",
  "patterns",
  "PlanEditorFields.tsx",
);

// ---------------------------------------------------------------------------
// Proof 1 — the module graph.
// ---------------------------------------------------------------------------

describe("criterion 10 — the walker itself works", () => {
  it("reaches real files from the real routes", () => {
    const reached = walk(ROUTE_ROOTS);
    expect(reached.files.size).toBeGreaterThan(5);
    // A sanity anchor: React is a static dependency of every route.
    expect(reached.packages.has("react")).toBe(true);
  });

  it("finds the form library when it is pointed behind the boundary", () => {
    // The self-test. If this ever stops finding it, the assertions below
    // are proving nothing.
    const reached = walk([PLAN_EDITOR_FIELDS]);
    for (const name of DYNAMIC_ONLY) {
      expect(reached.packages.has(name), `${name} is not reachable at all`).toBe(true);
    }
  });

  it("does not follow an import() — that is the boundary", () => {
    const edges = edgesOf(PLAN_EDITOR);
    expect(edges.dynamics).toContain("./PlanEditorFields");
    expect(edges.statics).not.toContain("./PlanEditorFields");
  });

  it("does not follow an import type — the compiler erases it", () => {
    // `lib/plan/schema.ts` is ON `/c/[id]`'s first-load path, because
    // `PlanEditor` imports it eagerly for `isEdited`, the bounds and the 422
    // mapping. It names React Hook Form's `Resolver` and `FieldErrors` in an
    // `import type` so that `planResolver` can be typed against the library
    // the lazy half uses without the library landing in the route's chunk
    // union — the same erasure that used to keep Zod out, now doing the job
    // that matters. If the `type` keyword ever goes, this fails.
    const schemaFile = path.join(WEB_ROOT, "lib", "plan", "schema.ts");
    const edges = edgesOf(schemaFile);
    expect(readFileSync(schemaFile, "utf8")).toContain(
      'import type { FieldErrors, Resolver } from "react-hook-form"',
    );
    expect(edges.statics).not.toContain("react-hook-form");
    expect(edges.dynamics).not.toContain("react-hook-form");
  });
});

describe("criterion 10 — the form library is not in a route's static graph", () => {
  const fromRoutes = walk(ROUTE_ROOTS);
  const fromPlanEditor = walk([PLAN_EDITOR]);

  it.each(DYNAMIC_ONLY)("%s is not reachable from `/` or `/c/[id]`", (name) => {
    expect(
      fromRoutes.packages.has(name),
      `${name} is statically imported by ${fromRoutes.via.get(name) ?? "?"}`,
    ).toBe(false);
  });

  it.each(DYNAMIC_ONLY)(
    "%s is not reachable from PlanEditor either — the surface WO-20 mounts",
    (name) => {
      expect(
        fromPlanEditor.packages.has(name),
        `${name} is statically imported by ${fromPlanEditor.via.get(name) ?? "?"}`,
      ).toBe(false);
    },
  );

  it("keeps the fields module itself out of the eager graph", () => {
    expect(fromPlanEditor.files.has(PLAN_EDITOR_FIELDS)).toBe(false);
    expect(fromRoutes.files.has(PLAN_EDITOR_FIELDS)).toBe(false);
  });

  it("has exactly one module in the product that imports it", () => {
    // Not "one module reachable from a root" — one module in the shipped
    // tree at all. A second importer anywhere in app/, components/ or lib/
    // is a second chance for a bundler to pull the package forward.
    expect(productImportersOf(DYNAMIC_ONLY)).toEqual([
      "components/patterns/PlanEditorFields.tsx",
    ]);
  });
});

describe("§19 — Zod is imported by nothing that ships", () => {
  it("is in no shipped module's static graph, in any of the three trees", () => {
    // The stronger claim, and the one this file exists to keep true: not
    // "behind a boundary" but "not there". `planResolver` is the validator
    // now, so a static import would be a regression of 73,605 B gzip.
    expect(productImportersOf(ABSENT_FROM_CLIENT)).toEqual([]);
  });

  it("is in no shipped module's DYNAMIC graph either", () => {
    // The half the `DYNAMIC_ONLY` assertions above deliberately do not make.
    // An `import("zod")` would move the cost to the first submit rather than
    // remove it, and the walker would not see it as a static edge.
    const dynamicImporters = ["app", "components", "lib"]
      .flatMap((dir) => sourceFiles(path.join(WEB_ROOT, dir)))
      .filter((file) =>
        edgesOf(file).dynamics.some((specifier) =>
          ABSENT_FROM_CLIENT.some(
            (name) => specifier === name || specifier.startsWith(`${name}/`),
          ),
        ),
      )
      .map((file) => path.relative(WEB_ROOT, file))
      .sort();

    expect(dynamicImporters).toEqual([]);
  });

  it("still builds the oracle, in the one place that is allowed to", () => {
    // The counterweight, and the reason the absence above is safe to assert.
    // The removal rests on `planResolver` and the Zod schema agreeing case
    // for case; that comparison has to keep running, so the schema has to
    // keep existing — in a test file, which is not shipped code, is not
    // walked above, and is outside `coverage.include`.
    const testFile = path.join(WEB_ROOT, "tests", "plan", "schema.test.ts");
    const source = readFileSync(testFile, "utf8");
    expect(edgesOf(testFile).statics).toContain("zod");
    expect(source).toContain("function buildPlanSchema()");
    expect(source).toContain("planResolver(values, undefined, RESOLVER_OPTIONS)");
  });
});

/**
 * Every module under `app/`, `components/` and `lib/` that names one of
 * `names` in a static import, relative to `web/` and sorted.
 */
function productImportersOf(names: readonly string[]): string[] {
  return ["app", "components", "lib"]
    .flatMap((dir) => sourceFiles(path.join(WEB_ROOT, dir)))
    .filter((file) =>
      edgesOf(file).statics.some((specifier) =>
        names.some((name) => specifier === name || specifier.startsWith(`${name}/`)),
      ),
    )
    .map((file) => path.relative(WEB_ROOT, file))
    .sort();
}

// ---------------------------------------------------------------------------
// Proof 2 — the build manifests, when there is a build.
// ---------------------------------------------------------------------------

/**
 * Signatures that survive minification, because they are string literals or
 * object keys rather than identifiers.
 *
 * `shouldUnregister` is a React Hook Form option key, asserted to exist
 * SOMEWHERE in the build before its absence from the first load is read as
 * evidence. `$ZodString` is one of Zod 4's `$constructor()` names, and it is
 * the opposite kind of check: it must be in NO chunk. The second name is
 * `"custom"`-free on purpose — a short or common string would go green on a
 * coincidence.
 */
const SIGNATURES: Record<(typeof DYNAMIC_ONLY)[number], string> = {
  "react-hook-form": "shouldUnregister",
};

/** Zod 4's `$constructor()` names, none of which may appear in a chunk. */
const ZOD_SIGNATURES = ["$ZodString", "$ZodArray", "$ZodObject"] as const;

/**
 * `data-surface="plan-editor"`, which only `PlanEditor.tsx` emits.
 *
 * The manifest half is meaningless until the surface is actually reachable
 * from a route: with nothing importing `PlanEditor`, webpack emits neither
 * its chunk nor the lazy one behind it, and "React Hook Form is not in the
 * first load" would be true for the same reason that "React Hook Form is
 * nowhere" is. WO-20 mounts the surface; from that commit on, this block
 * runs itself. Until then the module-graph proof above is the gate, and this
 * PR records the manifest numbers from a throwaway composition in its body.
 */
const SURFACE_MARKER = "plan-editor";

const built = existsSync(path.join(NEXT_DIR, "build-manifest.json"));
const surfaceInBuild =
  built &&
  allChunkFiles().some((file) => readFileSync(file, "utf8").includes(SURFACE_MARKER));

describe.skipIf(!surfaceInBuild)("criterion 10 — and again, in the build", () => {
  it("finds the form library's signature somewhere in the emitted chunks", async () => {
    const chunks = allChunkFiles();
    expect(chunks.length).toBeGreaterThan(0);
    for (const [name, signature] of Object.entries(SIGNATURES)) {
      const hit = chunks.some((file) => readFileSync(file, "utf8").includes(signature));
      expect(hit, `${name}: "${signature}" is in no chunk at all`).toBe(true);
    }
  });

  it.each(["/", "/c/[id]"])(
    "%s first-load JS contains no form library",
    async (route) => {
      const budgets = await import("../../scripts/route-budgets.mjs");
      const files = budgets.routeFirstLoadFiles(NEXT_DIR, route);
      expect(files.length).toBeGreaterThan(0);
      const text = files
        .map((file: string) => readFileSync(path.join(NEXT_DIR, file), "utf8"))
        .join("\n");
      for (const [name, signature] of Object.entries(SIGNATURES)) {
        expect(text.includes(signature), `${name} is in ${route}'s first load`).toBe(
          false,
        );
      }
    },
  );

  it("the shared chunk contains no form library", async () => {
    const budgets = await import("../../scripts/route-budgets.mjs");
    const files = budgets.sharedFirstLoadFiles(NEXT_DIR);
    const text = files
      .map((file: string) => readFileSync(path.join(NEXT_DIR, file), "utf8"))
      .join("\n");
    for (const [name, signature] of Object.entries(SIGNATURES)) {
      expect(text.includes(signature), `${name} is in the shared chunk`).toBe(false);
    }
  });

  it("§19 — Zod is in no emitted chunk at all, first-load or lazy", () => {
    // The saving, checked against the bytes rather than against the import
    // graph: every `.js` under `.next/static/chunks`, which is the lazy
    // plan-editor chunk as well as every route's first load.
    const chunks = allChunkFiles();
    expect(chunks.length).toBeGreaterThan(0);
    const carrying = chunks
      .filter((file) => {
        const text = readFileSync(file, "utf8");
        return ZOD_SIGNATURES.some((signature) => text.includes(signature));
      })
      .map((file) => path.relative(NEXT_DIR, file))
      .sort();

    expect(carrying).toEqual([]);
  });
});

function allChunkFiles(): string[] {
  const root = path.join(NEXT_DIR, "static", "chunks");
  if (!existsSync(root)) return [];
  const out: string[] = [];
  const walkDir = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walkDir(full);
      else if (entry.name.endsWith(".js")) out.push(full);
    }
  };
  walkDir(root);
  return out;
}

// ---------------------------------------------------------------------------
// The dependencies themselves.
// ---------------------------------------------------------------------------

interface PackageJson {
  dependencies: Record<string, string>;
  devDependencies: Record<string, string>;
}

const pkg = JSON.parse(
  readFileSync(path.join(WEB_ROOT, "package.json"), "utf8"),
) as PackageJson;

describe("the two dependencies WO-17 adds", () => {
  it("ships React Hook Form at the version 04 §4.4 names, exactly pinned", () => {
    expect(pkg.dependencies["react-hook-form"]).toBe("7.86.0");
  });

  it("ships Zod at WO-04's pin, exactly", () => {
    expect(pkg.dependencies["zod"]).toBe("4.4.3");
  });

  it("keeps both listed, and NEITHER LISTING IS A CLAIM THAT IT SHIPS", () => {
    // React Hook Form is a runtime dependency because the lazy chunk imports
    // it. Zod's entries stay for three reasons that all outlive §19's
    // removal, and none of which is "a browser downloads it":
    //   * `tests/contract/**` parses the recorded fixtures with it;
    //   * `lib/plan/schema.ts` names its types in an `import type`, which
    //     `npm run typecheck` and `next build` both have to resolve;
    //   * `tests/plan/schema.test.ts` builds the oracle from it.
    // The assertion that it reaches no chunk is above, in the build half —
    // this one only says the package is installed.
    for (const name of WO17_PACKAGES) {
      expect(Object.hasOwn(pkg.dependencies, name), `${name} is not a dependency`).toBe(
        true,
      );
    }
  });

  it("keeps Zod's devDependency entry too, and says why", () => {
    // WO-04's `tests/contract/generatedTypes.test.ts` asserts an exact pin in
    // `devDependencies` because the fixture parse tests depend on the
    // validator's behaviour being reproducible. That test is not this work
    // order's to edit, so the entry stays and is pinned to the same version
    // as the runtime one. The duplication is deliberate; the two must match.
    expect(pkg.devDependencies["zod"]).toBe(pkg.dependencies["zod"]);
  });

  it("is never installed production-only, so the duplicate listing cannot bite", () => {
    // npm marks a package that appears in BOTH lists as `dev` in the
    // lockfile, so a `--omit=dev` install would drop Zod — and the web image
    // BUILDS with it, because the `import type` has to resolve. Nothing in
    // this repository does such an install: the web image runs `npm ci
    // --ignore-scripts` and CI runs `npm ci`. This test is what keeps that
    // true rather than remembered.
    const installers = [
      readFileSync(path.join(WEB_ROOT, "Dockerfile"), "utf8"),
      readFileSync(path.join(REPO_ROOT, ".github", "workflows", "ci.yml"), "utf8"),
    ].join("\n");
    expect(installers).not.toMatch(/npm (?:ci|install|i)\b[^\n]*--omit[= ]dev/);
    expect(installers).not.toMatch(/npm (?:ci|install|i)\b[^\n]*--production/);
  });

  it("resolves both in the lockfile at those versions", () => {
    const lock = JSON.parse(
      readFileSync(path.join(WEB_ROOT, "package-lock.json"), "utf8"),
    ) as { packages: Record<string, { version?: string }> };
    expect(lock.packages["node_modules/react-hook-form"]?.version).toBe("7.86.0");
    expect(lock.packages["node_modules/zod"]?.version).toBe("4.4.3");
  });
});
