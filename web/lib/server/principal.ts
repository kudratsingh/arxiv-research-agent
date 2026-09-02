/**
 * MT-01 seam S1 — credential resolution, extracted (04-ARCHITECTURE.md §10).
 *
 * WHAT THIS IS AND IS NOT. §10's S1 row says the extraction is a **no-op
 * refactor today and the only edit site later**:
 *
 *   > `process.env.ARXIV_API_KEY` read inline → Extract to
 *   > `resolveUpstreamPrincipal(request): Promise<{keyId, apiKey} | null>` in
 *   > `web/lib/server/principal.ts`. The shared-principal implementation
 *   > returns the env key unchanged.
 *
 * So this file adds no behaviour. It does not read a cookie, does not consult
 * a session, does not vary by caller, and does not fake a login — D-009 is
 * binding and 04 §10 opens with it: "the revamp must not fake login or
 * per-user views". Every request resolves to the same principal, because
 * today there is exactly one.
 *
 * The evidence that it is a no-op is `web/tests/apiProxyRoute.test.ts`
 * passing **unmodified** (WO-30 criterion 5 / RC-08). That file asserts the
 * key is injected as `X-API-Key`, that the header is absent in the auth-off
 * configuration, and that a 401 flows back untouched. It was written against
 * the inline `process.env` read and never edited; if the extraction had
 * changed the boundary, it would be red.
 *
 * NO `server-only` IMPORT, DELIBERATELY. It would be the obvious guard for a
 * module that resolves a secret, and it cannot be used here: the `server-only`
 * package throws on import under any condition except `react-server`, which
 * would take `web/tests/apiProxyRoute.test.ts` — the frozen file that is this
 * work order's whole proof — red the moment the route imported this module.
 * What holds the line instead is the boundary the architecture already
 * names: `app/api/[...path]/route.ts` pins `runtime = "nodejs"` and is the
 * SOLE credential path (04 §1.3 constraint 1), and
 * `web/tests/principal.test.ts` asserts that no client-reachable module in
 * `web/` imports this file.
 *
 * WO-W17 ADDED ONE MODE, DEFAULT OFF (SR-08, ADR 0063).
 *
 * The paragraph above is still true of every deployment that does not set
 * `PILOT_EDGE_AUTH=on`, which is every deployment on `main`. Under that
 * setting — and only under it — this function stops resolving the same
 * principal for every request and maps the username the pilot edge
 * authenticated to that pilot's already-issued per-principal API key. Read
 * `lib/server/pilot.ts` for the four guards, `docs/runbooks/pilot.md` for the
 * operational half, and `docs/decisions/0063-pilot-principal-edge-mapping.md`
 * for why this is a hand-run slice of MT-01 L0-03 rather than the beginning
 * of one — it is marked to be superseded by MT-01 on arrival.
 *
 * Nothing else moved. This file still reads `ARXIV_API_KEY` in one place, is
 * still imported only by the proxy route, still mints no credential, and
 * still has no session, cookie or login of any kind (D-009).
 */

import {
  PILOT_EDGE_SECRET_ENV,
  PILOT_MAP_ENV,
  PILOT_MODE_ENV,
  emitPilotLog,
  readPilotConfig,
  resolvePilotPrincipal,
} from "@/lib/server/pilot";
import type { PilotConfig, PilotFault } from "@/lib/server/pilot";

/**
 * The key_id the backend attributes shared-principal traffic to.
 *
 * Not sent anywhere. `ARXIV_API_KEY` is the secret half of one `API_KEYS`
 * entry (`docker-compose.yml`, `WEB_API_KEY`) and the backend derives the
 * key_id from the secret itself (`src/api/auth.py`), so this constant exists
 * to give the log line and the future session lookup a stable name for "the
 * one principal this deployment has". It is never logged as a credential
 * because it is not one.
 */
export const SHARED_PRINCIPAL_KEY_ID = "shared";

/** What the proxy needs in order to authenticate one upstream call. */
export interface UpstreamPrincipal {
  /** Stable identifier for the principal. `"shared"` until MT-01. */
  keyId: string;
  /** The secret sent as `X-API-Key`. Never logged, never returned to a client. */
  apiKey: string;
}

/**
 * Refusal to resolve a principal at all. Never a fallback.
 *
 * WHY A THROW AND NOT `null`. `null` already means something specific and
 * safe — "send no `X-API-Key` header at all", the auth-off local demo — and a
 * caller that treated a pilot-mode refusal as `null` would silently downgrade
 * an authenticated pilot request to an anonymous one. There is no value of
 * `UpstreamPrincipal | null` that means "stop", so refusal leaves the return
 * type entirely: a caller that forgets to handle it gets a 500, which is
 * wrong but closed. `app/api/[...path]/route.ts` handles it and answers 503.
 *
 * `fault` is an enum member from `lib/server/pilot.ts`, never a fragment of
 * the configuration or of a header.
 */
export class PrincipalUnresolvedError extends Error {
  readonly fault: PilotFault;

  constructor(fault: PilotFault) {
    super(`upstream principal unresolved: ${fault}`);
    this.name = "PrincipalUnresolvedError";
    this.fault = fault;
  }
}

/**
 * Resolve the principal whose credential this request is proxied under.
 *
 * Args:
 *   request: The browser request. Read **only** in the pilot mode below, and
 *     only for the two headers the edge sets. With `PILOT_EDGE_AUTH` off this
 *     function still ignores it completely, which is what keeps §10 S1's
 *     "no-op refactor" claim — and `web/tests/principal.test.ts` — true.
 *
 * Returns:
 *   The shared principal, or `null` when no key is configured — the auth-off
 *   local demo (`docker-compose.yml`: `ENABLE_API_AUTH` defaults to false and
 *   `ARXIV_API_KEY` is empty), where the proxy must send no `X-API-Key`
 *   header at all rather than an empty one.
 *
 * Raises:
 *   `PrincipalUnresolvedError` — pilot mode only. Every pilot-mode failure
 *   lands here: a spoofed username header, an unknown username, a broken map,
 *   an ambiguous configuration. None of them falls back to the shared key.
 *
 * WO-W17 ADDED ONE BRANCH AND MOVED NOTHING. With `PILOT_EDGE_AUTH` unset,
 * empty or `off`, `readPilotConfig` returns after reading one environment
 * variable and the three lines below it are the three lines that were here
 * before — same reads, same order, same values, and no output of any kind.
 * That is acceptance criterion 1, and `web/tests/principal.test.ts` proves it
 * by passing unmodified.
 */
export async function resolveUpstreamPrincipal(
  request: Request,
): Promise<UpstreamPrincipal | null> {
  // The shared key is read HERE and nowhere else — `principal.test.ts` scans
  // the shipped tree for a second reader — and handed to the pilot parser,
  // which inspects only whether it is empty. Reading it before the mode is
  // known is deliberate: the ambiguity check needs it.
  const apiKey = process.env.ARXIV_API_KEY;
  const pilot = pilotConfig(apiKey);

  if (pilot.mode === "off") {
    // Referenced so the signature is honest rather than lint-silenced: the
    // shared implementation genuinely ignores the request, and MT-01 is where
    // that stops being true.
    void request;

    if (!apiKey) return null;
    return { keyId: SHARED_PRINCIPAL_KEY_ID, apiKey };
  }

  const resolution = resolvePilotPrincipal(pilot, request);
  emitPilotLog({
    outcome: resolution.ok ? "resolved" : resolution.fault,
    username: resolution.username,
    keyId: resolution.ok ? resolution.principal.keyId : null,
  });
  if (!resolution.ok) throw new PrincipalUnresolvedError(resolution.fault);
  return {
    keyId: resolution.principal.keyId,
    apiKey: resolution.principal.apiKey,
  };
}

/**
 * The parsed pilot configuration, parsed once per distinct environment.
 *
 * SR-08 asks for a map "read once at startup". A module-level constant would
 * be the literal reading of that, and it would also make the module
 * untestable — `process.env` is the only way a test can present a second
 * configuration, and a value frozen at import time cannot see one. So the
 * parse is memoised on its own inputs instead: in a running container the
 * environment never changes, so this parses exactly once and every later
 * request reads the same `Map`; in the suite a changed variable produces a
 * new parse. The distinction the card cares about — that the map is not
 * re-read from disk, re-fetched, or re-derived per request — holds either
 * way.
 */
let cachedInputs: readonly [string, string, string, string] | null = null;
let cachedConfig: PilotConfig | null = null;

function pilotConfig(sharedApiKey: string | undefined): PilotConfig {
  const inputs = [
    process.env[PILOT_MODE_ENV] ?? "",
    process.env[PILOT_MAP_ENV] ?? "",
    process.env[PILOT_EDGE_SECRET_ENV] ?? "",
    sharedApiKey ?? "",
  ] as const;
  if (
    cachedConfig !== null &&
    cachedInputs !== null &&
    cachedInputs[0] === inputs[0] &&
    cachedInputs[1] === inputs[1] &&
    cachedInputs[2] === inputs[2] &&
    cachedInputs[3] === inputs[3]
  ) {
    return cachedConfig;
  }
  const config = readPilotConfig(
    { mode: inputs[0], map: inputs[1], edgeSecret: inputs[2] },
    sharedApiKey,
  );
  cachedInputs = inputs;
  cachedConfig = config;
  return config;
}
