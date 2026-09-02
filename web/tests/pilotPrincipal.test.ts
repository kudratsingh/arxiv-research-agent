/**
 * WO-W17 criteria 1, 2 and 4 — the pilot mode at MT-01 seam S1.
 *
 * A NEW FILE, BECAUSE CRITERION 1 IS ABOUT AN OLD ONE. The card's first
 * acceptance criterion is that with the mode off `resolveUpstreamPrincipal`
 * is byte-identical, "proved by leaving `web/tests/principal.test.ts`'s
 * existing tests untouched". So that file is not edited and this one carries
 * everything new — including the mode-off assertions that file cannot make,
 * because it does not know the mode exists.
 *
 * WHAT THE THREE SUITES BELOW CORRESPOND TO.
 *
 *   §1  Mode off: the seam is what it was, and the new code emits nothing.
 *   §2  Mode on: every guard, each refused in its own right, plus the
 *       control case that stops the refusals from being vacuous.
 *   §3  The key never leaves the server: the log, the response, the shipped
 *       tree, and the built client bundle.
 *
 * THE REAL ROUTE HANDLER IS DRIVEN, NOT A MOCK OF IT. Several assertions
 * import `GET` from `app/api/[...path]/route.ts` — the same export the frozen
 * `apiProxyRoute.test.ts` imports — because the claim is about what the PROXY
 * does with a refusal, and a test that called the resolver directly would
 * prove the resolver refuses while saying nothing about whether the key was
 * sent anyway.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/[...path]/route";
import {
  PrincipalUnresolvedError,
  SHARED_PRINCIPAL_KEY_ID,
  resolveUpstreamPrincipal,
} from "@/lib/server/principal";
import {
  PILOT_EDGE_KEY_HEADER,
  PILOT_EDGE_SECRET_ENV,
  PILOT_LOG_EVENT,
  PILOT_MAP_ENV,
  PILOT_MAX_PRINCIPALS,
  PILOT_MODE_ENV,
  PILOT_USER_HEADER,
  formatPilotLogLine,
  readPilotConfig,
  resolvePilotPrincipal,
} from "@/lib/server/pilot";
import { E2E_PILOTS, E2E_PILOT_EDGE_SECRET } from "../e2e/support/env";

const WEB_ROOT = path.resolve(__dirname, "..");

/** A well-formed edge secret. Longer than the 32-character floor. */
const EDGE_SECRET = "0123456789abcdef0123456789abcdef0123";

/** Two pilots, the shape `deploy/pilot/env.example` documents. */
const MAP = JSON.stringify({
  "pilot-ada": { key_id: "pilot-ada-2026-09", api_key: "sk_ada_secret" },
  "pilot-bo": { key_id: "pilot-bo-2026-09", api_key: "sk_bo_secret" },
});

const originalEnv = {
  apiKey: process.env.ARXIV_API_KEY,
  base: process.env.API_INTERNAL_BASE,
  mode: process.env[PILOT_MODE_ENV],
  map: process.env[PILOT_MAP_ENV],
  edgeSecret: process.env[PILOT_EDGE_SECRET_ENV],
};

/** Every line the code under test wrote to stdout during one test. */
let written: string[] = [];

function restore(name: string, value: string | undefined): void {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
}

/** Turn the pilot mode on with a valid configuration. */
function enablePilotMode(): void {
  delete process.env.ARXIV_API_KEY;
  process.env[PILOT_MODE_ENV] = "on";
  process.env[PILOT_MAP_ENV] = MAP;
  process.env[PILOT_EDGE_SECRET_ENV] = EDGE_SECRET;
}

/** A request as the edge would forward it. */
function fromEdge(
  username: string,
  edgeKey: string = EDGE_SECRET,
): Request {
  return new Request("http://web.local/api/conversations", {
    headers: {
      [PILOT_USER_HEADER]: username,
      [PILOT_EDGE_KEY_HEADER]: edgeKey,
    },
  });
}

function context(...segments: string[]) {
  return { params: Promise.resolve({ path: segments }) };
}

/** The pilot resolver's own log lines, parsed. */
function pilotLines(): Record<string, unknown>[] {
  return written
    .filter((line) => line.includes(PILOT_LOG_EVENT))
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

beforeEach(() => {
  written = [];
  vi.spyOn(process.stdout, "write").mockImplementation(((chunk: unknown) => {
    written.push(String(chunk));
    return true;
  }) as typeof process.stdout.write);
  process.env.API_INTERNAL_BASE = "http://app:8000";
  delete process.env[PILOT_MODE_ENV];
  delete process.env[PILOT_MAP_ENV];
  delete process.env[PILOT_EDGE_SECRET_ENV];
});

afterEach(() => {
  vi.restoreAllMocks();
  restore("ARXIV_API_KEY", originalEnv.apiKey);
  restore("API_INTERNAL_BASE", originalEnv.base);
  restore(PILOT_MODE_ENV, originalEnv.mode);
  restore(PILOT_MAP_ENV, originalEnv.map);
  restore(PILOT_EDGE_SECRET_ENV, originalEnv.edgeSecret);
});

// ----------------------------------------------------- §1 the mode is off

describe("criterion 1 — with the mode off, the seam is what it was", () => {
  it("returns the shared principal, and ignores the pilot headers entirely", async () => {
    process.env.ARXIV_API_KEY = "server-only-secret";
    // A request carrying BOTH pilot headers, with a username that is in the
    // map. Mode off means the map is not consulted, so this must resolve to
    // the shared principal exactly as a bare request does — anything else
    // would be the mode enabling itself by inference, which is the thing
    // MT-01's threat T6 forbids.
    await expect(
      resolveUpstreamPrincipal(fromEdge("pilot-ada")),
    ).resolves.toEqual({
      keyId: SHARED_PRINCIPAL_KEY_ID,
      apiKey: "server-only-secret",
    });
  });

  it("treats an explicit `off`, an empty value and whitespace as off", async () => {
    process.env.ARXIV_API_KEY = "server-only-secret";
    for (const value of ["off", "", "   "]) {
      process.env[PILOT_MODE_ENV] = value;
      await expect(
        resolveUpstreamPrincipal(fromEdge("pilot-ada")),
      ).resolves.toEqual({
        keyId: SHARED_PRINCIPAL_KEY_ID,
        apiKey: "server-only-secret",
      });
    }
  });

  it("still returns null in the auth-off configuration", async () => {
    delete process.env.ARXIV_API_KEY;
    await expect(
      resolveUpstreamPrincipal(fromEdge("pilot-ada")),
    ).resolves.toBeNull();
  });

  it("writes nothing to stdout, so the log is byte-identical too", async () => {
    process.env.ARXIV_API_KEY = "server-only-secret";
    await resolveUpstreamPrincipal(fromEdge("pilot-ada"));
    // Not "no pilot line" — no line at all. The resolver is on the hot path
    // of every proxied request, and a new line per request would change what
    // `ci/proxy-log-sample.txt` documents for every deployment on `main`.
    expect(written).toEqual([]);
  });

  it("refuses to serve when the mode value is neither on nor off", async () => {
    // `true`, `1` and `yes` are the values an operator reaches for, and every
    // one of them is a belief that the pilot mapping is live. Treating them
    // as "off" would be silent and safe; refusing is loud and safe.
    process.env.ARXIV_API_KEY = "server-only-secret";
    for (const value of ["true", "1", "yes", "ON", "enabled"]) {
      process.env[PILOT_MODE_ENV] = value;
      await expect(
        resolveUpstreamPrincipal(fromEdge("pilot-ada")),
      ).rejects.toThrow(PrincipalUnresolvedError);
    }
  });
});

// ------------------------------------------------------ §2 the mode is on

describe("criterion 2 — the topology guard", () => {
  beforeEach(enablePilotMode);

  it("maps an edge-forwarded username to that pilot's key", async () => {
    // The control for every refusal below. Without it they would all pass
    // against a resolver that refused everything.
    await expect(
      resolveUpstreamPrincipal(fromEdge("pilot-ada")),
    ).resolves.toEqual({ keyId: "pilot-ada-2026-09", apiKey: "sk_ada_secret" });
    await expect(
      resolveUpstreamPrincipal(fromEdge("pilot-bo")),
    ).resolves.toEqual({ keyId: "pilot-bo-2026-09", apiKey: "sk_bo_secret" });
  });

  it("refuses a username header on a request that did not come through the edge", async () => {
    const spoofed = new Request("http://web.local/api/conversations", {
      headers: { [PILOT_USER_HEADER]: "pilot-ada" },
    });
    await expect(resolveUpstreamPrincipal(spoofed)).rejects.toMatchObject({
      fault: "untrusted_topology",
    });
  });

  it("refuses a wrong edge key, including one that differs only in length", async () => {
    for (const key of [
      `${EDGE_SECRET}x`,
      EDGE_SECRET.slice(0, -1),
      "",
      "0000000000000000000000000000000000",
    ]) {
      await expect(
        resolveUpstreamPrincipal(fromEdge("pilot-ada", key)),
      ).rejects.toMatchObject({ fault: "untrusted_topology" });
    }
  });

  it("never names the username when the topology guard failed", async () => {
    const spoofed = new Request("http://web.local/api/conversations", {
      headers: { [PILOT_USER_HEADER]: "an-attacker-chosen-value" },
    });
    await expect(resolveUpstreamPrincipal(spoofed)).rejects.toThrow();
    // The header is attacker-controlled on exactly this path, so it is the
    // one value that must not reach a log line.
    expect(written.join("")).not.toContain("an-attacker-chosen-value");
    expect(pilotLines()).toEqual([
      { event: PILOT_LOG_EVENT, outcome: "untrusted_topology" },
    ]);
  });

  it("refuses a missing or malformed username from a verified edge", async () => {
    await expect(resolveUpstreamPrincipal(fromEdge("   "))).rejects.toMatchObject(
      { fault: "username_missing" },
    );
    for (const bad of ["-leading", "trailing-", "has space", "a".repeat(65)]) {
      await expect(resolveUpstreamPrincipal(fromEdge(bad))).rejects.toMatchObject(
        { fault: "username_invalid" },
      );
    }
  });

  it("maps an unknown username to NO key — 503, never the shared one", async () => {
    await expect(
      resolveUpstreamPrincipal(fromEdge("pilot-nobody")),
    ).rejects.toMatchObject({ fault: "unknown_username" });
  });

  it("is total: an `off` config handed straight to the resolver answers, and answers no", () => {
    // Unreachable through `resolveUpstreamPrincipal`, which short-circuits the
    // off path before calling here — which is exactly why it is pinned. The
    // function's contract is that it always *answers*, so a future second
    // caller cannot get an exception out of it, and the answer it gives for a
    // configuration that never enabled the mode is a refusal rather than a
    // principal.
    expect(
      resolvePilotPrincipal({ mode: "off" }, fromEdge("pilot-ada")),
    ).toEqual({ ok: false, fault: "untrusted_topology", username: null });
  });
});

describe("criterion 2 — an ambiguous configuration refuses to serve", () => {
  it("refuses when the map and the shared key are both configured", async () => {
    enablePilotMode();
    process.env.ARXIV_API_KEY = "server-only-secret";
    // The whole point: a valid, mapped username, presented through a verified
    // edge, and the answer is still a refusal — because a deployment with two
    // configured answers to "whose credential is this" has none.
    await expect(
      resolveUpstreamPrincipal(fromEdge("pilot-ada")),
    ).rejects.toMatchObject({ fault: "shared_key_also_set" });
  });

  it("never falls back to the shared key on any configuration fault", async () => {
    process.env.ARXIV_API_KEY = "server-only-secret";
    process.env[PILOT_MODE_ENV] = "on";
    process.env[PILOT_EDGE_SECRET_ENV] = EDGE_SECRET;
    let sentKey: string | null = "not-called";
    globalThis.fetch = vi.fn(async (_input, init) => {
      sentKey = new Headers(init?.headers).get("X-API-Key");
      return Response.json({ status: "ok" });
    }) as unknown as typeof fetch;

    const response = await GET(fromEdge("pilot-ada"), context("conversations"));

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: "pilot_principal_unresolved",
    });
    // The upstream was never called, so the shared key was never sent — the
    // assertion that "fails closed" means closed rather than degraded.
    expect(sentKey).toBe("not-called");
  });

  it("refuses every shape of broken configuration", () => {
    const cases: [string, string, string][] = [
      // [mode, map, edgeSecret] -> fault
      ["on", MAP, ""],
      ["on", MAP, "too-short"],
      ["on", "", EDGE_SECRET],
      ["on", "{not json", EDGE_SECRET],
      ["on", "[]", EDGE_SECRET],
      ["on", '"a string"', EDGE_SECRET],
      ["on", "{}", EDGE_SECRET],
      ["on", '{"Bad Name":{"key_id":"k","api_key":"s"}}', EDGE_SECRET],
      ["on", '{"ok":"just-a-string"}', EDGE_SECRET],
      ["on", '{"ok":{"key_id":"k"}}', EDGE_SECRET],
      ["on", '{"ok":{"key_id":"","api_key":"s"}}', EDGE_SECRET],
      ["on", '{"a":{"key_id":"k1","api_key":"s"},"b":{"key_id":"k2","api_key":"s"}}', EDGE_SECRET],
      ["on", '{"a":{"key_id":"k","api_key":"s1"},"b":{"key_id":"k","api_key":"s2"}}', EDGE_SECRET],
    ];
    const faults = cases.map(
      ([mode, map, edgeSecret]) =>
        readPilotConfig({ mode, map, edgeSecret }, undefined).mode ===
        "misconfigured"
          ? (
              readPilotConfig({ mode, map, edgeSecret }, undefined) as {
                fault: string;
              }
            ).fault
          : "SERVED",
    );
    expect(faults).toEqual([
      "edge_secret_missing",
      "edge_secret_too_short",
      "map_missing",
      "map_unparseable",
      "map_not_an_object",
      "map_not_an_object",
      "map_empty",
      "map_username_invalid",
      "map_entry_invalid",
      "map_entry_invalid",
      "map_entry_invalid",
      "map_duplicate_api_key",
      "map_duplicate_key_id",
    ]);
  });

  it("refuses a sixth pilot — SR-09's cohort ceiling, in code", () => {
    const oversized: Record<string, unknown> = {};
    for (let i = 0; i <= PILOT_MAX_PRINCIPALS; i += 1) {
      oversized[`pilot-${i}`] = { key_id: `k${i}`, api_key: `s${i}` };
    }
    expect(
      readPilotConfig(
        {
          mode: "on",
          map: JSON.stringify(oversized),
          edgeSecret: EDGE_SECRET,
        },
        undefined,
      ),
    ).toEqual({ mode: "misconfigured", fault: "map_too_large" });
    // Exactly five is fine — the ceiling is a ceiling, not an off-by-one.
    delete oversized[`pilot-${PILOT_MAX_PRINCIPALS}`];
    expect(
      readPilotConfig(
        {
          mode: "on",
          map: JSON.stringify(oversized),
          edgeSecret: EDGE_SECRET,
        },
        undefined,
      ).mode,
    ).toBe("on");
  });

  it("never quotes the map in a fault, however broken the map is", () => {
    const config = readPilotConfig(
      {
        mode: "on",
        map: '{"pilot-ada": {"api_key": "sk_a_very_secret_value" ',
        edgeSecret: EDGE_SECRET,
      },
      undefined,
    );
    // `JSON.parse`'s SyntaxError quotes the region it failed on, and the
    // region is a table of API keys. The fault is an enum member instead.
    expect(config).toEqual({ mode: "misconfigured", fault: "map_unparseable" });
    expect(JSON.stringify(config)).not.toContain("sk_a_very_secret_value");
  });
});

describe("criterion 2 — the proxy answers 503 and sends no key", () => {
  beforeEach(enablePilotMode);

  it("forwards a mapped pilot's key upstream, and only that pilot's", async () => {
    const sent: string[] = [];
    globalThis.fetch = vi.fn(async (_input, init) => {
      sent.push(new Headers(init?.headers).get("X-API-Key") ?? "");
      return Response.json({ conversations: [] });
    }) as unknown as typeof fetch;

    await GET(fromEdge("pilot-ada"), context("conversations"));
    await GET(fromEdge("pilot-bo"), context("conversations"));

    expect(sent).toEqual(["sk_ada_secret", "sk_bo_secret"]);
  });

  it("answers an unknown username 503 without calling upstream", async () => {
    const fetchSpy = vi.fn(async () => Response.json({}));
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const response = await GET(
      fromEdge("pilot-nobody"),
      context("conversations"),
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: "pilot_principal_unresolved",
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("says the same thing for an unknown user and a broken deployment", async () => {
    globalThis.fetch = vi.fn(async () =>
      Response.json({}),
    ) as unknown as typeof fetch;
    const unknown = await GET(
      fromEdge("pilot-nobody"),
      context("conversations"),
    );
    process.env[PILOT_MAP_ENV] = "{not json";
    const broken = await GET(fromEdge("pilot-ada"), context("conversations"));

    // Identical from outside: an attacker learns nothing about whether a
    // username exists. Which one it was is in the resolver's log line.
    expect(unknown.status).toBe(broken.status);
    await expect(unknown.json()).resolves.toEqual(await broken.json());
  });

  it("logs the refusal as `principal_unresolved`, not as `misconfigured`", async () => {
    globalThis.fetch = vi.fn(async () =>
      Response.json({}),
    ) as unknown as typeof fetch;
    await GET(fromEdge("pilot-nobody"), context("conversations"));

    const proxy = written
      .filter((line) => line.includes("api_proxy_request"))
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    expect(proxy).toMatchObject([
      { status: 503, outcome: "principal_unresolved", bytes: 0 },
    ]);
  });
});

// ------------------------------------------- §3 the key never leaves here

describe("criterion 4 — the key never reaches a log, a response, or a bundle", () => {
  beforeEach(enablePilotMode);

  it("logs the username and the key_id, and never the key", async () => {
    await resolveUpstreamPrincipal(fromEdge("pilot-ada"));
    expect(pilotLines()).toEqual([
      {
        event: PILOT_LOG_EVENT,
        outcome: "resolved",
        user: "pilot-ada",
        key_id: "pilot-ada-2026-09",
      },
    ]);
    expect(written.join("")).not.toContain("sk_ada_secret");
  });

  it("names the username on an unknown-user refusal, and nothing else", async () => {
    await expect(
      resolveUpstreamPrincipal(fromEdge("pilot-nobody")),
    ).rejects.toThrow();
    expect(pilotLines()).toEqual([
      {
        event: PILOT_LOG_EVENT,
        outcome: "unknown_username",
        user: "pilot-nobody",
      },
    ]);
  });

  it("emits only keys from a fixed allowlist, whatever happened", () => {
    // An allowlist of KEYS, not a search for known secrets: a field added
    // later cannot smuggle a value in without failing here first.
    const shapes = [
      formatPilotLogLine({
        outcome: "resolved",
        username: "pilot-ada",
        keyId: "pilot-ada-2026-09",
      }),
      formatPilotLogLine({
        outcome: "untrusted_topology",
        username: null,
        keyId: null,
      }),
    ];
    for (const line of shapes) {
      const keys = Object.keys(JSON.parse(line) as Record<string, unknown>);
      expect(keys.every((key) => ["event", "outcome", "user", "key_id"].includes(key))).toBe(
        true,
      );
    }
  });

  it("puts no key in the response body, the headers, or any emitted line", async () => {
    globalThis.fetch = vi.fn(
      async () => Response.json({ detail: "invalid_api_key" }, { status: 401 }),
    ) as unknown as typeof fetch;

    const response = await GET(fromEdge("pilot-ada"), context("conversations"));
    const rendered = [
      await response.text(),
      JSON.stringify([...response.headers.entries()]),
      written.join(""),
    ].join("\n");

    for (const secret of ["sk_ada_secret", "sk_bo_secret", EDGE_SECRET]) {
      expect(rendered).not.toContain(secret);
    }
  });

  it("is reachable from two modules, and both of them are under lib/server/", () => {
    // WO-W17b ADDED THE SECOND, AND IT IS NOT A SECOND CREDENTIAL PATH.
    // `lib/server/identity.ts` calls the same parser and the same resolver to
    // answer one question — who did the edge authenticate — and returns a
    // `WorkspaceIdentity`, which has no field for a key, a key id or a fault.
    // The credential half is still `principal.ts`, which is still the only
    // module that reads `ARXIV_API_KEY` (`tests/principal.test.ts`) and is
    // still imported only by the proxy route.
    const importers = walk(WEB_ROOT).filter((file) =>
      /from "@\/lib\/server\/pilot"/.test(code(file)),
    );
    expect(importers.map((file) => path.relative(WEB_ROOT, file)).sort()).toEqual([
      "lib/server/identity.ts",
      "lib/server/principal.ts",
    ]);
  });

  it("reaches the browser through two server layouts and nothing else", () => {
    // The identity descriptor is the ONLY thing derived from the pilot
    // configuration that a browser ever sees, so the list of modules that can
    // derive one is pinned the way the credential seam's importer list is. A
    // client component appearing here would be a client component importing
    // `lib/server/**`.
    const importers = walk(WEB_ROOT).filter((file) =>
      /from "@\/lib\/server\/identity"/.test(code(file)),
    );
    expect(importers.map((file) => path.relative(WEB_ROOT, file)).sort()).toEqual([
      "app/(learn)/layout.tsx",
      "app/(workspace)/layout.tsx",
    ]);
  });

  it("is named in no shipped module outside lib/server/", () => {
    // The env variables carry the map and the edge secret. A `PILOT_` mention
    // in a client-reachable module would mean a second reader of one of them,
    // which is a second credential path — 04 §1.3 constraint 1's whole
    // subject. WO-W17b's `identity.ts` names the three variables and is under
    // `lib/server/`; nothing it exports carries their values.
    const mentions = walk(WEB_ROOT)
      .filter((file) => /\bPILOT_[A-Z_]+\b/.test(code(file)))
      .map((file) => path.relative(WEB_ROOT, file))
      .sort();
    expect(mentions).toEqual([
      "lib/server/identity.ts",
      "lib/server/pilot.ts",
      "lib/server/principal.ts",
    ]);
  });

  it.runIf(existsSync(path.join(WEB_ROOT, ".next", "static")))(
    "puts no pilot key material in the built client bundle",
    () => {
      // `npm run build` first; in CI the unit suite runs BEFORE `npm run
      // budgets`, so `.next/` does not exist and this is skipped rather than
      // passing vacuously. The PR body carries the local run's count.
      const staticDir = path.join(WEB_ROOT, ".next", "static");
      const files = walkAll(staticDir);
      expect(files.length).toBeGreaterThan(0);
      const needles = [
        E2E_PILOTS.a.apiKey,
        E2E_PILOTS.b.apiKey,
        E2E_PILOT_EDGE_SECRET,
        "sk_ada_secret",
        "PILOT_PRINCIPAL_MAP",
        "PILOT_EDGE_SECRET",
        // WO-W17b. Two server layouts now derive a descriptor from the pilot
        // configuration and hand it to a CLIENT component, so the mode
        // variable and both header names join the scan: if the derivation had
        // been written in the shell instead of above it, one of these five
        // would be in a chunk a browser downloads.
        "PILOT_EDGE_AUTH",
        "PILOT_MODE_ENV",
        "x-pilot-edge-key",
        "x-pilot-user",
      ];
      for (const file of files) {
        const body = readFileSync(file, "utf8");
        for (const needle of needles) {
          expect(
            body.includes(needle),
            `${path.relative(WEB_ROOT, file)} contains ${needle}`,
          ).toBe(false);
        }
      }
    },
  );
});

/**
 * A file's source with its comments removed.
 *
 * Same helper, same reason, as `web/tests/principal.test.ts`: the scans above
 * are about what the code DOES, and a scan that counted prose would force the
 * prose to be deleted to keep the test green.
 */
function code(file: string): string {
  return readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

/** Every shipped source file — the same walk `principal.test.ts` uses. */
function walk(root: string): string[] {
  const found: string[] = [path.join(root, "middleware.ts")];
  const visit = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (statSync(full).isDirectory()) visit(full);
      else if (/\.(ts|tsx)$/.test(entry) && !/\.stories\.tsx$/.test(entry)) {
        found.push(full);
      }
    }
  };
  for (const dir of ["app", "components", "lib"]) visit(path.join(root, dir));
  return found;
}

/** Every file under a directory, whatever its extension. */
function walkAll(root: string): string[] {
  const found: string[] = [];
  const visit = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (statSync(full).isDirectory()) visit(full);
      else found.push(full);
    }
  };
  visit(root);
  return found;
}
