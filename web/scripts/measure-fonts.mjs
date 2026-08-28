#!/usr/bin/env node
/**
 * WO-02 — font byte table and measured fallback metrics.
 *
 * Two independent reports, both re-runnable, neither carrying an invented
 * number:
 *
 *   1. BYTES     Every committed woff2 in app/fonts/, raw and gzip, totalled
 *                against the RC-01 font budget (122,880 B). Pure Node.
 *
 *   2. METRICS   size-adjust / ascent-override / descent-override /
 *                line-gap-override for each family, measured in a real
 *                browser against the fallback stack declared in
 *                app/tokens.css. Needs Chrome; skip with --no-browser.
 *
 * The metric method, in full:
 *
 *   A headless Chrome page loads the committed woff2 through the FontFace
 *   API (inlined as a data: URL, so no server and no file:// origin rules)
 *   and lays out one reference string twice -- once in the webfont, once in
 *   the fallback -- reading three numbers from each:
 *
 *     width              advance width of the reference string, from
 *                        CanvasRenderingContext2D.measureText
 *     baselineFromTop    distance from the top of a `line-height: normal`
 *                        line box to the alphabetic baseline, read off a
 *                        zero-height `vertical-align: baseline` marker span
 *     lineBoxHeight      height of that same line box
 *
 *   Every face this work order ships has hhea.lineGap = 0 (asserted below
 *   from the fonts themselves via --check-linegap, and recorded in
 *   evidence/gate-3/fonts.md). With no leading to distribute, the line box
 *   is exactly ascent + descent and the baseline sits exactly at ascent, so
 *   the two DOM numbers give ascent and descent directly rather than
 *   through an assumption:
 *
 *     ascent  = baselineFromTop / SIZE
 *     descent = (lineBoxHeight - baselineFromTop) / SIZE
 *
 *   The CSS descriptors follow the definition in CSS Fonts 5: size-adjust
 *   scales the em, and the ascent/descent overrides are percentages of that
 *   already-scaled em, so each is divided by the size adjustment.
 *
 *     size-adjust      = webfont.width / anchor.width
 *     ascent-override  = webfont.ascent  / size-adjust
 *     descent-override = webfont.descent / size-adjust
 *     line-gap-override = 0%   (measured: every shipped face has lineGap 0)
 *
 *   `anchor` is the concrete font the metric-adjusted @font-face in
 *   app/fonts/fallback.css actually resolves to -- NOT the declared generic
 *   stack. CSS cannot hang size-adjust on `system-ui` or `ui-serif`, so the
 *   adjusted face has to name real fonts through local(), and the ratio has
 *   to be taken against whichever of those the platform supplies. The
 *   script measures every candidate so the spread across platforms is
 *   visible rather than assumed, and measures the declared generic stack
 *   too, to show what the swap would have cost with no adjusted face at all.
 *
 *   Note that only size-adjust depends on the fallback. Ascent and descent
 *   come from the webfont alone, so those two descriptors are exact on
 *   every platform.
 *
 *   The script then re-renders the reference string in a fallback face that
 *   carries the computed descriptors and reports the residual difference
 *   from the webfont. A residual near zero is the evidence that the swap
 *   cannot move anything; a large one means the numbers are wrong.
 *
 * Usage:
 *   node scripts/measure-fonts.mjs                 both reports, markdown
 *   node scripts/measure-fonts.mjs --json          both reports, JSON
 *   node scripts/measure-fonts.mjs --no-browser    byte table only
 *   node scripts/measure-fonts.mjs --check-linegap assert lineGap = 0
 *
 *   CHROME_PATH=/path/to/chrome overrides Chrome discovery.
 */

import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { brotliDecompressSync, gzipSync } from "node:zlib";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FONT_DIR = path.join(WEB_ROOT, "app", "fonts");

/** RC-01, ratified at Gate 2: all self-hosted woff2 files, 120 KiB. */
const FONT_BUDGET_BYTES = 120 * 1024;

/** The em size everything is measured at. Large enough that a sub-pixel
 *  difference in the ratio shows up as a readable number of pixels. */
const SIZE = 100;

/**
 * Reference strings. `prose` is the string the size adjustment is derived
 * from: it is the product's own landing and disclosure copy
 * (03-DESIGN-BRIEF.md section 1.4), so the ratio is weighted by the letter
 * distribution of the text this product actually sets. The other two are
 * reported as a sensitivity check, never used to derive a descriptor.
 */
const REFERENCE = {
  prose:
    "What should the literature settle? Generating a plan starts a billable " +
    "run. You review and edit the plan before any arXiv search or paper " +
    "reading happens.",
  alphabet: "abcdefghijklmnopqrstuvwxyz",
  data: "arXiv:2601.00001 job 7f3a9c21 0.86 0.36 2026-01-14T09:22:31Z",
};

/**
 * The three families, each pinned to the face that renders body text -- the
 * weight the fallback is standing in for while the swap is pending.
 *
 * `stack` is the fallback portion of the declared stack in app/tokens.css,
 * verbatim and with the self-hosted family removed: what the browser paints
 * before the webfont arrives.
 *
 * `localSrc` is the src list of the metric-adjusted @font-face in
 * app/fonts/fallback.css, in order. The size adjustment is taken against
 * the first entry the measuring platform resolves; the rest are measured
 * too so fonts.md can show how far the ratio moves on a platform that
 * supplies a different one.
 */
const FAMILIES = [
  {
    id: "ui",
    label: "Atkinson Hyperlegible Next",
    file: "AtkinsonHyperlegibleNext-400-700.woff2",
    weight: 400,
    style: "normal",
    stack: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
    // Arial heads the list because it is the one sans present on macOS,
    // Windows and (as metric clone Liberation Sans) most Linux images, so a
    // single size-adjust holds across all three. The system-ui faces the
    // declared stack actually prefers are probed below and cannot be named
    // in local() at all.
    localSrc: [
      "Arial", "ArialMT", "Liberation Sans", "LiberationSans",
      "Helvetica Neue", "HelveticaNeue", "Helvetica", "DejaVu Sans", "DejaVuSans",
    ],
    probes: ["SF Pro Text", "SF Pro", ".SFNS-Regular", ".AppleSystemUIFont", "Segoe UI", "SegoeUI"],
  },
  {
    id: "report",
    label: "Literata",
    file: "Literata-400-600.woff2",
    weight: 400,
    style: "normal",
    stack: 'ui-serif, Georgia, "Times New Roman", serif',
    // Georgia is what the declared stack resolves to on macOS and Windows,
    // so heading with it keeps the adjusted face metrically identical to
    // the unadjusted fallback there. Times New Roman sits last: it is 10%
    // narrower than Georgia, so it is the worst of the four to anchor on.
    localSrc: [
      "Georgia", "Liberation Serif", "LiberationSerif", "DejaVu Serif", "DejaVuSerif",
      "Times New Roman", "TimesNewRomanPSMT",
    ],
    probes: ["Times", "Times-Roman", "SF Pro Text"],
  },
  {
    id: "mono",
    label: "IBM Plex Mono",
    file: "IBMPlexMono-400.woff2",
    weight: 400,
    style: "normal",
    stack: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    // local() matches PostScript and full names, not family names, so the
    // macOS entry has to be Menlo-Regular; plain "Menlo" silently misses
    // and falls through. Courier New precedes Consolas deliberately: Plex
    // Mono's advance is 0.6em, Courier New's is 0.6em and Consolas' is
    // 0.55em, so on Windows the ugly-but-metric face is the better swap.
    localSrc: [
      "Menlo-Regular", "Menlo Regular", "DejaVu Sans Mono", "DejaVuSansMono",
      "Liberation Mono", "LiberationMono", "Courier New", "CourierNewPSMT", "Consolas",
    ],
    probes: ["Menlo", "SFMono-Regular", "SF Mono", ".SFNSMono-Regular"],
  },
];

// --------------------------------------------------------------- byte table

function byteTable() {
  const files = readdirSync(FONT_DIR)
    .filter((name) => name.endsWith(".woff2"))
    .sort();
  const faces = files.map((name) => {
    const bytes = readFileSync(path.join(FONT_DIR, name));
    return { name, raw: bytes.length, gzip: gzipSync(bytes, { level: 9 }).length };
  });
  const raw = faces.reduce((sum, face) => sum + face.raw, 0);
  const gzip = faces.reduce((sum, face) => sum + face.gzip, 0);
  return {
    faces,
    totalRaw: raw,
    totalGzip: gzip,
    budget: FONT_BUDGET_BYTES,
    headroom: FONT_BUDGET_BYTES - raw,
    withinBudget: raw <= FONT_BUDGET_BYTES,
  };
}

// ------------------------------------------------------- woff2 lineGap check

/**
 * The 63 table tags a woff2 table directory can reference by index
 * (WOFF2 specification, "Known Table Tags").
 */
const KNOWN_TAGS = [
  "cmap", "head", "hhea", "hmtx", "maxp", "name", "OS/2", "post", "cvt ", "fpgm",
  "glyf", "loca", "prep", "CFF ", "VORG", "EBDT", "EBLC", "gasp", "hdmx", "kern",
  "LTSH", "PCLT", "VDMX", "vhea", "vmtx", "BASE", "GDEF", "GPOS", "GSUB", "EBSC",
  "JSTF", "MATH", "CBDT", "CBLC", "COLR", "CPAL", "SVG ", "sbix", "acnt", "avar",
  "bdat", "bloc", "bsln", "cvar", "fdsc", "feat", "fmtx", "fvar", "gvar", "hsty",
  "just", "lcar", "mort", "morx", "opbd", "prop", "trak", "Zapf", "Silf", "Glat",
  "Gloc", "Feat", "Sill",
];

/** Reads a woff2 table directory and returns its hhea and head values. */
function readWoff2Metrics(file) {
  const buf = readFileSync(file);
  if (buf.toString("latin1", 0, 4) !== "wOF2") throw new Error(`${file} is not woff2`);
  const numTables = buf.readUInt16BE(12);

  let at = 48;
  const readBase128 = () => {
    let value = 0;
    for (let i = 0; i < 5; i += 1) {
      const byte = buf[at];
      at += 1;
      value = value * 128 + (byte & 0x7f);
      if ((byte & 0x80) === 0) return value;
    }
    throw new Error("malformed UIntBase128");
  };

  const directory = [];
  for (let i = 0; i < numTables; i += 1) {
    const flags = buf[at];
    at += 1;
    const index = flags & 0x3f;
    let tag;
    if (index === 0x3f) {
      tag = buf.toString("latin1", at, at + 4);
      at += 4;
    } else {
      tag = KNOWN_TAGS[index];
    }
    const transform = (flags >> 6) & 0x03;
    const origLength = readBase128();
    // The transformed length is present when the table is transformed:
    // glyf and loca are transformed at version 0, everything else at any
    // non-zero version.
    const transformed =
      tag === "glyf" || tag === "loca" ? transform === 0 : transform !== 0;
    const length = transformed ? readBase128() : origLength;
    directory.push({ tag, length });
  }

  const font = brotliDecompressSync(buf.subarray(at));
  const offsets = new Map();
  let cursor = 0;
  for (const entry of directory) {
    offsets.set(entry.tag, cursor);
    cursor += entry.length;
  }

  const head = offsets.get("head");
  const hhea = offsets.get("hhea");
  if (head === undefined || hhea === undefined) throw new Error(`${file}: no head/hhea`);
  return {
    unitsPerEm: font.readUInt16BE(head + 18),
    ascender: font.readInt16BE(hhea + 4),
    descender: font.readInt16BE(hhea + 6),
    lineGap: font.readInt16BE(hhea + 8),
  };
}

function lineGapReport() {
  return readdirSync(FONT_DIR)
    .filter((name) => name.endsWith(".woff2"))
    .sort()
    .map((name) => ({ name, ...readWoff2Metrics(path.join(FONT_DIR, name)) }));
}

// ------------------------------------------------------- browser measurement

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);

function findChrome() {
  const found = CHROME_CANDIDATES.find((candidate) => existsSync(candidate));
  if (!found) {
    throw new Error(
      "no Chrome found; set CHROME_PATH, or pass --no-browser for the byte table alone",
    );
  }
  return found;
}

/** Builds the measurement page. Fonts are inlined so nothing is fetched. */
function harnessHtml() {
  const input = FAMILIES.map((family) => ({
    id: family.id,
    label: family.label,
    stack: family.stack,
    weight: family.weight,
    style: family.style,
    localSrc: family.localSrc,
    probes: family.probes,
    dataUrl: `data:font/woff2;base64,${readFileSync(path.join(FONT_DIR, family.file)).toString("base64")}`,
  }));

  return `<!doctype html><meta charset="utf-8"><title>wo-02 font metrics</title>
<script id="input" type="application/json">${JSON.stringify({ input, REFERENCE, SIZE })}</script>
<script>
window.__wo02_measure = async () => {
  const cfg = JSON.parse(document.getElementById("input").textContent);
  const SIZE = cfg.SIZE;

  // Advance width of each reference string, from the canvas text metrics.
  function widths(spec) {
    const ctx = document.createElement("canvas").getContext("2d");
    ctx.font = SIZE + "px " + spec;
    // An unparseable shorthand leaves ctx.font at its default; catch that
    // rather than silently measuring the wrong font.
    if (!ctx.font.includes(String(SIZE))) throw new Error("bad font spec: " + spec);
    const result = {};
    for (const [key, text] of Object.entries(cfg.REFERENCE)) {
      result[key] = ctx.measureText(text).width;
    }
    return result;
  }

  // Baseline offset and line box height for a 'line-height: normal' line.
  function box(spec) {
    const wrap = document.createElement("div");
    wrap.style.cssText =
      "position:absolute;left:-9999px;top:0;white-space:pre;line-height:normal;" +
      "font-size:" + SIZE + "px;font-family:" + spec;
    const marker = document.createElement("span");
    marker.style.cssText = "display:inline-block;width:0;height:0;vertical-align:baseline";
    wrap.append(document.createTextNode("Hxgp"), marker);
    document.body.appendChild(wrap);
    const wrapBox = wrap.getBoundingClientRect();
    const markerBox = marker.getBoundingClientRect();
    const measured = {
      baselineFromTop: markerBox.top - wrapBox.top,
      lineBoxHeight: wrapBox.height,
    };
    wrap.remove();
    return measured;
  }

  const measure = (spec) => ({ widths: widths(spec), ...box(spec) });

  const results = [];
  for (const family of cfg.input) {
    const face = "__wo02_" + family.id;
    const loaded = new FontFace(face, "url(" + family.dataUrl + ")", {
      weight: String(family.weight),
      style: family.style,
    });
    await loaded.load();
    document.fonts.add(loaded);

    const webfont = measure('"' + face + '"');
    const fallback = measure(family.stack);

    // Each concrete font on its own, probed exactly the way the adjusted
    // face will use it: through local() in an @font-face, not through a
    // font-family name. The two are not equivalent -- local() matches
    // PostScript and full names, so "Menlo" misses where "Menlo-Regular"
    // hits, and a miss silently falls through to the next src entry.
    // A face whose src resolves to nothing renders as the platform
    // default, which is how a missing font identifies itself here.
    const absent = measure('"__wo02_absent_family__"');
    let probeSeq = 0;
    const probeOne = (name) => {
      probeSeq += 1;
      const face = "__wo02_probe_" + family.id + "_" + probeSeq;
      const sheet = document.createElement("style");
      sheet.textContent =
        "@font-face{font-family:'" + face + "';src:local('" + name + "');}";
      document.head.appendChild(sheet);
      document.fonts.load(SIZE + "px '" + face + "'");
      const probe = measure("'" + face + "', '__wo02_absent_family__'");
      return {
        ...probe,
        resolved: Math.abs(probe.widths.prose - absent.widths.prose) > 0.01,
      };
    };

    const candidates = {};
    for (const name of family.localSrc) candidates[name] = probeOne(name);
    const probes = {};
    for (const name of family.probes) probes[name] = probeOne(name);

    // The size adjustment is taken against the first candidate this
    // platform actually supplies -- the one the adjusted @font-face below
    // will resolve to.
    const anchorName = family.localSrc.find((name) => candidates[name].resolved) || null;
    if (!anchorName) throw new Error("no fallback candidate resolved for " + family.id);
    const anchor = candidates[anchorName];

    const sizeAdjust = webfont.widths.prose / anchor.widths.prose;
    const ascent = webfont.baselineFromTop / SIZE;
    const descent = (webfont.lineBoxHeight - webfont.baselineFromTop) / SIZE;
    const descriptors = {
      sizeAdjust,
      ascentOverride: ascent / sizeAdjust,
      descentOverride: descent / sizeAdjust,
      lineGapOverride: 0,
    };

    // Verification: declare the adjusted face for real and re-measure. If
    // the descriptors are right, this renders identically to the webfont.
    const adjusted = "__wo02_adjusted_" + family.id;
    const sheet = document.createElement("style");
    sheet.textContent =
      "@font-face{font-family:'" + adjusted + "';" +
      "src:" + family.localSrc.map((n) => "local('" + n + "')").join(",") + ";" +
      "size-adjust:" + (descriptors.sizeAdjust * 100).toFixed(4) + "%;" +
      "ascent-override:" + (descriptors.ascentOverride * 100).toFixed(4) + "%;" +
      "descent-override:" + (descriptors.descentOverride * 100).toFixed(4) + "%;" +
      "line-gap-override:0%;}";
    document.head.appendChild(sheet);
    // A local() face needs no fetch, so layout can use it as soon as the
    // sheet is in. Do not await document.fonts here: a face that resolves
    // to nothing would never settle and would hang the run.
    document.fonts.load(SIZE + "px '" + adjusted + "'");
    const verified = measure("'" + adjusted + "'");

    const residual = {
      widthPx: verified.widths.prose - webfont.widths.prose,
      widthPercent: (verified.widths.prose - webfont.widths.prose) / webfont.widths.prose,
      baselinePx: verified.baselineFromTop - webfont.baselineFromTop,
      lineBoxPx: verified.lineBoxHeight - webfont.lineBoxHeight,
      // What the same swap would have cost with no adjusted face at all.
      unadjustedWidthPercent:
        (fallback.widths.prose - webfont.widths.prose) / webfont.widths.prose,
      unadjustedLineBoxPx: fallback.lineBoxHeight - webfont.lineBoxHeight,
    };

    results.push({
      id: family.id,
      webfont,
      fallback,
      candidates,
      probes,
      anchorName,
      descriptors,
      residual,
      sensitivity: {
        prose: sizeAdjust,
        alphabet: webfont.widths.alphabet / anchor.widths.alphabet,
        data: webfont.widths.data / anchor.widths.data,
      },
    });
  }

  return results;
};
</script>`;
}

/**
 * Runs the harness in headless Chrome over the DevTools protocol.
 *
 * The obvious alternative -- `--dump-dom` with `--virtual-time-budget` --
 * deadlocks here: virtual time does not advance past a pending font load,
 * and a local()-only @font-face never settles. Driving the protocol
 * directly lets the run await the harness promise and nothing else.
 */
async function measureInBrowser() {
  const chrome = findChrome();
  const dir = mkdtempSync(path.join(tmpdir(), "wo02-fonts-"));
  const page = path.join(dir, "harness.html");
  writeFileSync(page, harnessHtml());

  const child = spawn(
    chrome,
    [
      "--headless",
      "--disable-gpu",
      "--no-sandbox",
      "--no-first-run",
      "--disable-extensions",
      "--force-device-scale-factor=1",
      `--user-data-dir=${path.join(dir, "profile")}`,
      "--remote-debugging-port=0",
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );

  const cleanup = () => {
    child.kill("SIGKILL");
    rmSync(dir, { recursive: true, force: true });
  };

  try {
    const endpoint = await new Promise((resolve, reject) => {
      let buffered = "";
      const timer = setTimeout(() => reject(new Error("Chrome did not announce a DevTools endpoint")), 30000);
      child.stderr.on("data", (chunk) => {
        buffered += chunk;
        const found = /DevTools listening on (ws:\/\/\S+)/.exec(buffered);
        if (found) {
          clearTimeout(timer);
          resolve(found[1]);
        }
      });
      child.on("exit", (code) => {
        clearTimeout(timer);
        reject(new Error(`Chrome exited early (${code}): ${buffered.slice(-500)}`));
      });
    });

    const session = await openSession(endpoint);
    try {
      const { targetId } = await session.send("Target.createTarget", { url: `file://${page}` });
      const { sessionId } = await session.send("Target.attachToTarget", { targetId, flatten: true });

      // file:// has no load ordering guarantees worth trusting; poll for the
      // harness function instead of racing the load event.
      const deadline = Date.now() + 30000;
      for (;;) {
        const probe = await session.send(
          "Runtime.evaluate",
          { expression: "typeof window.__wo02_measure", returnByValue: true },
          sessionId,
        );
        if (probe.result?.value === "function") break;
        if (Date.now() > deadline) throw new Error("harness never defined __wo02_measure");
        await new Promise((resolve) => setTimeout(resolve, 50));
      }

      const evaluated = await session.send(
        "Runtime.evaluate",
        {
          expression: "window.__wo02_measure()",
          awaitPromise: true,
          returnByValue: true,
        },
        sessionId,
      );
      if (evaluated.exceptionDetails) {
        throw new Error(
          `harness threw: ${evaluated.exceptionDetails.exception?.description ?? JSON.stringify(evaluated.exceptionDetails)}`,
        );
      }
      return { chrome, version: chromeVersion(chrome), raw: evaluated.result.value };
    } finally {
      session.close();
    }
  } finally {
    cleanup();
  }
}

/** Minimal DevTools protocol client over the WebSocket Node 22 ships. */
function openSession(endpoint) {
  const socket = new WebSocket(endpoint);
  const pending = new Map();
  let nextId = 0;

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const waiting = pending.get(message.id);
    if (!waiting) return;
    pending.delete(message.id);
    if (message.error) waiting.reject(new Error(`${message.error.message} (${message.error.code})`));
    else waiting.resolve(message.result);
  });

  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const id = (nextId += 1);
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
    });

  return new Promise((resolve, reject) => {
    socket.addEventListener("open", () => resolve({ send, close: () => socket.close() }));
    socket.addEventListener("error", () => reject(new Error(`cannot connect to ${endpoint}`)));
  });
}

function chromeVersion(chrome) {
  return execFileSync(chrome, ["--version"], { encoding: "utf8" }).trim();
}

// --------------------------------------------------------------- presentation

const pct = (value) => `${(value * 100).toFixed(2)}%`;
const num = (value) => value.toLocaleString("en-US");

function markdown(report) {
  const lines = [];
  const { bytes } = report;

  lines.push("### Per-face byte table", "");
  lines.push("| File | Raw (B) | gzip (B) |", "|---|---:|---:|");
  for (const face of bytes.faces) {
    lines.push(`| \`${face.name}\` | ${num(face.raw)} | ${num(face.gzip)} |`);
  }
  lines.push(`| **Total** | **${num(bytes.totalRaw)}** | **${num(bytes.totalGzip)}** |`);
  lines.push(`| Budget (RC-01) | ${num(bytes.budget)} | — |`);
  lines.push(
    `| Headroom | ${bytes.headroom >= 0 ? "+" : ""}${num(bytes.headroom)} | — |`,
    "",
    bytes.withinBudget
      ? `Within budget: ${((bytes.totalRaw / bytes.budget) * 100).toFixed(1)}% of ${num(bytes.budget)} B.`
      : `**OVER BUDGET by ${num(-bytes.headroom)} B.**`,
    "",
  );

  if (report.lineGap) {
    lines.push("### hhea line gap, read from the committed woff2 files", "");
    lines.push("| File | unitsPerEm | ascender | descender | lineGap |", "|---|---:|---:|---:|---:|");
    for (const face of report.lineGap) {
      lines.push(
        `| \`${face.name}\` | ${face.unitsPerEm} | ${face.ascender} | ${face.descender} | ${face.lineGap} |`,
      );
    }
    lines.push("");
  }

  if (report.metrics) {
    const labelOf = (id) => FAMILIES.find((family) => family.id === id).label;

    lines.push("### Measured fallback metrics", "");
    lines.push(`Measured in ${report.chrome.version} on ${report.chrome.platform}, at ${SIZE}px.`, "");
    lines.push(
      "| Family | Adjustment anchor | `size-adjust` | `ascent-override` | `descent-override` | `line-gap-override` |",
      "|---|---|---:|---:|---:|---:|",
    );
    for (const family of report.metrics) {
      const d = family.descriptors;
      lines.push(
        `| ${labelOf(family.id)} | \`local("${family.anchorName}")\` | ${pct(d.sizeAdjust)} | ` +
          `${pct(d.ascentOverride)} | ${pct(d.descentOverride)} | ${pct(d.lineGapOverride)} |`,
      );
    }
    lines.push("");

    lines.push("### Verification: the adjusted face re-measured against the webfont", "");
    lines.push(
      "Residual is the adjusted fallback minus the webfont, laying out the same reference string. " +
        "The last two columns are what the same swap would have cost with no adjusted face.",
      "",
      "| Family | Residual width | Residual baseline | Residual line box | Unadjusted width | Unadjusted line box |",
      "|---|---:|---:|---:|---:|---:|",
    );
    for (const family of report.metrics) {
      const r = family.residual;
      lines.push(
        `| ${labelOf(family.id)} | ${r.widthPx.toFixed(2)} px (${pct(r.widthPercent)}) | ` +
          `${r.baselinePx.toFixed(2)} px | ${r.lineBoxPx.toFixed(2)} px | ` +
          `${pct(r.unadjustedWidthPercent)} | ${r.unadjustedLineBoxPx.toFixed(2)} px |`,
      );
    }
    lines.push("");

    lines.push("### Size-adjust sensitivity to the reference string", "");
    lines.push(
      "The descriptor is derived from `prose`; the other two say how much the ratio would move had a different string been chosen.",
      "",
      "| Family | prose (used) | alphabet | data strings |",
      "|---|---:|---:|---:|",
    );
    for (const family of report.metrics) {
      lines.push(
        `| ${labelOf(family.id)} | ${pct(family.sensitivity.prose)} | ` +
          `${pct(family.sensitivity.alphabet)} | ${pct(family.sensitivity.data)} |`,
      );
    }
    lines.push("");

    lines.push("### Fallback candidates, measured individually", "");
    lines.push(
      "Prose advance width at 100px. `size-adjust here` is the descriptor that candidate would have " +
        "produced -- the cross-platform spread. Probes are fonts that were tried and are not nameable " +
        "or not installed.",
      "",
      "| Family | Font | Role | Resolved | Prose width (px) | size-adjust here |",
      "|---|---|---|---|---:|---:|",
    );
    for (const family of report.metrics) {
      const label = labelOf(family.id);
      const webfontWidth = family.webfont.widths.prose;
      lines.push(
        `| ${label} | *(declared generic stack)* | what renders with no adjusted face | — | ` +
          `${family.fallback.widths.prose.toFixed(2)} | ${pct(webfontWidth / family.fallback.widths.prose)} |`,
      );
      const rows = [
        ...Object.entries(family.candidates).map((entry) => [...entry, "src candidate"]),
        ...Object.entries(family.probes).map((entry) => [...entry, "probe"]),
      ];
      for (const [name, data, role] of rows) {
        lines.push(
          `| ${label} | \`${name}\`${name === family.anchorName ? " **(anchor)**" : ""} | ${role} | ` +
            `${data.resolved ? "yes" : "no"} | ${data.resolved ? data.widths.prose.toFixed(2) : "—"} | ` +
            `${data.resolved ? pct(webfontWidth / data.widths.prose) : "—"} |`,
        );
      }
    }
    lines.push("");

    lines.push("### The @font-face block these numbers produce", "");
    lines.push("```css");
    for (const family of report.metrics) {
      const declared = FAMILIES.find((f) => f.id === family.id);
      const d = family.descriptors;
      lines.push(
        `@font-face {`,
        `  font-family: "${declared.label} Fallback";`,
        `  src: ${declared.localSrc.map((name) => `local("${name}")`).join(", ")};`,
        `  size-adjust: ${(d.sizeAdjust * 100).toFixed(2)}%;`,
        `  ascent-override: ${(d.ascentOverride * 100).toFixed(2)}%;`,
        `  descent-override: ${(d.descentOverride * 100).toFixed(2)}%;`,
        `  line-gap-override: 0%;`,
        `}`,
      );
    }
    lines.push("```", "");
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------- main

const argv = new Set(process.argv.slice(2));
const report = { bytes: byteTable() };

if (argv.has("--check-linegap") || !argv.has("--no-browser")) {
  report.lineGap = lineGapReport();
  const offenders = report.lineGap.filter((face) => face.lineGap !== 0);
  if (offenders.length > 0) {
    console.error(
      "lineGap is not 0 for: " +
        offenders.map((face) => face.name).join(", ") +
        "\nThe two-unknown solve in this script assumes no leading; rework it before trusting the overrides.",
    );
    process.exitCode = 1;
  }
}

if (!argv.has("--no-browser")) {
  const measured = await measureInBrowser();
  report.chrome = { path: measured.chrome, version: measured.version, platform: process.platform };
  report.reference = REFERENCE;
  report.measuredAtPx = SIZE;
  report.metrics = measured.raw;
}

if (argv.has("--json")) {
  console.log(JSON.stringify(report, null, 2));
} else {
  console.log(markdown(report));
}

if (!report.bytes.withinBudget) process.exitCode = 1;
