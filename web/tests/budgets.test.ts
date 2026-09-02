/**
 * Tests for the route budget check (WO-23).
 *
 * The build-dependent behaviour is exercised against synthetic fixture
 * manifests written to a temp directory, so the suite runs without `.next`
 * present and is independent of whatever the real build currently weighs.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  GZIP_LEVEL,
  emittedCssFiles,
  evaluate,
  formatBytes,
  formatDelta,
  gzipBytes,
  isOnRouteSegmentPath,
  loadBudgets,
  measure,
  parseBudgetBytes,
  renderReport,
  routeFirstLoadFiles,
  run,
  selfHostedFontFiles,
  sharedFirstLoadFiles,
  verifyAgainstPrerenderedHtml,
  type BudgetRow,
  type BudgetsFile,
} from "../scripts/route-budgets.mjs";

const WEB_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT_PATH = path.join(WEB_DIR, "scripts", "route-budgets.mjs");
const BUDGETS_PATH = path.join(WEB_DIR, "budgets.json");

// ---------------------------------------------------------------------------
// Fixture build
// ---------------------------------------------------------------------------

/** Deterministic filler that compresses predictably. */
function filler(seed: string, length: number): string {
  let out = "";
  while (out.length < length) out += `${seed}${out.length};`;
  return out.slice(0, length);
}

function write(file: string, contents: string): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, contents, "utf8");
}

interface Fixture {
  root: string;
  nextDir: string;
}

/**
 * A miniature Next 16 webpack build: the two manifests the script reads, the
 * client-reference manifests that replaced the deleted `app-build-manifest.json`,
 * the emitted chunks, one stylesheet, and the prerendered HTML for `/`.
 *
 * It deliberately reproduces the two traps in a real build: `/c/[id]`'s
 * client-reference manifest also lists `/`'s page module, and the root layout's
 * only client module is a stylesheet whose JS stub is never in the script set.
 */
function makeFixture(options: { fonts?: Array<{ rel: string; size: number }> } = {}): Fixture {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wo23-budgets-"));
  const nextDir = path.join(root, ".next");

  const chunks: Record<string, string> = {
    "static/chunks/webpack-1111111111111111.js": filler("webpack", 2_000),
    "static/chunks/4bd1b696-2222222222222222.js": filler("framework", 40_000),
    "static/chunks/794-3333333333333333.js": filler("nextruntime", 30_000),
    "static/chunks/main-app-4444444444444444.js": filler("mainapp", 400),
    "static/chunks/polyfills-5555555555555555.js": filler("polyfill", 90_000),
    "static/chunks/756-6666666666666666.js": filler("sharedvendor", 6_000),
    "static/chunks/454-7777777777777777.js": filler("markdown", 100_000),
    "static/chunks/app/page-8888888888888888.js": filler("homepage", 5_000),
    "static/chunks/app/layout-9999999999999999.js": filler("layoutstub", 190),
    "static/chunks/app/c/[id]/page-aaaaaaaaaaaaaaaa.js": filler("convpage", 20_000),
  };
  for (const [rel, body] of Object.entries(chunks)) write(path.join(nextDir, rel), body);
  write(path.join(nextDir, "static/css/bbbbbbbbbbbbbbbb.css"), filler(".a{color:red}", 15_000));

  write(
    path.join(nextDir, "build-manifest.json"),
    JSON.stringify({
      polyfillFiles: ["static/chunks/polyfills-5555555555555555.js"],
      devFiles: [],
      lowPriorityFiles: [],
      rootMainFiles: [
        "static/chunks/webpack-1111111111111111.js",
        "static/chunks/4bd1b696-2222222222222222.js",
        "static/chunks/794-3333333333333333.js",
        "static/chunks/main-app-4444444444444444.js",
      ],
      rootMainFilesTree: {},
      pages: { "/_app": [] },
    }),
  );

  write(
    path.join(nextDir, "app-path-routes-manifest.json"),
    JSON.stringify({
      "/page": "/",
      "/c/[id]/page": "/c/[id]",
      "/learn/page": "/learn",
      "/learn/paths/[id]/page": "/learn/paths/[id]",
      "/learn/progress/page": "/learn/progress",
      "/learn/sessions/[id]/page": "/learn/sessions/[id]",
      "/api/[...path]/route": "/api/[...path]",
    }),
  );

  const homeModules = {
    [`${root}/app/page.tsx#`]: {
      chunks: ["756", "static/chunks/756-6666666666666666.js", "974", "static/chunks/app/page-8888888888888888.js"],
    },
    [`${root}/app/globals.css`]: {
      chunks: ["177", "static/chunks/app/layout-9999999999999999.js"],
    },
    [`${root}/node_modules/next/dist/client/components/layout-router.js`]: { chunks: [] },
  };
  // The real Next 16 manifest for `/c/[id]` also carries `/`'s page module.
  const convModules = {
    ...homeModules,
    [`${root}/app/c/[id]/page.tsx#default`]: {
      chunks: [
        "756",
        "static/chunks/756-6666666666666666.js",
        "454",
        "static/chunks/454-7777777777777777.js",
        "378",
        "static/chunks/app/c/%5Bid%5D/page-aaaaaaaaaaaaaaaa.js",
      ],
    },
  };

  write(
    path.join(nextDir, "server/app/page_client-reference-manifest.js"),
    `globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});globalThis.__RSC_MANIFEST["/page"]=${JSON.stringify(
      { clientModules: homeModules, entryCSSFiles: {} },
    )};`,
  );
  write(
    path.join(nextDir, "server/app/c/[id]/page_client-reference-manifest.js"),
    `globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});globalThis.__RSC_MANIFEST["/c/[id]/page"]=${JSON.stringify(
      { clientModules: convModules, entryCSSFiles: {} },
    )};`,
  );
  write(
    path.join(nextDir, "server/app/learn/page_client-reference-manifest.js"),
    `globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});globalThis.__RSC_MANIFEST["/learn/page"]=${JSON.stringify(
      { clientModules: homeModules, entryCSSFiles: {} },
    )};`,
  );
  write(
    path.join(nextDir, "server/app/learn/paths/[id]/page_client-reference-manifest.js"),
    `globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});globalThis.__RSC_MANIFEST["/learn/paths/[id]/page"]=${JSON.stringify(
      { clientModules: convModules, entryCSSFiles: {} },
    )};`,
  );
  // WO-W13. The session route composes `ReportReader`'s document surface, so
  // in the real build its module set is the conversation route's shape rather
  // than the landing page's — which is also why its ceiling is seeded just
  // under `/c/[id]`'s. The fixture mirrors that.
  write(
    path.join(nextDir, "server/app/learn/sessions/[id]/page_client-reference-manifest.js"),
    `globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});globalThis.__RSC_MANIFEST["/learn/sessions/[id]/page"]=${JSON.stringify(
      { clientModules: convModules, entryCSSFiles: {} },
    )};`,
  );

  write(
    path.join(nextDir, "server/app/learn/progress/page_client-reference-manifest.js"),
    `globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});globalThis.__RSC_MANIFEST["/learn/progress/page"]=${JSON.stringify(
      { clientModules: homeModules, entryCSSFiles: {} },
    )};`,
  );

  write(
    path.join(nextDir, "server/app/index.html"),
    [
      '<link rel="stylesheet" href="/_next/static/css/bbbbbbbbbbbbbbbb.css"/>',
      '<link rel="preload" as="script" href="/_next/static/chunks/webpack-1111111111111111.js"/>',
      '<script src="/_next/static/chunks/4bd1b696-2222222222222222.js" async=""></script>',
      '<script src="/_next/static/chunks/794-3333333333333333.js" async=""></script>',
      '<script src="/_next/static/chunks/main-app-4444444444444444.js" async=""></script>',
      '<script src="/_next/static/chunks/756-6666666666666666.js" async=""></script>',
      '<script src="/_next/static/chunks/app/page-8888888888888888.js" async=""></script>',
      '<script src="/_next/static/chunks/polyfills-5555555555555555.js" noModule=""></script>',
      '<script src="/_next/static/chunks/webpack-1111111111111111.js" id="_R_" async=""></script>',
    ].join("\n"),
  );

  for (const font of options.fonts ?? []) {
    const abs = path.join(root, font.rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, Buffer.alloc(font.size, 7));
  }

  return { root, nextDir };
}

function fixtureBudgets(overrides: Partial<Record<string, number>> = {}): BudgetsFile {
  const rows: BudgetRow[] = [
    {
      id: "route-js-home",
      kind: "route-first-load-js",
      route: "/",
      label: "`/` first-load JS, excl. polyfill",
      budgetBytes: overrides["route-js-home"] ?? 5_000_000,
      baselineBytes: 1,
      enforcement: "gated",
    },
    {
      id: "route-js-conversation",
      kind: "route-first-load-js",
      route: "/c/[id]",
      label: "`/c/[id]` first-load JS, excl. polyfill",
      budgetBytes: overrides["route-js-conversation"] ?? 5_000_000,
      enforcement: "gated",
    },
    {
      id: "shared-framework-runtime",
      kind: "shared-first-load-js",
      label: "Shared framework/runtime chunk",
      budgetBytes: overrides["shared-framework-runtime"] ?? 5_000_000,
      enforcement: "gated",
    },
    {
      id: "emitted-css",
      kind: "emitted-css",
      label: "All emitted CSS",
      budgetBytes: overrides["emitted-css"] ?? 5_000_000,
      enforcement: "gated",
    },
    {
      id: "self-hosted-fonts",
      kind: "self-hosted-fonts",
      label: "All self-hosted font files (woff2, latin subset)",
      budgetBytes: overrides["self-hosted-fonts"] ?? 5_000_000,
      enforcement: "gated",
    },
    {
      id: "total-transferred-js",
      kind: "external-total-transferred-js",
      label: "Total transferred JS on a settled report route, incl. lazy chunks",
      budgetBytes: 245_760,
      enforcement: "external",
      enforcedBy: "WO-21 -- Playwright network-transfer assertion",
    },
    {
      id: "derived-total-first-load",
      kind: "derived-total-first-load",
      label: "Derived: total first-load transfer for `/c/[id]`, cold cache",
      budgetBytes: 334_848,
      enforcement: "reported",
      derivedFrom: ["route-js-conversation", "emitted-css", "self-hosted-fonts"],
    },
  ];
  return { source: "fixture", rows };
}

function gzipOf(fixture: Fixture, rel: string): number {
  return gzipBytes(fs.readFileSync(path.join(fixture.nextDir, rel)));
}

let fixture: Fixture;

beforeEach(() => {
  fixture = makeFixture();
});

afterEach(() => {
  fs.rmSync(fixture.root, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------

describe("byte parsing (criterion 2: budgets are bytes, not KB strings)", () => {
  it("accepts non-negative integers", () => {
    expect(parseBudgetBytes(0)).toBe(0);
    expect(parseBudgetBytes(148_480)).toBe(148_480);
  });

  it.each([["145 KiB"], ["145 KB"], ["148480"], [148_480.5], [-1], [null], [undefined], [{}]])(
    "rejects %o",
    (value) => {
      expect(() => parseBudgetBytes(value as unknown)).toThrow(/integer number of BYTES/);
    },
  );

  it("names the offending row in the error", () => {
    expect(() => parseBudgetBytes("12 KB", 'row "emitted-css"')).toThrow(/row "emitted-css"/);
  });

  it("gzips at zlib level 6, the level that reproduces the retained baseline", () => {
    expect(GZIP_LEVEL).toBe(6);
    const sample = Buffer.from(filler("sample", 50_000));
    expect(gzipBytes(sample)).toBe(zlib.gzipSync(sample, { level: 6 }).length);
    expect(gzipBytes(sample)).not.toBe(zlib.gzipSync(sample, { level: 9 }).length);
  });

  it("formats bytes and deltas with an explicit KiB conversion", () => {
    expect(formatBytes(137_272)).toBe("137,272 B (134.1 KiB)");
    expect(formatBytes(null)).toBe("—");
    expect(formatDelta(11_208)).toBe("+11,208 B");
    expect(formatDelta(-7_985)).toBe("−7,985 B");
    expect(formatDelta(0)).toBe("±0 B");
  });
});

describe("route -> chunk association from the fixture manifests", () => {
  it("unions rootMainFiles with the entry's own client chunks and drops polyfills", () => {
    expect(routeFirstLoadFiles(fixture.nextDir, "/")).toEqual([
      "static/chunks/4bd1b696-2222222222222222.js",
      "static/chunks/756-6666666666666666.js",
      "static/chunks/794-3333333333333333.js",
      "static/chunks/app/page-8888888888888888.js",
      "static/chunks/main-app-4444444444444444.js",
      "static/chunks/webpack-1111111111111111.js",
    ]);
  });

  it("decodes percent-encoded dynamic segments and excludes the other route's page chunk", () => {
    const files = routeFirstLoadFiles(fixture.nextDir, "/c/[id]");
    expect(files).toContain("static/chunks/app/c/[id]/page-aaaaaaaaaaaaaaaa.js");
    expect(files).toContain("static/chunks/454-7777777777777777.js");
    expect(files).not.toContain("static/chunks/app/page-8888888888888888.js");
    expect(files).not.toContain("static/chunks/polyfills-5555555555555555.js");
  });

  it("excludes the layout chunk contributed only by a stylesheet module", () => {
    // Its sole client module is app/globals.css; Next links the stylesheet and
    // never loads the JS stub, so it is not first-load JS on any route.
    for (const route of ["/", "/c/[id]"]) {
      expect(routeFirstLoadFiles(fixture.nextDir, route)).not.toContain(
        "static/chunks/app/layout-9999999999999999.js",
      );
    }
  });

  it("keeps client modules outside app/ but scopes app/ modules to the route's own path", () => {
    expect(isOnRouteSegmentPath("components/QueryForm.tsx", "/c/[id]/page")).toBe(true);
    expect(isOnRouteSegmentPath("app/c/[id]/page.tsx", "/c/[id]/page")).toBe(true);
    expect(isOnRouteSegmentPath("app/layout.tsx", "/c/[id]/page")).toBe(true);
    expect(isOnRouteSegmentPath("app/page.tsx", "/c/[id]/page")).toBe(false);
    expect(isOnRouteSegmentPath("app/other/page.tsx", "/page")).toBe(false);
  });

  it("fails loudly on an unknown route rather than reporting zero", () => {
    expect(() => routeFirstLoadFiles(fixture.nextDir, "/nope")).toThrow(
      /not in \.next\/app-path-routes-manifest\.json/,
    );
  });

  it("treats rootMainFiles minus polyfills as the shared framework/runtime set", () => {
    expect(sharedFirstLoadFiles(fixture.nextDir)).toEqual([
      "static/chunks/4bd1b696-2222222222222222.js",
      "static/chunks/794-3333333333333333.js",
      "static/chunks/main-app-4444444444444444.js",
      "static/chunks/webpack-1111111111111111.js",
    ]);
  });

  it("collects every emitted stylesheet", () => {
    expect(emittedCssFiles(fixture.nextDir)).toEqual(["static/css/bbbbbbbbbbbbbbbb.css"]);
  });

  it("cross-checks the manifest union against the prerendered <script src> set", () => {
    const files = routeFirstLoadFiles(fixture.nextDir, "/");
    const check = verifyAgainstPrerenderedHtml(fixture.nextDir, "/", files);
    expect(check).toMatchObject({ checked: true, match: true });

    const skipped = verifyAgainstPrerenderedHtml(fixture.nextDir, "/c/[id]", []);
    expect(skipped).toMatchObject({ checked: false });

    const mismatch = verifyAgainstPrerenderedHtml(fixture.nextDir, "/", [
      ...files,
      "static/chunks/454-7777777777777777.js",
    ]);
    expect(mismatch.match).toBe(false);
    expect(mismatch.onlyInManifest).toEqual(["static/chunks/454-7777777777777777.js"]);
  });
});

describe("font row (criterion 3: measured from woff2 files, not the JS manifests)", () => {
  it("reports zero and no files when WO-02's faces have not landed", () => {
    expect(selfHostedFontFiles(fixture.root)).toEqual([]);
    const { measurements } = measure({ webDir: fixture.root, budgets: fixtureBudgets() });
    const fonts = measurements.find((m) => m.row.id === "self-hosted-fonts");
    expect(fonts?.measuredBytes).toBe(0);
    expect(fonts?.fontsPresent).toBe(false);
    expect(fonts?.notes.join(" ")).toMatch(/WO-02 has not landed/);
  });

  it("sums raw woff2 bytes from both emission paths once faces exist", () => {
    fs.rmSync(fixture.root, { recursive: true, force: true });
    fixture = makeFixture({
      fonts: [
        { rel: ".next/static/media/literata-400.woff2", size: 17_000 },
        { rel: "public/fonts/atkinson-400.woff2", size: 13_000 },
        { rel: "public/fonts/not-a-font.txt", size: 999 },
      ],
    });
    expect(selfHostedFontFiles(fixture.root)).toHaveLength(2);
    const { measurements } = measure({ webDir: fixture.root, budgets: fixtureBudgets() });
    const fonts = measurements.find((m) => m.row.id === "self-hosted-fonts");
    // Raw bytes, not gzipped: woff2 is already Brotli-compressed internally.
    expect(fonts?.measuredBytes).toBe(30_000);
    expect(fonts?.fontsPresent).toBe(true);
  });
});

describe("breach detection", () => {
  function evaluateFixture(overrides: Partial<Record<string, number>> = {}) {
    const budgets = fixtureBudgets(overrides);
    const { measurements } = measure({ webDir: fixture.root, budgets });
    return { budgets, result: evaluate(measurements) };
  }

  it("passes when every gated row is under its ceiling", () => {
    const { result } = evaluateFixture();
    expect(result.breached).toBe(false);
    expect(result.rows.filter((r) => r.status === "BREACH")).toHaveLength(0);
  });

  it("breaches when a gated row exceeds its ceiling, and names the row", () => {
    const measuredCss = gzipOf(fixture, "static/css/bbbbbbbbbbbbbbbb.css");
    const { result } = evaluateFixture({ "emitted-css": measuredCss - 1 });
    expect(result.breached).toBe(true);
    const css = result.rows.find((r) => r.row.id === "emitted-css");
    expect(css?.status).toBe("BREACH");
    expect(css?.breached).toBe(true);
    expect(css?.headroomBytes).toBe(-1);
  });

  it("treats the ceiling as inclusive: measured == budget passes", () => {
    const measuredCss = gzipOf(fixture, "static/css/bbbbbbbbbbbbbbbb.css");
    const { result } = evaluateFixture({ "emitted-css": measuredCss });
    expect(result.breached).toBe(false);
    expect(result.rows.find((r) => r.row.id === "emitted-css")?.headroomBytes).toBe(0);
  });

  it("never breaches on the externally enforced or reported-only rows", () => {
    const { result } = evaluateFixture({});
    const external = result.rows.find((r) => r.row.id === "total-transferred-js");
    expect(external?.status).toBe("EXTERNAL");
    expect(external?.measuredBytes).toBeNull();
    expect(external?.breached).toBe(false);

    const derived = result.rows.find((r) => r.row.id === "derived-total-first-load");
    expect(derived?.status).toBe("REPORTED");
    expect(derived?.breached).toBe(false);
  });

  it("even when a reported-only row exceeds its reference ceiling", () => {
    const budgets = fixtureBudgets();
    const derivedRow = budgets.rows.find((r) => r.id === "derived-total-first-load");
    if (derivedRow) derivedRow.budgetBytes = 1;
    const { measurements } = measure({ webDir: fixture.root, budgets });
    const result = evaluate(measurements);
    expect(result.breached).toBe(false);
    expect(result.rows.find((r) => r.row.id === "derived-total-first-load")?.status).toBe(
      "REPORTED",
    );
  });

  it("derives the total first-load row from JS + CSS + fonts", () => {
    const { result } = evaluateFixture();
    const byId = new Map(result.rows.map((r) => [r.row.id, r]));
    const expected =
      (byId.get("route-js-conversation")?.measuredBytes ?? 0) +
      (byId.get("emitted-css")?.measuredBytes ?? 0) +
      (byId.get("self-hosted-fonts")?.measuredBytes ?? 0);
    expect(byId.get("derived-total-first-load")?.measuredBytes).toBe(expected);
  });

  it("reports the delta from the retained baseline", () => {
    const { result } = evaluateFixture();
    const home = result.rows.find((r) => r.row.id === "route-js-home");
    expect(home?.baselineBytes).toBe(1);
    expect(home?.baselineDeltaBytes).toBe((home?.measuredBytes ?? 0) - 1);
    expect(home?.baselineExact).toBe(false);
  });
});

describe("report format", () => {
  function report(overrides: Partial<Record<string, number>> = {}): string {
    const budgets = fixtureBudgets(overrides);
    const { measurements, crossChecks } = measure({ webDir: fixture.root, budgets });
    return renderReport({
      result: evaluate(measurements),
      budgets,
      crossChecks,
      generatedAt: "2026-08-28T00:00:00.000Z",
      nextVersion: "16.3.3",
    });
  }

  it("is a Markdown document with a gated table carrying budget, headroom and baseline delta", () => {
    const md = report();
    expect(md.startsWith("# Route budget report")).toBe(true);
    expect(md).toContain("## Gated rows");
    expect(md).toContain(
      "| Row | Measured | Budget | Headroom | Retained baseline | Δ baseline | Status |",
    );
    expect(md).toContain("`/` first-load JS, excl. polyfill");
    expect(md).toContain("`/c/[id]` first-load JS, excl. polyfill");
  });

  it("marks the 240 KiB total-transferred row as enforced by WO-21 and not gated here", () => {
    const md = report();
    expect(md).toContain("## Rows this script does NOT gate");
    expect(md).toContain("**not gated here**");
    expect(md).toContain("WO-21");
    expect(md).toContain("NOT MEASURED HERE");
    // The number is still visible, so it can never be silently dropped.
    expect(md).toContain("245,760 B");
  });

  it("puts the derived row under 'Reported, not gated'", () => {
    const md = report();
    const derivedIndex = md.indexOf("Derived: total first-load transfer");
    expect(derivedIndex).toBeGreaterThan(md.indexOf("## Reported, not gated"));
    expect(md).toContain("transfer ceiling, not an LCP ceiling");
  });

  it("states the result and, on a breach, what the two legitimate responses are", () => {
    expect(report()).toContain("**Result: pass.**");
    const measuredCss = gzipOf(fixture, "static/css/bbbbbbbbbbbbbbbb.css");
    const breached = report({ "emitted-css": measuredCss - 1 });
    expect(breached).toContain("**Result: BREACH.**");
    expect(breached).toContain("### Breaches");
    expect(breached).toContain("reduce the payload, or move the ceiling");
  });

  it("records the method, the baseline reproduction and the manifest cross-check", () => {
    const md = report();
    expect(md).toContain("## Method");
    expect(md).toContain("zlib level 6");
    expect(md).toContain("## Baseline reproduction");
    expect(md).toContain("## Manifest cross-check");
    expect(md).toContain("manifest union == prerendered `<script src>` set");
    expect(md).toContain("## Chunk detail");
  });

  it("restates the ratchet rule and lists what it does not cover, including RC-06 CLS", () => {
    const md = report();
    expect(md).toContain("## Ratchet rule");
    expect(md).toContain("no flag and no env var can skip this check");
    expect(md).toContain("CLS (RC-06)");
  });

  it("surfaces any raised ceiling on every run instead of burying it in a merged diff", () => {
    const budgets = fixtureBudgets();
    budgets.ratchet = [
      {
        row: "shared-framework-runtime",
        from: 122_880,
        to: 141_312,
        date: "2026-08-28",
        authority: "Coordinator ruling under the Gate 2 delegation",
        why: "The RC-01 ceiling was inferred without a measured baseline and proved infeasible.",
      },
    ];
    const { measurements, crossChecks } = measure({ webDir: fixture.root, budgets });
    const md = renderReport({
      result: evaluate(measurements),
      budgets,
      crossChecks,
      generatedAt: "2026-08-28T00:00:00.000Z",
      nextVersion: "16.3.3",
    });
    expect(md).toContain("### Ceilings that have moved");
    expect(md).toContain("122,880 B");
    expect(md).toContain("141,312 B");
    expect(md).toContain("Coordinator ruling under the Gate 2 delegation");
  });

  it("omits the ratchet section entirely when no ceiling has moved", () => {
    expect(report()).not.toContain("### Ceilings that have moved");
  });
});

describe("the committed budgets.json encodes RC-01 in bytes", () => {
  const budgets = loadBudgets(BUDGETS_PATH);

  it("has the seven reconciled rows plus the four (learn) route rows", () => {
    expect(budgets.rows.map((r) => r.id)).toEqual([
      "route-js-home",
      "route-js-conversation",
      "route-js-learn-list",
      "route-js-learn-path",
      // WO-W13. A new row is an APPEND, not a ratchet: it is seeded at its
      // first measurement with the usual headroom and has no ceiling to
      // justify moving. Only a row whose ceiling moves needs a `ratchet`
      // entry, which is why this id has none.
      "route-js-learn-session",
      // WO-W14's Ledger, appended after it for the same reason: the rows
      // are read in order by the report and by the eye.
      "route-js-learn-progress",
      "shared-framework-runtime",
      "emitted-css",
      "self-hosted-fonts",
      "total-transferred-js",
      "derived-total-first-load",
    ]);
  });

  it.each([
    // WO-31 RATCHETED SIX OF THE SEVEN DOWN, to the post-cleanup
    // measurements taken on main at 8f0d738. Each movement has a per-row
    // entry in the `ratchet` log with its measured figure and its headroom,
    // and the two rows that had been RAISED before keep that earlier
    // argument in the entry's `previousMovement`.
    //
    // `baselineBytes` is unchanged on every row: it is the retained Gate 1
    // measurement, and the report's baseline-reproduction table is what
    // proves this script still reproduces those figures. A ceiling moving
    // must never move a baseline.
    ["route-js-home", 166_912, 137_272],
    ["route-js-conversation", 192_512, 184_745],
    ["route-js-learn-list", 166_912, null],
    ["route-js-learn-path", 169_984, null],
    ["route-js-learn-session", 188_416, null],
    // WO-W14 seeds the Ledger at its sibling /learn/paths/[id]'s ceiling.
    // No `baselineBytes`: there is no Gate 1 measurement of a route that
    // did not exist then.
    ["route-js-learn-progress", 169_984, null],
    ["shared-framework-runtime", 139_264, null],
    // WO-W13 ratcheted this one UP, 11,264 -> 12,288: the guided-read
    // session's two-column margin measured 11,335 B, 71 B over the WO-31
    // ceiling. 12 KiB is the smallest whole-KiB ceiling above it and keeps
    // less proportional headroom than the ceiling it replaces.
    ["emitted-css", 12_288, 4_288],
    ["self-hosted-fonts", 109_568, 0],
    // The one row WO-31 could not ratchet: its `enforcedBy` names a WO-21
    // Playwright transfer assertion that was never written, so there is no
    // measurement to ratchet to. See the assertion further down.
    ["total-transferred-js", 245_760, null],
    // Mechanical: this row is defined as route-js-conversation +
    // emitted-css + self-hosted-fonts, so the CSS movement above moves it by
    // exactly the same 1,024 B. 192,512 + 12,288 + 109,568 = 314,368.
    ["derived-total-first-load", 314_368, null],
  ])("row %s carries the ratified ceiling in bytes", (id, budgetBytes, baselineBytes) => {
    const row = budgets.rows.find((r) => r.id === id);
    expect(row?.budgetBytes).toBe(budgetBytes);
    expect(Number.isInteger(row?.budgetBytes)).toBe(true);
    expect(row?.baselineBytes ?? null).toBe(baselineBytes);
  });

  it("gates the eight per-asset-class rows, delegates one and only reports one", () => {
    const by = (enforcement: string) =>
      budgets.rows.filter((r) => r.enforcement === enforcement).map((r) => r.id);
    // Seven at WO-31, plus WO-W13's `/learn/sessions/[id]` and WO-W14's
    // `/learn/progress`. A new route row is gated from its first commit;
    // there is no "reported for a while first" grace, because a ceiling
    // nobody enforces is a note.
    expect(by("gated")).toHaveLength(9);
    expect(by("external")).toEqual(["total-transferred-js"]);
    expect(by("reported")).toEqual(["derived-total-first-load"]);
  });

  it("records every deviation from RC-01 in the ratchet log, and the log agrees with the rows", () => {
    const ratchet = budgets.ratchet ?? [];
    expect(ratchet.length).toBeGreaterThan(0);
    for (const entry of ratchet) {
      const row = budgets.rows.find((r) => r.id === entry.row);
      expect(row, `ratchet entry names unknown row ${entry.row}`).toBeDefined();
      expect(entry.from).not.toBe(entry.to);
      expect(entry.why.length).toBeGreaterThan(80);
      expect(Number.isInteger(entry.from) && Number.isInteger(entry.to)).toBe(true);
    }

    // THE LIVE CEILING MUST EQUAL THE LAST THING THE LOG SAYS IT MOVED TO,
    // so a ceiling can never drift away from its own justification.
    //
    // Read per row rather than per entry, and that generalisation is
    // WO-W13's: `emitted-css` now has TWO movements — WO-31's ratchet down
    // to 11,264 and WO-W13's up to 12,288 — and a per-entry check would
    // demand the live ceiling equal both. The log is APPEND-ONLY history, so
    // the newest entry for a row is the one that has to match; the older
    // ones are the audit trail and are asserted above for their own shape.
    const latest = new Map<string, (typeof ratchet)[number]>();
    for (const entry of ratchet) latest.set(entry.row, entry);
    for (const [id, entry] of latest) {
      const row = budgets.rows.find((r) => r.id === id);
      expect(row?.budgetBytes, `${id} drifted from its newest ratchet entry`).toBe(
        entry.to
      );
    }

    // And the chain has no gap: each movement of a row starts where the
    // previous one ended. A `from` that skips a value would be a ceiling
    // that moved once without saying so.
    const byRow = new Map<string, (typeof ratchet)[number][]>();
    for (const entry of ratchet) {
      byRow.set(entry.row, [...(byRow.get(entry.row) ?? []), entry]);
    }
    for (const [id, entries] of byRow) {
      entries.forEach((entry, index) => {
        if (index === 0) return;
        expect(entry.from, `${id} ratchet chain has a gap at movement ${index}`).toBe(
          entries[index - 1]!.to
        );
      });
    }
  });

  it("carries the shared framework/runtime movements with their measured justifications", () => {
    const entry = (budgets.ratchet ?? []).find((r) => r.row === "shared-framework-runtime");
    // WO-31's ratchet DOWN, against the current measurement (main d3460a7).
    expect(entry?.from).toBe(141_312);
    expect(entry?.to).toBe(139_264); // 136 KiB
    expect(entry?.measuredBytes).toBe(131_641);
    expect((entry?.to ?? 0) / (entry?.measuredBytes ?? 1)).toBeCloseTo(1.058, 2);

    // WO-23's raise, retained. It is the record of why this row exceeds
    // RC-01's 122,880 B at all — React DOM plus the Next app-router runtime
    // already totalled 128,973 B before any application code existed — and a
    // smaller ceiling does not supersede that argument.
    const before = entry?.previousMovement;
    expect(before?.from).toBe(122_880); // the RC-01 ceiling
    expect(before?.to).toBe(141_312); // 138 KiB
    expect(before?.measuredBytes).toBe(130_865);
    expect(entry?.perFileAtChange?.total).toBe(130_865);
  });

  it("carries the landing-route movements with their measured justifications", () => {
    const entry = (budgets.ratchet ?? []).find((r) => r.row === "route-js-home");
    expect(entry?.from).toBe(167_936);
    expect(entry?.to).toBe(166_912); // 163 KiB
    expect(entry?.measuredBytes).toBe(158_878);
    // Tighter than the ~8% RC-01's rows carry, because this one is measured
    // against the finished surface rather than projected from the legacy one.
    expect((entry?.to ?? 0) / (entry?.measuredBytes ?? 1)).toBeCloseTo(1.051, 2);

    const before = entry?.previousMovement;
    expect(before?.from).toBe(148_480); // the RC-01 ceiling
    expect(before?.to).toBe(167_936); // 164 KiB
    expect(before?.measuredBytes).toBe(158_899);
    // The rejected alternative and its number are part of the justification,
    // not a note somebody made elsewhere: a ratchet entry that only says the
    // ceiling was too low is an assertion, and this one has to be an argument.
    expect(before?.why).toContain("143426");
    expect(before?.why).toContain("page-has-heading-one");
  });

  /**
   * WO-31 criterion 5 — the ratchet went DOWN, on every row that had a
   * measurement to go down to.
   *
   * Stated as one assertion rather than left implicit in the table above,
   * because "ratcheted to the measured post-cleanup values" is the criterion
   * and a later PR raising a row would otherwise only have to edit two
   * numbers in the same file to look consistent.
   */
  it("ratcheted every measurable row DOWN, with headroom over its measurement", () => {
    const lowered = (budgets.ratchet ?? []).filter((r) => r.pr?.startsWith("WO-31"));
    expect(lowered.map((r) => r.row)).toEqual([
      "route-js-home",
      "route-js-conversation",
      "shared-framework-runtime",
      "emitted-css",
      "self-hosted-fonts",
      "derived-total-first-load",
    ]);
    for (const entry of lowered) {
      expect(entry.to, `${entry.row} did not move down`).toBeLessThan(entry.from);
      // A ratchet with no measurement behind it is a preference.
      expect(entry.measuredBytes, `${entry.row} states no measurement`).toBeTypeOf("number");
      // A ceiling below its own measurement is a red build, not a ratchet.
      expect(entry.to, `${entry.row} is below what it measured`).toBeGreaterThan(
        entry.measuredBytes ?? Infinity,
      );
    }
  });

  it("leaves the one row it cannot measure alone, and says why", () => {
    // `total-transferred-js` is the only row with no measurement anywhere:
    // its `enforcedBy` names a WO-21 Playwright transfer assertion that was
    // never written, so there is nothing to ratchet to. It must therefore
    // carry no WO-31 ratchet entry.
    const row = budgets.rows.find((r) => r.id === "total-transferred-js");
    expect(row?.budgetBytes).toBe(245_760);
    expect(row?.enforcement).toBe("external");
    expect(
      (budgets.ratchet ?? []).some((r) => r.row === "total-transferred-js"),
    ).toBe(false);
  });

  it("names WO-21 as the enforcer of the total-transferred row", () => {
    const row = budgets.rows.find((r) => r.id === "total-transferred-js");
    expect(row?.enforcedBy).toMatch(/WO-21/);
  });

  it("rejects a budgets file whose ceiling is a KB string", () => {
    const bad = path.join(fixture.root, "bad-budgets.json");
    fs.writeFileSync(
      bad,
      JSON.stringify({
        source: "fixture",
        rows: [
          {
            id: "emitted-css",
            kind: "emitted-css",
            label: "All emitted CSS",
            budgetBytes: "12 KiB",
            enforcement: "gated",
          },
        ],
      }),
    );
    expect(() => loadBudgets(bad)).toThrow(/integer number of BYTES/);
  });
});

describe("ratchet rule (criterion 7: nothing can skip the check)", () => {
  const source = fs.readFileSync(SCRIPT_PATH, "utf8");

  it("reads no environment variable", () => {
    expect(source).not.toMatch(/process\.env/);
  });

  it("has no skip/ignore/force escape hatch", () => {
    expect(source).not.toMatch(/--(skip|ignore|force|no-fail|allow-fail)/);
    expect(source).not.toMatch(/SKIP_BUDGETS|BUDGETS_SKIP|IGNORE_BUDGET/i);
  });

  it("refuses any command-line argument, so no flag can be introduced by invocation", () => {
    expect(source).toContain("this check takes no arguments");
  });

  it("exits non-zero on breach rather than warning", () => {
    expect(source).toMatch(/if \(result\.breached\)/);
    expect(source).toMatch(/return 1;/);
  });

  it("is wired to an npm script that builds first", () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(WEB_DIR, "package.json"), "utf8")) as {
      scripts: Record<string, string>;
    };
    expect(pkg.scripts.budgets).toBe("npm run build && node scripts/route-budgets.mjs");
    // B4: the build tool stays pinned to webpack.
    expect(pkg.scripts.build).toBe("next build --webpack");
  });
});

describe("run()", () => {
  it("writes budget-report.md next to budgets.json and returns the verdict", () => {
    fs.copyFileSync(BUDGETS_PATH, path.join(fixture.root, "budgets.json"));
    fs.mkdirSync(path.join(fixture.root, "node_modules", "next"), { recursive: true });
    fs.writeFileSync(
      path.join(fixture.root, "node_modules", "next", "package.json"),
      JSON.stringify({ version: "16.3.3" }),
    );
    const { result, reportPath } = run({ webDir: fixture.root, now: new Date(0) });
    expect(reportPath).toBe(path.join(fixture.root, "budget-report.md"));
    expect(fs.readFileSync(reportPath, "utf8")).toContain("# Route budget report");
    // Eleven rows: the seven reconciled ones plus the four `(learn)` routes.
    expect(result.rows).toHaveLength(11);
  });

  it("explains how to fix a missing build instead of measuring nothing", () => {
    const empty = fs.mkdtempSync(path.join(os.tmpdir(), "wo23-empty-"));
    try {
      expect(() =>
        measure({ webDir: empty, budgets: fixtureBudgets() } as {
          webDir: string;
          budgets: BudgetsFile;
        }),
      ).toThrow(/npm run build/);
    } finally {
      fs.rmSync(empty, { recursive: true, force: true });
    }
  });
});
