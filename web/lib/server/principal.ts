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
 */

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
 * Resolve the principal whose credential this request is proxied under.
 *
 * Args:
 *   request: The browser request. **Unused today, and that is the point** —
 *     it is the parameter MT-01's session lookup reads (a cookie, a bearer
 *     token, whatever the ADR lands on), so adding it later is an edit to
 *     this function's body and to nothing else. §10 S1 specifies this exact
 *     signature.
 *
 * Returns:
 *   The shared principal, or `null` when no key is configured — the auth-off
 *   local demo (`docker-compose.yml`: `ENABLE_API_AUTH` defaults to false and
 *   `ARXIV_API_KEY` is empty), where the proxy must send no `X-API-Key`
 *   header at all rather than an empty one.
 */
export async function resolveUpstreamPrincipal(
  request: Request,
): Promise<UpstreamPrincipal | null> {
  // Referenced so the signature is honest rather than lint-silenced: the
  // shared implementation genuinely ignores the request, and MT-01 is where
  // that stops being true.
  void request;

  const apiKey = process.env.ARXIV_API_KEY;
  if (!apiKey) return null;
  return { keyId: SHARED_PRINCIPAL_KEY_ID, apiKey };
}
