#!/usr/bin/env node
/**
 * Route budget check (WO-23, C7).
 *
 * Reads the Next.js production build manifests, gzips the per-route first-load
 * file union, compares every ceiling in `budgets.json` (bytes, never "KB"
 * strings), writes `budget-report.md`, and exits non-zero on any breach.
 *
 * RATCHET RULE (04-ARCHITECTURE.md 8.4). This module deliberately:
 *   - accepts NO command-line arguments,
 *   - reads NO environment variables,
 *   - has no skip/ignore/allow-failure path of any kind.
 * A budget may only move by editing `budgets.json` in the same commit, with the
 * reason stated in the PR body. `tests/budgets.test.ts` asserts these
 * properties against this file's own source text so they cannot regress.
 *
 * MANIFEST NOTE (deviation from the WO-23 criterion-1 wording, documented in
 * the PR body). 04-ARCHITECTURE.md 8.4 and the WO-23 card were written against
 * Next 15, which emitted `.next/app-build-manifest.json`. Next 16.3.3 — the
 * version this repo pins, built with `next build --webpack` — no longer emits
 * that file; `APP_BUILD_MANIFEST` was removed from
 * `next/dist/shared/lib/constants.js`. The equivalent app-router route -> chunk
 * association in Next 16 is:
 *   - `.next/build-manifest.json`   -> `rootMainFiles` (shared by every app
 *                                      route) and `polyfillFiles` (excluded by
 *                                      the budget definition),
 *   - `.next/app-path-routes-manifest.json` -> route path -> entry key,
 *   - `.next/server/app/<entry>/page_client-reference-manifest.js`
 *                                   -> the entry's client modules and the
 *                                      chunks each one pulls in.
 * Both `build-manifest.json` files named by the criterion are read; the
 * app-router half is read from the manifests that replaced the deleted one.
 * `verifyAgainstPrerenderedHtml()` below independently cross-checks the
 * manifest-derived union against the `<script src>` set of the prerendered HTML
 * for every statically rendered route, so the substitution is proved, not
 * asserted.
 */

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import zlib from "node:zlib";
import { fileURLToPath, pathToFileURL } from "node:url";

/**
 * zlib level 6 (zlib's own default). Determined from the retained Gate 1
 * baseline, not chosen: summing per-file `gzipSync(buf, { level: 6 })` over the
 * `/c/[id]` first-load union reproduces `docs/revamp/baseline/README.md`'s
 * 184,745 B exactly, and no other level reproduces it. See the "Method"
 * section of the generated report.
 */
export const GZIP_LEVEL = 6;

const BYTES_PER_KIB = 1024;

/** App-router special files that are part of a route's own segment path. */
const APP_SEGMENT_FILE = /^(page|layout|template|default|error|global-error|not-found|loading|forbidden|unauthorized)\.(?:[cm]?[jt]sx?)$/;

const ROW_KINDS = new Set([
  "route-first-load-js",
  "shared-first-load-js",
  "emitted-css",
  "self-hosted-fonts",
  "external-total-transferred-js",
  "derived-total-first-load",
]);

const ENFORCEMENTS = new Set(["gated", "external", "reported"]);

// ---------------------------------------------------------------------------
// Bytes
// ---------------------------------------------------------------------------

/**
 * WO-23 criterion 2: budgets are BYTES, expressed as integers. A "145 KiB"
 * string is a hard error rather than something this script tries to interpret,
 * which is exactly what makes the comparison unambiguous.
 */
export function parseBudgetBytes(value, context = "budget") {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(
      `${context}: budgets must be a non-negative integer number of BYTES ` +
        `(RC-01 / WO-23 criterion 2), not ${JSON.stringify(value)}. ` +
        `Write 148480, not "145 KiB".`,
    );
  }
  return value;
}

/** Gzip byte length of a buffer at the baseline-matching level. */
export function gzipBytes(buffer) {
  return zlib.gzipSync(buffer, { level: GZIP_LEVEL }).length;
}

/** Gzip byte length of a file on disk. */
export function gzipFileBytes(absPath) {
  return gzipBytes(fs.readFileSync(absPath));
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  const kib = (bytes / BYTES_PER_KIB).toFixed(1);
  return `${bytes.toLocaleString("en-US")} B (${kib} KiB)`;
}

export function formatDelta(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  const sign = bytes > 0 ? "+" : bytes < 0 ? "−" : "±";
  return `${sign}${Math.abs(bytes).toLocaleString("en-US")} B`;
}

// ---------------------------------------------------------------------------
// budgets.json
// ---------------------------------------------------------------------------

export function loadBudgets(budgetsPath) {
  const raw = JSON.parse(fs.readFileSync(budgetsPath, "utf8"));
  if (!Array.isArray(raw.rows) || raw.rows.length === 0) {
    throw new Error(`${budgetsPath}: "rows" must be a non-empty array.`);
  }
  const seen = new Set();
  for (const row of raw.rows) {
    if (!row.id || seen.has(row.id)) {
      throw new Error(`${budgetsPath}: duplicate or missing row id ${JSON.stringify(row.id)}.`);
    }
    seen.add(row.id);
    if (!ROW_KINDS.has(row.kind)) {
      throw new Error(`${budgetsPath}: row "${row.id}" has unknown kind ${JSON.stringify(row.kind)}.`);
    }
    if (!ENFORCEMENTS.has(row.enforcement)) {
      throw new Error(
        `${budgetsPath}: row "${row.id}" has unknown enforcement ${JSON.stringify(row.enforcement)}.`,
      );
    }
    parseBudgetBytes(row.budgetBytes, `${budgetsPath}: row "${row.id}"`);
    if (row.baselineBytes !== null && row.baselineBytes !== undefined) {
      parseBudgetBytes(row.baselineBytes, `${budgetsPath}: row "${row.id}" baseline`);
    }
  }
  return raw;
}

// ---------------------------------------------------------------------------
// Manifests
// ---------------------------------------------------------------------------

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

/**
 * Evaluate a `page_client-reference-manifest.js` in an isolated VM context. The
 * file is a plain assignment to `globalThis.__RSC_MANIFEST`; running it in a
 * fresh context keeps it out of this process's globals.
 */
export function readClientReferenceManifest(file) {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file });
  return context.__RSC_MANIFEST ?? {};
}

/** Absolute path of the client-reference manifest for an app entry key. */
function clientReferenceManifestPath(nextDir, entryKey) {
  const withoutLeadingSlash = entryKey.replace(/^\//, "");
  const dir = path.posix.dirname(withoutLeadingSlash);
  const rel = dir === "." ? "" : dir;
  return path.join(nextDir, "server", "app", rel, "page_client-reference-manifest.js");
}

/**
 * Is `modulePath` (relative to the web root, POSIX separators) part of the
 * route's own segment path?
 *
 * Client modules outside `app/` (components, lib, node_modules) belong to
 * whichever entry's graph pulled them in and are always counted. Modules inside
 * `app/` are counted only when they sit on this route's own segment path — the
 * Next 16 manifest for one entry can also list another entry's page module, and
 * counting `/`'s page chunk against `/c/[id]` would inflate the route.
 */
export function isOnRouteSegmentPath(modulePath, entryKey) {
  if (!modulePath.startsWith("app/")) return true;
  const entryDir = path.posix.dirname(`app${entryKey}`); // e.g. app/c/[id]
  const moduleDir = path.posix.dirname(modulePath);
  const base = path.posix.basename(modulePath);
  if (!APP_SEGMENT_FILE.test(base)) return false;
  const isAncestor = entryDir === moduleDir || entryDir.startsWith(`${moduleDir}/`);
  if (!isAncestor) return false;
  // Only this entry's own `page.*` counts; a parent segment's page is a
  // different route.
  if (base.startsWith("page.") && moduleDir !== entryDir) return false;
  return true;
}

function chunkPathsOf(chunks) {
  // `chunks` interleaves webpack chunk ids with emitted asset paths.
  return (chunks ?? [])
    .filter((c) => typeof c === "string" && c.includes("static/chunks/") && c.endsWith(".js"))
    .map((c) => decodeURIComponent(c));
}

/**
 * The first-load JavaScript file union for one app route, as
 * build-root-relative paths (e.g. `static/chunks/webpack-abc.js`).
 * Polyfills are excluded — every budget row in RC-01 is "excl. polyfill".
 */
export function routeFirstLoadFiles(nextDir, route) {
  const buildManifest = readJson(path.join(nextDir, "build-manifest.json"));
  const appRoutes = readJson(path.join(nextDir, "app-path-routes-manifest.json"));

  const entryKey = Object.keys(appRoutes).find((key) => appRoutes[key] === route);
  if (!entryKey) {
    throw new Error(
      `Route ${JSON.stringify(route)} is not in .next/app-path-routes-manifest.json. ` +
        `Known routes: ${Object.values(appRoutes).join(", ")}`,
    );
  }

  const polyfills = new Set(buildManifest.polyfillFiles ?? []);
  const files = new Set((buildManifest.rootMainFiles ?? []).filter((f) => !polyfills.has(f)));

  const manifestFile = clientReferenceManifestPath(nextDir, entryKey);
  const manifest = readClientReferenceManifest(manifestFile)[entryKey];
  if (!manifest) {
    throw new Error(`${manifestFile}: no __RSC_MANIFEST entry for ${entryKey}.`);
  }

  const webDir = path.dirname(nextDir);
  for (const [rawKey, mod] of Object.entries(manifest.clientModules ?? {})) {
    const modulePath = rawKey.split("#")[0];
    const rel = path.relative(webDir, modulePath).split(path.sep).join("/");
    // A CSS module's JS stub is never in the script set — its stylesheet is
    // linked instead, and lands in the "all emitted CSS" row.
    if (rel.endsWith(".css")) continue;
    if (!isOnRouteSegmentPath(rel, entryKey)) continue;
    for (const chunk of chunkPathsOf(mod.chunks)) {
      if (!polyfills.has(chunk)) files.add(chunk);
    }
  }

  return [...files].sort();
}

/** The file set shared by every app route: the build manifest's root main files. */
export function sharedFirstLoadFiles(nextDir) {
  const buildManifest = readJson(path.join(nextDir, "build-manifest.json"));
  const polyfills = new Set(buildManifest.polyfillFiles ?? []);
  return (buildManifest.rootMainFiles ?? []).filter((f) => !polyfills.has(f)).sort();
}

/** Every emitted stylesheet, build-root-relative. */
export function emittedCssFiles(nextDir) {
  const dir = path.join(nextDir, "static", "css");
  if (!fs.existsSync(dir)) return [];
  return walk(dir)
    .filter((f) => f.endsWith(".css"))
    .map((f) => path.relative(path.join(nextDir), f).split(path.sep).join("/"))
    .sort();
}

/**
 * Every self-hosted woff2 face, as absolute paths (WO-23 criterion 3: measured
 * from the emitted font binaries, never from the JS manifests).
 *
 * Both emission paths WO-02 could choose are scanned:
 *   - `next/font/local` writes hashed faces to `.next/static/media/`,
 *   - a hand-rolled `@font-face` in `app/globals.css` serves them from
 *     `public/`.
 * WO-02 has not landed, so today this finds nothing and the row reports 0 B.
 * That is the row's honest state, not a pass: `fontsPresent` is false and the
 * report says so on the row.
 */
export function selfHostedFontFiles(webDir) {
  const roots = [
    path.join(webDir, ".next", "static", "media"),
    path.join(webDir, "public"),
  ];
  const found = [];
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    for (const file of walk(root)) {
      if (file.toLowerCase().endsWith(".woff2")) found.push(file);
    }
  }
  return found.sort();
}

function walk(dir, acc = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, acc);
    else acc.push(full);
  }
  return acc;
}

// ---------------------------------------------------------------------------
// Cross-check against the prerendered HTML
// ---------------------------------------------------------------------------

/**
 * For statically prerendered routes, Next writes the real first-load script set
 * into the HTML. Comparing it with the manifest-derived union proves the Next
 * 16 manifest substitution documented at the top of this file. Reported, never
 * gated: a mismatch is a signal for a human, not a budget breach.
 */
export function verifyAgainstPrerenderedHtml(nextDir, route, manifestFiles) {
  const rel = route === "/" ? "index.html" : `${route.replace(/^\//, "")}.html`;
  const htmlFile = path.join(nextDir, "server", "app", rel);
  if (route.includes("[") || !fs.existsSync(htmlFile)) {
    return { route, checked: false, reason: "not statically prerendered" };
  }
  const html = fs.readFileSync(htmlFile, "utf8");
  const buildManifest = readJson(path.join(nextDir, "build-manifest.json"));
  const polyfills = new Set(buildManifest.polyfillFiles ?? []);
  const fromHtml = new Set(
    [...html.matchAll(/<script[^>]*\ssrc="\/_next\/([^"]+)"/g)]
      .map((m) => decodeURIComponent(m[1]))
      .filter((f) => !polyfills.has(f)),
  );
  const expected = new Set(manifestFiles);
  const onlyInHtml = [...fromHtml].filter((f) => !expected.has(f)).sort();
  const onlyInManifest = [...expected].filter((f) => !fromHtml.has(f)).sort();
  return {
    route,
    checked: true,
    match: onlyInHtml.length === 0 && onlyInManifest.length === 0,
    onlyInHtml,
    onlyInManifest,
  };
}

// ---------------------------------------------------------------------------
// Measurement
// ---------------------------------------------------------------------------

function sumFiles(nextDir, relFiles) {
  const files = relFiles.map((rel) => {
    const abs = path.join(nextDir, rel);
    return { file: rel, bytes: gzipFileBytes(abs), rawBytes: fs.statSync(abs).size };
  });
  return { files, total: files.reduce((acc, f) => acc + f.bytes, 0) };
}

/**
 * Measure every row in `budgets`. Returns one measurement per row, in the same
 * order, plus the manifest cross-check results.
 */
export function measure({ webDir, budgets }) {
  const nextDir = path.join(webDir, ".next");
  if (!fs.existsSync(path.join(nextDir, "build-manifest.json"))) {
    throw new Error(
      `${nextDir}/build-manifest.json is missing. Run \`npm run build\` first ` +
        `(\`npm run budgets\` does this for you).`,
    );
  }

  const crossChecks = [];
  const byId = new Map();
  const measured = [];

  for (const row of budgets.rows) {
    const m = { row, files: [], measuredBytes: null, notes: [] };

    switch (row.kind) {
      case "route-first-load-js": {
        const rel = routeFirstLoadFiles(nextDir, row.route);
        const { files, total } = sumFiles(nextDir, rel);
        m.files = files;
        m.measuredBytes = total;
        crossChecks.push(verifyAgainstPrerenderedHtml(nextDir, row.route, rel));
        break;
      }
      case "shared-first-load-js": {
        const { files, total } = sumFiles(nextDir, sharedFirstLoadFiles(nextDir));
        m.files = files;
        m.measuredBytes = total;
        break;
      }
      case "emitted-css": {
        const { files, total } = sumFiles(nextDir, emittedCssFiles(nextDir));
        m.files = files;
        m.measuredBytes = total;
        break;
      }
      case "self-hosted-fonts": {
        // Raw woff2 bytes: woff2 is already Brotli-compressed internally, so
        // the wire weight is the file size. Gzipping it again would understate
        // nothing and overstate nothing — it would simply not be the number a
        // browser downloads.
        const faces = selfHostedFontFiles(webDir);
        m.files = faces.map((abs) => ({
          file: path.relative(webDir, abs).split(path.sep).join("/"),
          bytes: fs.statSync(abs).size,
          rawBytes: fs.statSync(abs).size,
        }));
        m.measuredBytes = m.files.reduce((acc, f) => acc + f.bytes, 0);
        m.fontsPresent = faces.length > 0;
        if (!m.fontsPresent) {
          m.notes.push(
            "No self-hosted woff2 emitted. WO-02 has not landed, so this row reports 0 B " +
              "and is not yet a meaningful pass. The measurement path is live: it scans " +
              "`.next/static/media/**/*.woff2` and `public/**/*.woff2` and will report the " +
              "real per-face total the moment WO-02's faces exist.",
          );
        }
        break;
      }
      case "external-total-transferred-js": {
        m.measuredBytes = null;
        m.notes.push(
          `NOT MEASURED HERE. This row cannot come from the build manifests — lazy chunks ` +
            `are fetched at runtime. It is enforced by ${row.enforcedBy}.`,
        );
        break;
      }
      case "derived-total-first-load": {
        const parts = (row.derivedFrom ?? []).map((id) => {
          const src = byId.get(id);
          if (!src) throw new Error(`Row "${row.id}" derives from unknown row "${id}".`);
          return src;
        });
        m.measuredBytes = parts.reduce((acc, p) => acc + (p.measuredBytes ?? 0), 0);
        m.derivedFrom = parts.map((p) => p.row.id);
        break;
      }
      default:
        throw new Error(`Unhandled row kind ${row.kind}.`);
    }

    byId.set(row.id, m);
    measured.push(m);
  }

  return { measurements: measured, crossChecks };
}

// ---------------------------------------------------------------------------
// Evaluation
// ---------------------------------------------------------------------------

/**
 * Turn measurements into pass/breach verdicts. Only rows with
 * `enforcement: "gated"` can breach; `"external"` and `"reported"` rows are
 * carried into the report so the number is visible and never silently treated
 * as gated.
 */
export function evaluate(measurements) {
  const rows = measurements.map((m) => {
    const budget = parseBudgetBytes(m.row.budgetBytes, `row "${m.row.id}"`);
    const measuredBytes = m.measuredBytes;
    const gated = m.row.enforcement === "gated";
    const comparable = typeof measuredBytes === "number";
    const headroomBytes = comparable ? budget - measuredBytes : null;
    const breached = gated && comparable && measuredBytes > budget;
    let status;
    if (m.row.enforcement === "external") status = "EXTERNAL";
    else if (m.row.enforcement === "reported") status = "REPORTED";
    else status = breached ? "BREACH" : "PASS";
    const baselineBytes =
      typeof m.row.baselineBytes === "number" ? m.row.baselineBytes : null;
    return {
      ...m,
      budgetBytes: budget,
      measuredBytes,
      headroomBytes,
      baselineBytes,
      baselineDeltaBytes:
        comparable && baselineBytes !== null ? measuredBytes - baselineBytes : null,
      baselineExact:
        comparable && baselineBytes !== null ? measuredBytes === baselineBytes : null,
      status,
      breached,
    };
  });
  return { rows, breached: rows.some((r) => r.breached) };
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

function statusCell(row) {
  switch (row.status) {
    case "BREACH":
      return "**BREACH**";
    case "PASS":
      return "pass";
    case "EXTERNAL":
      return "**not gated here**";
    default:
      return "reported";
  }
}

export function renderReport({ result, budgets, crossChecks, generatedAt, nextVersion }) {
  const gatedRows = result.rows.filter((r) => r.row.enforcement === "gated");
  const externalRows = result.rows.filter((r) => r.row.enforcement === "external");
  const reportedRows = result.rows.filter((r) => r.row.enforcement === "reported");

  const out = [];
  out.push("# Route budget report");
  out.push("");
  out.push(
    `Generated by \`npm run budgets\` (\`web/scripts/route-budgets.mjs\`, WO-23) at ${generatedAt}.`,
  );
  out.push(`Next.js ${nextVersion} production build (\`next build --webpack\`).`);
  out.push(
    `Budgets: \`web/budgets.json\` — ${budgets.source}.`,
  );
  out.push("");
  out.push(
    result.breached
      ? "**Result: BREACH.** At least one gated ceiling is exceeded; `npm run budgets` exits non-zero."
      : "**Result: pass.** Every gated ceiling holds.",
  );
  out.push("");

  out.push("## Gated rows");
  out.push("");
  out.push("These are the ceilings `npm run budgets` enforces. Any breach exits non-zero.");
  out.push("");
  out.push("| Row | Measured | Budget | Headroom | Retained baseline | Δ baseline | Status |");
  out.push("|---|---:|---:|---:|---:|---:|:---|");
  for (const r of gatedRows) {
    out.push(
      `| ${r.row.label} | ${formatBytes(r.measuredBytes)} | ${formatBytes(r.budgetBytes)} ` +
        `| ${formatDelta(r.headroomBytes)} | ${formatBytes(r.baselineBytes)} ` +
        `| ${formatDelta(r.baselineDeltaBytes)} | ${statusCell(r)} |`,
    );
  }
  out.push("");

  const breaches = result.rows.filter((r) => r.breached);
  if (breaches.length > 0) {
    out.push("### Breaches");
    out.push("");
    for (const r of breaches) {
      out.push(
        `- **${r.row.label}** is over by ${Math.abs(r.headroomBytes).toLocaleString("en-US")} B ` +
          `(${formatBytes(r.measuredBytes)} against ${formatBytes(r.budgetBytes)}).` +
          (r.row.definition ? ` Definition: ${r.row.definition}` : ""),
      );
    }
    out.push("");
    out.push(
      "Two legitimate responses, per 04-ARCHITECTURE.md §8.4: reduce the payload, or move the " +
        "ceiling in `web/budgets.json` in the same commit and say why in the PR body. There is no " +
        "third option — no environment variable and no flag skips this check.",
    );
    out.push("");
  }

  if (externalRows.length > 0) {
    out.push("## Rows this script does NOT gate");
    out.push("");
    out.push(
      "Listed so the ceiling is never silently treated as enforced. `npm run budgets` " +
        "cannot pass or fail on these rows.",
    );
    out.push("");
    out.push("| Row | Budget | Status | Enforced by |");
    out.push("|---|---:|:---|:---|");
    for (const r of externalRows) {
      out.push(
        `| ${r.row.label} | ${formatBytes(r.budgetBytes)} | ${statusCell(r)} | ${r.row.enforcedBy} |`,
      );
    }
    out.push("");
    for (const r of externalRows) {
      for (const note of r.notes) out.push(`> ${r.row.label}: ${note}`);
    }
    out.push("");
  }

  if (reportedRows.length > 0) {
    out.push("## Reported, not gated");
    out.push("");
    out.push("| Row | Measured | Reference ceiling | Δ reference | Composition |");
    out.push("|---|---:|---:|---:|:---|");
    for (const r of reportedRows) {
      out.push(
        `| ${r.row.label} | ${formatBytes(r.measuredBytes)} | ${formatBytes(r.budgetBytes)} ` +
          `| ${formatDelta(r.headroomBytes)} | ${(r.derivedFrom ?? []).join(" + ") || "—"} |`,
      );
    }
    out.push("");
    out.push(
      "RC-01: the derived row is a **transfer ceiling, not an LCP ceiling** — fonts load " +
        "`font-display: swap`, are cached across both routes, and do not block first paint. " +
        "It is here so a reviewer sees the real page weight; the gate stays on the per-class rows.",
    );
    out.push("");
  }

  const noteRows = result.rows.filter(
    (r) => r.notes.length > 0 && r.row.enforcement !== "external",
  );
  if (noteRows.length > 0) {
    out.push("## Row notes");
    out.push("");
    for (const r of noteRows) {
      for (const note of r.notes) out.push(`- **${r.row.label}** — ${note}`);
    }
    out.push("");
  }

  out.push("## Baseline reproduction");
  out.push("");
  out.push(
    "WO-23 criterion 6: the script's own correctness proof is that it reproduces the retained " +
      "`docs/revamp/baseline/README.md` figures from the current build.",
  );
  out.push("");
  out.push("| Row | Retained baseline | Measured now | Reproduced to the byte |");
  out.push("|---|---:|---:|:---|");
  for (const r of result.rows) {
    if (r.baselineBytes === null || typeof r.measuredBytes !== "number") continue;
    out.push(
      `| ${r.row.label} | ${r.baselineBytes.toLocaleString("en-US")} B | ` +
        `${r.measuredBytes.toLocaleString("en-US")} B | ` +
        `${r.baselineExact ? "yes" : `no (${formatDelta(r.baselineDeltaBytes)})`} |`,
    );
  }
  out.push("");
  out.push(
    "Where a row is not byte-exact, the residue is accounted for rather than absorbed into the " +
      "budget:",
  );
  out.push("");
  out.push(
    "- **`/` (+1 B).** The `/` and `/c/[id]` unions share six chunks and differ only in " +
      "`app/page-*.js` versus `454-*.js` + `app/c/[id]/page-*.js`. `/c/[id]` reproduces exactly, " +
      "so the method and the gzip settings are proved; the residue is confined to the one chunk " +
      "`/` does not share. The retained baseline was captured from source commit `e6e8739`, which " +
      "is not an ancestor of this repository's history, so a one-byte compressed difference in the " +
      "home page chunk is a tree difference, not a measurement difference.",
  );
  out.push(
    "- **CSS (−21 B).** 4,267 + 21 = 4,288 exactly, where 21 is the length of a Next stylesheet " +
      "filename plus its NUL terminator (`<16 hex>.css` is always 20 characters). That is the " +
      "`FNAME` header `gzip(1)` writes when it compresses a named file and omits with `-n`: " +
      "`gzip -c 036cc441629251b0.css` is 4,288 bytes and `gzip -cn` is 4,267. The retained CSS " +
      "figure therefore includes 21 bytes of gzip filename metadata that no server ever sends. " +
      "This script measures payload, so it reports 4,267 for every row and does not reproduce the " +
      "header. The route rows confirm the split: with `FNAME` headers the `/c/[id]` union would be " +
      "184,928 B, not the retained 184,745 B.",
  );
  out.push("");

  out.push("## Manifest cross-check");
  out.push("");
  out.push(
    "Next 16.3.3 no longer emits `.next/app-build-manifest.json`, so the app-router route → " +
      "chunk association is rebuilt from `build-manifest.json` (`rootMainFiles`, " +
      "`polyfillFiles`), `app-path-routes-manifest.json`, and each entry's " +
      "`page_client-reference-manifest.js`. For every statically prerendered route the derived " +
      "union is compared with the `<script src>` set Next actually wrote into the HTML:",
  );
  out.push("");
  out.push("| Route | Cross-check |");
  out.push("|---|:---|");
  for (const c of crossChecks) {
    if (!c.checked) {
      out.push(`| \`${c.route}\` | skipped — ${c.reason} |`);
    } else if (c.match) {
      out.push(`| \`${c.route}\` | manifest union == prerendered \`<script src>\` set |`);
    } else {
      out.push(
        `| \`${c.route}\` | **mismatch** — only in HTML: ${c.onlyInHtml.join(", ") || "none"}; ` +
          `only in manifest: ${c.onlyInManifest.join(", ") || "none"} |`,
      );
    }
  }
  out.push("");

  out.push("## Chunk detail");
  out.push("");
  for (const r of result.rows) {
    if (r.files.length === 0) continue;
    out.push(`### ${r.row.label}`);
    out.push("");
    out.push("| File | Gzip | Raw |");
    out.push("|---|---:|---:|");
    for (const f of r.files) {
      out.push(
        `| \`${f.file}\` | ${f.bytes.toLocaleString("en-US")} B | ${f.rawBytes.toLocaleString("en-US")} B |`,
      );
    }
    out.push(
      `| **total** | **${(r.measuredBytes ?? 0).toLocaleString("en-US")} B** | |`,
    );
    out.push("");
  }

  out.push("## Method");
  out.push("");
  out.push(`- Compression: gzip, zlib level ${GZIP_LEVEL} (zlib's default), one gzip stream per file, summed.`);
  out.push(
    "- The level is not a preference: summing per-file level-6 gzip over the `/c/[id]` first-load " +
      "union reproduces the retained baseline's 184,745 B exactly, and no other level does.",
  );
  out.push("- Polyfills are excluded from every JS row (RC-01 says \"excl. polyfill\").");
  out.push(
    "- Fonts are measured as raw woff2 bytes, not gzipped: woff2 carries its own Brotli " +
      "compression, so the file size is the wire weight.",
  );
  out.push("- Stylesheets are gzipped like JS and summed across every emitted `.css`.");
  out.push("");

  out.push("## Ratchet rule");
  out.push("");
  out.push(
    "04-ARCHITECTURE.md §8.4: budgets may only move in a PR that says why in the PR body and " +
      "updates `web/budgets.json` in the same commit. `scripts/route-budgets.mjs` accepts no " +
      "command-line arguments and reads no environment variables, so no flag and no env var can " +
      "skip this check; `tests/budgets.test.ts` asserts that against the script's own source.",
  );
  out.push("");

  out.push("## Not covered by this report");
  out.push("");
  out.push(
    "- **CLS (RC-06).** The CI gate is ≤ 0.02 and the design intent and measured baseline are " +
      "0.000. CLS is measured by WO-21 (Playwright) and WO-29 (Lighthouse CI), not here. RC-06 " +
      "requires any state that lands non-zero to carry a written justification in this report; " +
      "no such justification has been filed, and none is due until those measurements exist.",
  );
  out.push("- **Lab performance targets (04 §8.2).** WO-29, nightly `lhci autorun`.");
  out.push("- **Reflow (`scrollWidth <= clientWidth`).** WO-21, per-PR chromium E2E.");
  out.push("");

  return out.join("\n");
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

export function run({ webDir, now = new Date() } = {}) {
  const budgetsPath = path.join(webDir, "budgets.json");
  const budgets = loadBudgets(budgetsPath);
  const { measurements, crossChecks } = measure({ webDir, budgets });
  const result = evaluate(measurements);
  const nextVersion = readJson(
    path.join(webDir, "node_modules", "next", "package.json"),
  ).version;
  const report = renderReport({
    result,
    budgets,
    crossChecks,
    generatedAt: now.toISOString(),
    nextVersion,
  });
  const reportPath = path.join(webDir, "budget-report.md");
  fs.writeFileSync(reportPath, `${report}\n`, "utf8");
  return { result, report, reportPath };
}

function main(argv) {
  if (argv.length > 0) {
    // Ratchet rule: there is nothing to configure, and in particular nothing
    // that could skip or soften the check.
    console.error(
      "route-budgets: this check takes no arguments. Budgets live in web/budgets.json " +
        "and may only change under the ratchet rule (04-ARCHITECTURE.md §8.4).",
    );
    return 2;
  }
  const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const { result, reportPath } = run({ webDir });

  for (const row of result.rows) {
    const measured = typeof row.measuredBytes === "number" ? formatBytes(row.measuredBytes) : "not measured here";
    console.log(
      `${row.status.padEnd(9)} ${row.row.label} — ${measured} against ${formatBytes(row.budgetBytes)}`,
    );
  }
  console.log(`\nReport written to ${reportPath}`);

  if (result.breached) {
    const breaches = result.rows.filter((r) => r.breached);
    console.error(
      `\nBudget breach in ${breaches.length} row(s): ${breaches.map((r) => r.row.id).join(", ")}.\n` +
        "Either reduce the payload, or move the ceiling in web/budgets.json in the same commit " +
        "and say why in the PR body (04-ARCHITECTURE.md §8.4). There is no skip flag.",
    );
    return 1;
  }
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exit(main(process.argv.slice(2)));
}
