/**
 * WO-16 criterion 8 — "Nothing is transmitted anywhere; a test asserts no
 * `fetch`/`sendBeacon` to any non-`/api` origin exists in the module
 * graph."
 *
 * 04 §9.2 opens with the reason: "adding a telemetry route to FastAPI would
 * breach the frozen-backend rule, and shipping a private research
 * workspace's queries to a third party is not acceptable for this product."
 * That is a claim about the whole client, not about this work order's
 * files, so this test is scoped to the whole client — every `.ts`/`.tsx`
 * under `app/`, `components/` and `lib/`.
 *
 * ONE EXCLUSION, NAMED AND ASSERTED. `app/api/[...path]/route.ts` is the
 * Next.js server's own proxy to FastAPI: it runs in the Node runtime on the
 * server this repository already deploys (`docker-compose.yml:111-140`), it
 * is the sanctioned egress, and it is not in any browser bundle. It is
 * excluded by name, its existence is asserted, and the test asserts that it
 * is the ONLY exclusion — so a second server file cannot quietly join it.
 *
 * The scan runs over comment-stripped source, because several of the files
 * it reads DOCUMENT the prohibition (this one included), and a scanner that
 * failed on its own rationale would be one nobody could write.
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { API_BASE } from "@/lib/api";

import { WEB_ROOT, sourceFilesUnder, stripComments } from "./support/source";

/** The server-side proxy. Node runtime, our own server, never bundled. */
const SERVER_PROXY = path.join(WEB_ROOT, "app", "api", "[...path]", "route.ts");

const CLIENT_FILES = ["app", "components", "lib"]
  .flatMap((dir) => sourceFilesUnder(path.join(WEB_ROOT, dir)))
  .filter((file) => file !== SERVER_PROXY);

function client(file: string): { file: string; source: string } {
  return { file: path.relative(WEB_ROOT, file), source: stripComments(readFileSync(file, "utf8")) };
}

const SOURCES = CLIENT_FILES.map(client);

/**
 * Every way a browser can send bytes somewhere without `fetch`.
 *
 * `sendBeacon` is the one 04 §9.2 names, because it is what an analytics
 * SDK reaches for on `visibilitychange`; the rest are the alternatives a
 * later change would reach for once it was blocked.
 */
const TRANSMITTERS: readonly [string, RegExp][] = [
  ["sendBeacon", /\bsendBeacon\b/],
  ["XMLHttpRequest", /\bXMLHttpRequest\b/],
  ["WebSocket", /\bnew\s+WebSocket\b/],
  ["Image beacon", /\bnew\s+Image\b/],
  ["RTCPeerConnection", /\bRTCPeerConnection\b/],
  ["importScripts", /\bimportScripts\b/],
  ["navigator.connection upload", /\bnavigator\.sendBeacon\b/],
  ["form.submit", /\bdocument\.forms\b/],
];

describe("criterion 8 — nothing transmits", () => {
  it("reads a real client tree, and excludes exactly one server file", () => {
    expect(SOURCES.length).toBeGreaterThan(30);
    expect(existsSync(SERVER_PROXY), "the named exclusion must exist").toBe(true);
    // Every OTHER route handler would also be server code. There are none,
    // so the exclusion list is one file long and this is what keeps it so.
    const handlers = sourceFilesUnder(path.join(WEB_ROOT, "app")).filter((file) =>
      /(^|[\\/])route\.tsx?$/.test(file),
    );
    expect(handlers).toEqual([SERVER_PROXY]);
  });

  it.each(TRANSMITTERS)("no client module uses %s", (_name, pattern) => {
    const offenders = SOURCES.filter((entry) => pattern.test(entry.source));
    expect(offenders.map((entry) => entry.file)).toEqual([]);
  });

  it("has no absolute URL literal in any client module", () => {
    // A third-party endpoint has to be written down somewhere, and this is
    // where it would be. The allow-list is empty on purpose.
    const offenders = SOURCES.flatMap((entry) =>
      [...entry.source.matchAll(/["'`](https?:\/\/[^"'`]*)["'`]/g)].map((match) => ({
        file: entry.file,
        url: match[1] as string,
      })),
    );
    expect(offenders).toEqual([]);
  });

  it("calls fetch from exactly one module, and only at /api", () => {
    const callers = SOURCES.filter((entry) => /\bfetch\s*\(/.test(entry.source));
    expect(callers.map((entry) => entry.file)).toEqual(["lib/api/client.ts"]);

    const source = callers[0]?.source ?? "";
    // Every fetch target in that module is `${API_BASE}${path}`, and
    // API_BASE is the same-origin proxy prefix.
    expect(API_BASE).toBe("/api");
    for (const match of source.matchAll(/\bfetch\s*\(\s*([^,)]+)/g)) {
      expect((match[1] as string).trim()).toBe("`${API_BASE}${path}`");
    }
  });

  it("opens an EventSource only at an /api path", () => {
    const openers = SOURCES.filter((entry) => /\bnew\s+EventSource\b/.test(entry.source));
    expect(openers.map((entry) => entry.file)).toEqual(["lib/job/useJobStream.ts"]);
    // The URL comes from `streamUrl`, which `lib/api/client.ts` builds from
    // API_BASE; the module itself writes no origin.
    for (const entry of openers) {
      expect(entry.source).not.toMatch(/new\s+EventSource\s*\(\s*["'`]https?:/);
    }
  });

  it("declares no analytics, error-tracking or RUM package", () => {
    const packageJson = JSON.parse(
      readFileSync(path.join(WEB_ROOT, "package.json"), "utf8"),
    ) as { dependencies: Record<string, string>; devDependencies: Record<string, string> };
    const names = [
      ...Object.keys(packageJson.dependencies),
      ...Object.keys(packageJson.devDependencies),
    ];
    // 04 §9.2 item 4's "explicitly not done" list, as a package check.
    const banned =
      /sentry|datadog|newrelic|new-relic|bugsnag|rollbar|logrocket|fullstory|amplitude|mixpanel|segment|posthog|hotjar|analytics|@vercel\/speed-insights/i;
    expect(names.filter((name) => banned.test(name))).toEqual([]);
  });
});

describe("criterion 8 — the diagnostics modules in particular", () => {
  const DIAGNOSTICS_FILES = sourceFilesUnder(path.join(WEB_ROOT, "lib", "diagnostics")).map(
    client,
  );

  it("reads the whole directory", () => {
    expect(DIAGNOSTICS_FILES.length).toBeGreaterThan(3);
  });

  it("contains no network call of any kind", () => {
    for (const entry of DIAGNOSTICS_FILES) {
      expect(/\bfetch\s*\(/.test(entry.source), entry.file).toBe(false);
      expect(/\bEventSource\b/.test(entry.source), entry.file).toBe(false);
      expect(/\bsendBeacon\b/.test(entry.source), entry.file).toBe(false);
      expect(/\bnavigator\./.test(entry.source), entry.file).toBe(false);
    }
  });

  it("the surface's only outward call is the clipboard, which is local", () => {
    const source = stripComments(
      readFileSync(path.join(WEB_ROOT, "components", "patterns", "Diagnostics.tsx"), "utf8"),
    );
    const navigatorCalls = [...source.matchAll(/\bnavigator\.(\w+)/g)].map(
      (match) => match[1] as string,
    );
    expect([...new Set(navigatorCalls)]).toEqual(["clipboard"]);
    expect(/\bfetch\s*\(/.test(source)).toBe(false);
  });
});
