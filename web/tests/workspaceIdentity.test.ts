/**
 * WO-W17b criteria 1 and 2 — the descriptor the identity slot is derived from.
 *
 * WHAT THIS FILE IS ABOUT, AND WHAT `tests/pilotPrincipal.test.ts` IS ABOUT.
 * That file proves the CREDENTIAL half: which key the proxy sends upstream,
 * and that it never falls back to the shared one. This file proves the
 * SENTENCE half: what the header is allowed to say about who is reading it.
 * They share `lib/server/pilot.ts`'s guards on purpose — a second copy of the
 * topology check would be a second thing to get wrong — so the assertions here
 * are about the DESCRIPTOR, which is the only thing that crosses into a
 * browser.
 *
 * THE THREE CLAIMS.
 *
 *   1. With the mode off, the answer is `shared` and the request is not
 *      consulted at all. A forged edge header on a `main` deployment changes
 *      nothing, which is what makes this work order invisible there.
 *   2. With the mode on, the answer is the pilot the EDGE authenticated, and
 *      every way of failing to prove that — a spoofed header, a wrong secret,
 *      an unknown username, a broken configuration, no request at all —
 *      answers `unresolved`. Never `shared`, and never a username.
 *   3. The descriptor cannot carry a secret. Not "does not today": the type
 *      has no field for one, and the assertion below is over the key set of
 *      every descriptor the deriver can produce plus a substring scan of its
 *      serialised form for the map's own values.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deriveWorkspaceIdentity,
  pilotEnvironment,
  resolveWorkspaceIdentity,
} from "@/lib/server/identity";
import {
  PILOT_EDGE_KEY_HEADER,
  PILOT_EDGE_SECRET_ENV,
  PILOT_MAP_ENV,
  PILOT_MODE_ENV,
  PILOT_USER_HEADER,
} from "@/lib/server/pilot";
import type { PilotEnv } from "@/lib/server/pilot";
import type { WorkspaceIdentity } from "@/lib/identity";

/** 42 characters: over `PILOT_EDGE_SECRET_MIN_LENGTH`, and not a secret. */
const EDGE_SECRET = "unit_suite_edge_secret_local_preview_00000";

const ADA = { keyId: "ada-key-id", apiKey: "sk_ada_secret_local_preview" };
const BO = { keyId: "bo-key-id", apiKey: "sk_bo_secret_local_preview" };

const MAP = JSON.stringify({
  "pilot-ada": { key_id: ADA.keyId, api_key: ADA.apiKey },
  "pilot-bo": { key_id: BO.keyId, api_key: BO.apiKey },
});

/** Every value a descriptor must never be able to carry. */
const SECRETS = [ADA.apiKey, BO.apiKey, ADA.keyId, BO.keyId, EDGE_SECRET];

const ON: PilotEnv = { mode: "on", map: MAP, edgeSecret: EDGE_SECRET };

/** Headers as they arrive at a server component: `ReadonlyHeaders` has `get`. */
function incoming(values: Record<string, string>): Headers {
  return new Headers(values);
}

/** What the edge sends: its own proof, then the name it authenticated. */
function fromEdge(username: string): Headers {
  return incoming({
    [PILOT_EDGE_KEY_HEADER]: EDGE_SECRET,
    [PILOT_USER_HEADER]: username,
  });
}

// ---------------------------------------------------------------------------
// Criterion 1 — with the mode off, nothing changed.
// ---------------------------------------------------------------------------

describe("criterion 1 — the mode is off, so the workspace is shared", () => {
  it.each([
    ["unset", undefined],
    ["empty", ""],
    ["whitespace", "   "],
    ["the literal off", "off"],
  ])("resolves shared when the mode is %s", (_label, mode) => {
    const identity = deriveWorkspaceIdentity(
      { mode, map: MAP, edgeSecret: EDGE_SECRET },
      fromEdge("pilot-ada"),
    );
    expect(identity).toEqual({ kind: "shared" });
  });

  it("ignores the edge headers entirely, forged or genuine", () => {
    // The header set that WOULD resolve to a pilot under `on`. On a `main`
    // deployment it is not evidence of anything and must not become one — the
    // same claim `tests/pilotPrincipal.test.ts` makes about the credential.
    const identity = deriveWorkspaceIdentity(
      { mode: undefined, map: undefined, edgeSecret: undefined },
      fromEdge("pilot-ada"),
    );
    expect(identity).toEqual({ kind: "shared" });
  });

  it("resolves shared with no request at all — a render outside a request", () => {
    expect(deriveWorkspaceIdentity({ mode: "off" } as PilotEnv, null)).toEqual({
      kind: "shared",
    });
  });
});

// ---------------------------------------------------------------------------
// Criterion 2 — with the mode on, the descriptor is the edge's answer.
// ---------------------------------------------------------------------------

describe("criterion 2 — the pilot the edge authenticated, and only that", () => {
  it("names the pilot on a request the edge vouched for", () => {
    expect(deriveWorkspaceIdentity(ON, fromEdge("pilot-ada"))).toEqual({
      kind: "pilot",
      username: "pilot-ada",
    });
    expect(deriveWorkspaceIdentity(ON, fromEdge("pilot-bo"))).toEqual({
      kind: "pilot",
      username: "pilot-bo",
    });
  });

  it("carries the username and NOTHING else — no key, no key id, no fault", () => {
    const identity = deriveWorkspaceIdentity(ON, fromEdge("pilot-ada"));
    expect(Object.keys(identity).sort()).toEqual(["kind", "username"]);
    const serialised = JSON.stringify(identity);
    for (const secret of SECRETS) {
      expect(serialised, `the descriptor carries ${secret}`).not.toContain(secret);
    }
  });

  it("lower-cases the username, because the map's keys are lower-case", () => {
    expect(deriveWorkspaceIdentity(ON, fromEdge("Pilot-Ada"))).toEqual({
      kind: "pilot",
      username: "pilot-ada",
    });
  });
});

describe("criterion 2 — an unproven request is `unresolved`, never `shared`", () => {
  /** Each case is a way of failing to be the edge, or of not being mapped. */
  const REFUSALS: [string, Headers | null][] = [
    // THE SPOOF. A username with no edge key: the request did not come
    // through the edge, so it is not evidence of anything. This is the case
    // MT-01 threat T6 names, and answering `shared` here would be worse than
    // answering nothing — it would tell a stranger the workspace they are
    // looking at is everyone's.
    ["a username with no edge key", incoming({ [PILOT_USER_HEADER]: "pilot-ada" })],
    [
      "a username with the wrong edge key",
      incoming({
        [PILOT_EDGE_KEY_HEADER]: `${EDGE_SECRET}x`,
        [PILOT_USER_HEADER]: "pilot-ada",
      }),
    ],
    [
      "a username with an edge key of a different length",
      incoming({ [PILOT_EDGE_KEY_HEADER]: "short", [PILOT_USER_HEADER]: "pilot-ada" }),
    ],
    ["the edge key with no username", incoming({ [PILOT_EDGE_KEY_HEADER]: EDGE_SECRET })],
    ["an empty username from the edge", fromEdge("   ")],
    ["a malformed username from the edge", fromEdge("../../etc/passwd")],
    ["a username nobody was issued", fromEdge("pilot-nobody")],
    ["no request at all", null],
  ];

  it.each(REFUSALS)("refuses %s", (_label, headers) => {
    expect(deriveWorkspaceIdentity(ON, headers)).toEqual({ kind: "unresolved" });
  });

  it("names nobody, in any of them", () => {
    for (const [label, headers] of REFUSALS) {
      const serialised = JSON.stringify(deriveWorkspaceIdentity(ON, headers));
      expect(serialised, label).not.toContain("pilot-ada");
      expect(serialised, label).not.toContain("username");
      for (const secret of SECRETS) expect(serialised, label).not.toContain(secret);
    }
  });
});

describe("criterion 2 — a configuration fault is `unresolved` too", () => {
  it.each([
    ["a mode value that is neither on nor off", { ...ON, mode: "true" }],
    ["a missing edge secret", { ...ON, edgeSecret: undefined }],
    ["an edge secret under the floor", { ...ON, edgeSecret: "too-short" }],
    ["a missing map", { ...ON, map: undefined }],
    ["an unparseable map", { ...ON, map: "{not json" }],
    ["a map that is not an object", { ...ON, map: "[]" }],
    ["an empty map", { ...ON, map: "{}" }],
    [
      "a sixth pilot, over SR-09's cohort ceiling",
      {
        ...ON,
        map: JSON.stringify(
          Object.fromEntries(
            [1, 2, 3, 4, 5, 6].map((n) => [
              `pilot-${n}`,
              { key_id: `k${n}`, api_key: `sk_${n}` },
            ]),
          ),
        ),
      },
    ],
  ])("refuses %s", (_label, env) => {
    expect(deriveWorkspaceIdentity(env as PilotEnv, fromEdge("pilot-ada"))).toEqual({
      kind: "unresolved",
    });
  });

  it("never quotes the broken configuration back at the reader", () => {
    // `readPilotConfig` refuses to put a fragment of the map into a fault for
    // the reason its own header gives — a `JSON.parse` message quotes the
    // document it failed on, and the document is a table of API keys. The
    // descriptor cannot carry a fault at all, which is the same protection one
    // layer further out.
    const broken = { ...ON, map: `{"pilot-ada": {"api_key": "${ADA.apiKey}"` };
    const identity = deriveWorkspaceIdentity(broken, fromEdge("pilot-ada"));
    expect(identity).toEqual({ kind: "unresolved" });
    expect(Object.keys(identity)).toEqual(["kind"]);
    expect(JSON.stringify(identity)).not.toContain(ADA.apiKey);
  });

  it("does NOT see the shared-key ambiguity, and that is written down", () => {
    // `readPilotConfig` refuses a deployment that sets a pilot map AND
    // `ARXIV_API_KEY`, because it has two answers to "whose credential is
    // this". Seeing that here would mean reading the shared key, and
    // `tests/principal.test.ts` asserts `lib/server/principal.ts` is the only
    // module in the shipped tree that does. So this function answers the
    // question it CAN answer — who did the edge authenticate — and the proxy
    // is what refuses the deployment, with a 503 on every request. Pinned so
    // the trade-off is a decision rather than a surprise.
    const identity = deriveWorkspaceIdentity(ON, fromEdge("pilot-ada"));
    expect(identity).toEqual({ kind: "pilot", username: "pilot-ada" });
  });
});

// ---------------------------------------------------------------------------
// The environment read, and the request-scope wrapper.
// ---------------------------------------------------------------------------

describe("pilotEnvironment reads three variables and no others", () => {
  it("maps each name to its value", () => {
    expect(
      pilotEnvironment({
        [PILOT_MODE_ENV]: "on",
        [PILOT_MAP_ENV]: MAP,
        [PILOT_EDGE_SECRET_ENV]: EDGE_SECRET,
        ARXIV_API_KEY: "server-only-secret",
      }),
    ).toEqual({ mode: "on", map: MAP, edgeSecret: EDGE_SECRET });
  });

  it("does not read the shared key, whatever it is set to", () => {
    // The scan in `tests/principal.test.ts` is the structural version of this;
    // this is the behavioural one, and it is cheap.
    const env = pilotEnvironment({ ARXIV_API_KEY: "server-only-secret" });
    expect(JSON.stringify(env)).not.toContain("server-only-secret");
    expect(env).toEqual({ mode: undefined, map: undefined, edgeSecret: undefined });
  });
});

describe("resolveWorkspaceIdentity, outside and inside a request scope", () => {
  const saved = {
    mode: process.env[PILOT_MODE_ENV],
    map: process.env[PILOT_MAP_ENV],
    secret: process.env[PILOT_EDGE_SECRET_ENV],
  };

  const restore = (name: string, value: string | undefined): void => {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  };

  beforeEach(() => {
    delete process.env[PILOT_MODE_ENV];
    delete process.env[PILOT_MAP_ENV];
    delete process.env[PILOT_EDGE_SECRET_ENV];
  });

  afterEach(() => {
    vi.doUnmock("next/headers");
    vi.resetModules();
    restore(PILOT_MODE_ENV, saved.mode);
    restore(PILOT_MAP_ENV, saved.map);
    restore(PILOT_EDGE_SECRET_ENV, saved.secret);
  });

  it("resolves shared with the mode off and no request to read", async () => {
    // `next/headers` throws outside a request scope. The mode is off, so
    // there is nothing to learn from a request anyway, and the answer is the
    // one every `main` deployment renders.
    await expect(resolveWorkspaceIdentity()).resolves.toEqual({ kind: "shared" });
  });

  it("resolves unresolved with the mode on and no request to read", async () => {
    process.env[PILOT_MODE_ENV] = "on";
    process.env[PILOT_MAP_ENV] = MAP;
    process.env[PILOT_EDGE_SECRET_ENV] = EDGE_SECRET;
    await expect(resolveWorkspaceIdentity()).resolves.toEqual({ kind: "unresolved" });
  });

  it("reads the real request headers when there is a request", async () => {
    process.env[PILOT_MODE_ENV] = "on";
    process.env[PILOT_MAP_ENV] = MAP;
    process.env[PILOT_EDGE_SECRET_ENV] = EDGE_SECRET;
    vi.resetModules();
    vi.doMock("next/headers", () => ({
      headers: async () => fromEdge("pilot-bo"),
    }));
    const { resolveWorkspaceIdentity: resolved } = await import(
      "@/lib/server/identity"
    );
    await expect(resolved()).resolves.toEqual({
      kind: "pilot",
      username: "pilot-bo",
    });
  });

  it("never throws, whatever the configuration is", async () => {
    // A layout that threw would replace the whole page with an error boundary
    // because a sentence in the header could not be composed. Every shape of
    // broken configuration is exercised through the real entry point.
    for (const mode of ["on", "true", "ON", "off", ""]) {
      process.env[PILOT_MODE_ENV] = mode;
      process.env[PILOT_MAP_ENV] = "{not json";
      process.env[PILOT_EDGE_SECRET_ENV] = "x";
      const identity: WorkspaceIdentity = await resolveWorkspaceIdentity();
      expect(["shared", "unresolved"]).toContain(identity.kind);
    }
  });
});
