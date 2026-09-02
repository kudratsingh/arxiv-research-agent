/**
 * WO-W17 — the pilot edge-identity mode that lives behind MT-01 seam S1.
 *
 * WHAT THIS IS. `planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md` SR-08
 * asks for one thing and refuses everything adjacent to it: the edge
 * (`deploy/pilot/Caddyfile`, HTTP `basic_auth`, one user per pilot) does the
 * authenticating and forwards the username it authenticated; this module maps
 * that username to that pilot's already-issued per-principal API key, from a
 * server-side environment map. There is no session, no login page, no cookie,
 * no token, and no key minting. `resolveUpstreamPrincipal` stays the only
 * edit site (04-ARCHITECTURE.md §10 S1) and the proxy stays the only
 * credential boundary (04 §1.3 constraint 1).
 *
 * WHAT THIS IS NOT. It is not MT-01. `docs/proposals/multi-tenancy.md` §3
 * Option C1 is the shape being borrowed and MT-01 **replaces** this, it does
 * not grow from it — see `docs/decisions/0063-pilot-principal-edge-mapping.md`,
 * which is marked to be superseded by MT-01 on arrival.
 *
 * THE FOUR GUARDS, AND WHY EACH ONE EXISTS.
 *
 *   1. OFF BY DEFAULT, AND ONLY THE LITERAL `on` TURNS IT ON. MT-01's threat
 *      T6 (identity-header spoofing) states the requirement in one sentence:
 *      the resolver "must be off by default, gated by an explicit setting,
 *      and must never be enabled by inference". Unset, empty and `off` are
 *      off. `on` is on. **Any other value is a configuration fault and the
 *      deployment refuses to serve** — because the alternative is an operator
 *      typing `PILOT_EDGE_AUTH=true`, believing the pilot mapping is live,
 *      and getting the shared principal instead. Silent-and-safe is still
 *      silent; loud-and-safe is better.
 *
 *   2. A TOPOLOGY ASSERTION, NOT A TOPOLOGY ASSUMPTION. A forwarded username
 *      is only trustworthy if nothing but the edge can reach the `web`
 *      service. That is true of the production overlay, whose `web` publishes
 *      no host port (`deploy/hetzner/compose.prod.yml`), and **false** of base
 *      compose, which publishes it to loopback (`docker-compose.yml`). ADR
 *      0039 is the cautionary precedent for deciding anything by the wrong
 *      signal, so the trust is not inferred from the topology at all: the edge
 *      sends a shared secret in `X-Pilot-Edge-Key` and the resolver refuses
 *      the username header unless that secret matches, compared over SHA-256
 *      digests with `timingSafeEqual`. See `docs/runbooks/pilot.md` for the
 *      alternatives that were rejected and why this one is the least magic.
 *
 *   3. FAIL CLOSED, NEVER TO THE SHARED KEY. Every failure below — a broken
 *      map, an unknown username, a spoofed header, an ambiguous configuration
 *      — resolves to NO principal. `resolveUpstreamPrincipal` throws rather
 *      than returning `null`, because `null` already means something specific
 *      and safe ("send no `X-API-Key` header at all", the auth-off demo) and
 *      quietly downgrading a pilot's authenticated request to an
 *      unauthenticated one is precisely the bug this file must not have.
 *
 *   4. THE MAP IS NEVER LOGGED AND CANNOT BE. `PilotLogRecord` has no field
 *      that can hold a secret — the same structural argument
 *      `lib/server/proxyLog.ts` makes about the request log. The username is
 *      logged, and only after the topology guard has passed, so an attacker
 *      cannot write arbitrary bytes into the log by sending a header.
 *
 * NO `server-only` IMPORT, for the reason `principal.ts` gives at length: the
 * package throws under any condition except `react-server`, which would take
 * the frozen `web/tests/apiProxyRoute.test.ts` red.
 */

import { createHash, timingSafeEqual } from "node:crypto";

// ------------------------------------------------------------------ the env

/** Server-side setting that turns the mapping on. Default off. */
export const PILOT_MODE_ENV = "PILOT_EDGE_AUTH";
/** Server-side JSON map: `{"<edge username>": {"key_id", "api_key"}}`. */
export const PILOT_MAP_ENV = "PILOT_PRINCIPAL_MAP";
/** Server-side shared secret the edge echoes, proving the request came through it. */
export const PILOT_EDGE_SECRET_ENV = "PILOT_EDGE_SECRET";

/** The one value of `PILOT_EDGE_AUTH` that enables the mapping. */
export const PILOT_MODE_ON = "on";
/** The one non-empty value that explicitly disables it. */
export const PILOT_MODE_OFF = "off";

// -------------------------------------------------------------- the headers

/** The username the edge authenticated. Lower-case: `Headers` is case-insensitive. */
export const PILOT_USER_HEADER = "x-pilot-user";
/** The edge's proof that it is the edge. Compared, never logged, never forwarded. */
export const PILOT_EDGE_KEY_HEADER = "x-pilot-edge-key";

// --------------------------------------------------------------- the bounds

/**
 * Shortest edge secret the resolver will accept.
 *
 * 32 characters is `openssl rand -hex 16`. The runbook asks for
 * `openssl rand -hex 32`; this is the floor, not the recommendation. A floor
 * exists at all because the secret is the entire topology guard, and a
 * four-character one would make the guard decorative.
 */
export const PILOT_EDGE_SECRET_MIN_LENGTH = 32;

/**
 * The cohort ceiling, enforced in code rather than only in a document.
 *
 * SR-09 bounds pilot spend by arithmetic instead of by the global cap MT-01
 * finding F4 says does not exist yet, and the first term of that arithmetic
 * is "≤5 pilots". It also says what happens above it: "Any cohort beyond 5,
 * any public opening, or any scheduled work re-triggers the F4 prerequisite."
 * A sixth entry in the map is therefore not a bigger pilot, it is a different
 * decision — so it refuses to serve rather than quietly doubling the exposure
 * the Gate W2 report was written against.
 */
export const PILOT_MAX_PRINCIPALS = 5;

/**
 * What an edge username may look like.
 *
 * Deliberately narrower than "whatever Caddy would accept". The username
 * reaches a log line and a keystore lookup, so it is restricted to a
 * conservative token: lower-case alphanumerics, dot, dash, underscore, no
 * leading or trailing punctuation, 1–64 characters. Anything else is refused
 * rather than sanitised — sanitising invents a username nobody issued.
 */
export const PILOT_USERNAME_PATTERN =
  /^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$/;

// ---------------------------------------------------------------- the faults

/**
 * A configuration the deployment refuses to serve under.
 *
 * Every one of these is an operator mistake, not a caller mistake, and every
 * one of them produces a 503 for **every** request rather than a fallback for
 * any of them. `shared_key_also_set` is the ambiguity the card names by name:
 * a deployment that has both a pilot map and `ARXIV_API_KEY` has two answers
 * to "whose key is this request", and the safe move is to give neither.
 */
export type PilotConfigFault =
  | "mode_value_invalid"
  | "shared_key_also_set"
  | "edge_secret_missing"
  | "edge_secret_too_short"
  | "map_missing"
  | "map_unparseable"
  | "map_not_an_object"
  | "map_empty"
  | "map_too_large"
  | "map_username_invalid"
  | "map_entry_invalid"
  | "map_duplicate_api_key"
  | "map_duplicate_key_id";

/**
 * A request the resolver refuses under a configuration that is itself fine.
 *
 * `untrusted_topology` is the spoof case: a username header arrived on a
 * request that did not carry the edge's secret, so it did not come through
 * the edge, so it is not evidence of anything.
 */
export type PilotRequestFault =
  | "untrusted_topology"
  | "username_missing"
  | "username_invalid"
  | "unknown_username";

export type PilotFault = PilotConfigFault | PilotRequestFault;

// --------------------------------------------------------------- the config

/** One pilot's already-issued backend credential. Never leaves the server. */
export interface PilotPrincipalEntry {
  /** The NAME half of the `api_keys_file` entry — what lands on a row (ADR 0036). */
  keyId: string;
  /** The SECRET half. Sent upstream as `X-API-Key` and nowhere else. */
  apiKey: string;
}

/** The resolved server configuration: one of three states, never a maybe. */
export type PilotConfig =
  | { readonly mode: "off" }
  | { readonly mode: "misconfigured"; readonly fault: PilotConfigFault }
  | {
      readonly mode: "on";
      readonly edgeSecret: string;
      readonly principals: ReadonlyMap<string, PilotPrincipalEntry>;
    };

/** The three environment values this module reads. Passed in, never grabbed. */
export interface PilotEnv {
  readonly mode: string | undefined;
  readonly map: string | undefined;
  readonly edgeSecret: string | undefined;
}

/**
 * Parse the pilot configuration.
 *
 * Args:
 *   env: The three `PILOT_*` values. Passed as an argument rather than read
 *     from `process.env` here so this function is a pure parser — and so that
 *     `web/tests/principal.test.ts`'s "is the only module that reads
 *     ARXIV_API_KEY" scan keeps meaning what it says: the shared key is read
 *     in `principal.ts` and handed down, never read a second time.
 *   sharedApiKey: `ARXIV_API_KEY` as `principal.ts` read it. Only its
 *     emptiness is inspected; the value is never returned, logged or
 *     compared.
 *
 * Returns:
 *   `off`, `on` with the parsed map, or `misconfigured` with the reason. The
 *   reason is an enum member, never a fragment of the input — a parse error
 *   message from `JSON.parse` can quote the document it failed on, and that
 *   document is a table of API keys.
 */
export function readPilotConfig(
  env: PilotEnv,
  sharedApiKey: string | undefined,
): PilotConfig {
  const mode = (env.mode ?? "").trim();
  if (mode === "" || mode === PILOT_MODE_OFF) return { mode: "off" };
  if (mode !== PILOT_MODE_ON) {
    return { mode: "misconfigured", fault: "mode_value_invalid" };
  }

  // THE AMBIGUITY RULE. Two configured answers to "whose credential is this"
  // is not a fallback chain, it is an unanswered question. Refusing here is
  // what makes "never the shared key" a property of the code rather than of
  // the order of the branches below it.
  if ((sharedApiKey ?? "") !== "") {
    return { mode: "misconfigured", fault: "shared_key_also_set" };
  }

  const edgeSecret = (env.edgeSecret ?? "").trim();
  if (edgeSecret === "") {
    return { mode: "misconfigured", fault: "edge_secret_missing" };
  }
  if (edgeSecret.length < PILOT_EDGE_SECRET_MIN_LENGTH) {
    return { mode: "misconfigured", fault: "edge_secret_too_short" };
  }

  const rawMap = (env.map ?? "").trim();
  if (rawMap === "") return { mode: "misconfigured", fault: "map_missing" };

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawMap);
  } catch {
    // The caught error is deliberately discarded rather than attached to the
    // fault: `SyntaxError` messages from `JSON.parse` quote the offending
    // region of the document, and the document is a table of API keys.
    return { mode: "misconfigured", fault: "map_unparseable" };
  }
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    Array.isArray(parsed)
  ) {
    return { mode: "misconfigured", fault: "map_not_an_object" };
  }

  const entries = Object.entries(parsed as Record<string, unknown>);
  if (entries.length === 0) {
    return { mode: "misconfigured", fault: "map_empty" };
  }
  if (entries.length > PILOT_MAX_PRINCIPALS) {
    return { mode: "misconfigured", fault: "map_too_large" };
  }

  const principals = new Map<string, PilotPrincipalEntry>();
  const seenApiKeys = new Set<string>();
  const seenKeyIds = new Set<string>();
  for (const [username, value] of entries) {
    if (!PILOT_USERNAME_PATTERN.test(username)) {
      return { mode: "misconfigured", fault: "map_username_invalid" };
    }
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return { mode: "misconfigured", fault: "map_entry_invalid" };
    }
    const record = value as Record<string, unknown>;
    const keyId = record["key_id"];
    const apiKey = record["api_key"];
    if (
      typeof keyId !== "string" ||
      typeof apiKey !== "string" ||
      keyId.trim() === "" ||
      apiKey.trim() === ""
    ) {
      return { mode: "misconfigured", fault: "map_entry_invalid" };
    }
    // THE NEVER-REASSIGN RULE, AS ARITHMETIC. SR-02/F1: `key_id` is a mutable
    // display name, so two pilots sharing one key — or one key_id — would
    // read and write each other's profile, ledger and threads under ADR
    // 0036's scoping. `src/api/auth.py::load_keystore_from_file` refuses the
    // same two shapes in the keystore; this refuses them in the map, because
    // a mapping is only per-person if it is injective.
    if (seenApiKeys.has(apiKey.trim())) {
      return { mode: "misconfigured", fault: "map_duplicate_api_key" };
    }
    if (seenKeyIds.has(keyId.trim())) {
      return { mode: "misconfigured", fault: "map_duplicate_key_id" };
    }
    seenApiKeys.add(apiKey.trim());
    seenKeyIds.add(keyId.trim());
    principals.set(username, {
      keyId: keyId.trim(),
      apiKey: apiKey.trim(),
    });
  }

  return { mode: "on", edgeSecret, principals };
}

// ------------------------------------------------------------- the resolver

/**
 * The only thing the resolver reads off a request: two headers, by name.
 *
 * WHY A STRUCTURAL TYPE AND NOT `Request` (WO-W17b). `resolvePilotPrincipal`
 * never touched a method, a body or a URL — it reads `X-Pilot-Edge-Key` and
 * `X-Pilot-User`, and nothing else — and the second caller does not hold a
 * `Request` at all: `lib/server/identity.ts` runs inside a server component,
 * where `next/headers` hands back a `ReadonlyHeaders` and there is no request
 * object to be had. Narrowing the parameter to what is actually read lets both
 * callers pass what they have, and it makes the read surface of this function
 * something the signature states rather than something a reader has to verify.
 * `Request` satisfies it structurally, so `principal.ts` and every existing
 * test are unchanged.
 */
export interface PilotHeaderReader {
  get(name: string): string | null;
}

/** Anything carrying request headers: a `Request`, or a server component's. */
export interface PilotHeaderCarrier {
  readonly headers: PilotHeaderReader;
}

/** What one request resolved to. */
export type PilotResolution =
  | {
      readonly ok: true;
      readonly username: string;
      readonly principal: PilotPrincipalEntry;
    }
  | {
      readonly ok: false;
      readonly fault: PilotFault;
      /** `null` whenever the value is not provably the edge's. */
      readonly username: string | null;
    };

/**
 * Map one request's edge-forwarded username to a principal.
 *
 * Args:
 *   config: The parsed configuration. A `misconfigured` one refuses every
 *     request without inspecting it at all — an operator's mistake is not a
 *     per-caller condition.
 *   request: The browser request as the proxy received it, or anything else
 *     carrying that request's headers — see `PilotHeaderCarrier`.
 *
 * Returns:
 *   The pilot's principal, or a fault. The fault carries a username ONLY when
 *   the topology guard passed and the value parsed as a username, so a
 *   spoofed header can never reach the log.
 */
export function resolvePilotPrincipal(
  config: PilotConfig,
  request: PilotHeaderCarrier,
): PilotResolution {
  if (config.mode === "misconfigured") {
    return { ok: false, fault: config.fault, username: null };
  }
  if (config.mode === "off") {
    // Not reachable through `resolveUpstreamPrincipal`, which short-circuits
    // the off path before calling here. Answered rather than thrown so that
    // the type is total and a future caller cannot get an exception out of a
    // function whose job is to answer questions.
    return { ok: false, fault: "untrusted_topology", username: null };
  }

  // GUARD 2, FIRST AND UNCONDITIONALLY. Nothing below this line reads the
  // username header, so there is no ordering in which an unauthenticated
  // request's header influences anything — including the log.
  const presented = request.headers.get(PILOT_EDGE_KEY_HEADER);
  if (presented === null || !secretsMatch(presented, config.edgeSecret)) {
    return { ok: false, fault: "untrusted_topology", username: null };
  }

  const rawUsername = request.headers.get(PILOT_USER_HEADER);
  if (rawUsername === null || rawUsername.trim() === "") {
    return { ok: false, fault: "username_missing", username: null };
  }
  const username = rawUsername.trim().toLowerCase();
  if (!PILOT_USERNAME_PATTERN.test(username)) {
    // Still not logged. The edge is trusted to be the edge, not to be
    // incapable of forwarding a header some future middlebox rewrote.
    return { ok: false, fault: "username_invalid", username: null };
  }

  const principal = config.principals.get(username);
  if (principal === undefined) {
    // The one fault that names its username: the value came through the
    // verified edge and is a well-formed token, so it is the operator's own
    // vocabulary, and "which pilot 503'd" is the question the runbook's
    // revocation section is answered by.
    return { ok: false, fault: "unknown_username", username };
  }
  return { ok: true, username, principal };
}

/**
 * Constant-time comparison of two secrets of unequal length.
 *
 * `timingSafeEqual` throws on a length mismatch, and the length of the
 * presented value is attacker-controlled, so the raw strings are never handed
 * to it. Hashing first makes both operands 32 bytes, which removes the throw
 * and the length oracle in one step.
 */
function secretsMatch(presented: string, expected: string): boolean {
  const a = createHash("sha256").update(presented, "utf8").digest();
  const b = createHash("sha256").update(expected, "utf8").digest();
  return timingSafeEqual(a, b);
}

// --------------------------------------------------------------- the log line

/** The stable `event` value, so the line is greppable in a mixed stdout. */
export const PILOT_LOG_EVENT = "pilot_principal";

/**
 * One resolution, as it will be serialised.
 *
 * THIS TYPE CANNOT EXPRESS A SECRET, and that is the redaction guarantee —
 * the same shape `ProxyLogRecord` uses. There is no `apiKey` field, no
 * `headers` field and no free-form `detail` field, so a later edit that
 * wanted to log the key would have to add a field, and
 * `web/tests/pilotPrincipal.test.ts` asserts the emitted key set.
 */
export interface PilotLogRecord {
  /** `resolved`, or the fault that refused the request. */
  readonly outcome: "resolved" | PilotFault;
  /** The edge-authenticated username, or `null` when it was not provably one. */
  readonly username: string | null;
  /** The principal the username mapped to, or `null` when it mapped to none. */
  readonly keyId: string | null;
}

/** Serialise one record. Fixed key order, for the same reason the proxy log has one. */
export function formatPilotLogLine(record: PilotLogRecord): string {
  const line: Record<string, string> = {
    event: PILOT_LOG_EVENT,
    outcome: record.outcome,
  };
  if (record.username !== null) line["user"] = record.username;
  if (record.keyId !== null) line["key_id"] = record.keyId;
  return JSON.stringify(line);
}

/**
 * Write one record to stdout.
 *
 * `process.stdout.write` rather than `console.log`, and failures swallowed,
 * for the two reasons `lib/server/proxyLog.ts::emitProxyLog` gives: Next
 * decorates `console` in ways that stop the line being parseable JSON, and a
 * broken log pipe must never turn a working proxy response into a 500.
 */
export function emitPilotLog(record: PilotLogRecord): void {
  try {
    process.stdout.write(`${formatPilotLogLine(record)}\n`);
  } catch {
    // Observability is not allowed to break the thing it observes.
  }
}
