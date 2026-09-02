/**
 * WO-W17b — the identity slot's occupant, derived per request at seam S1.
 *
 * THE PROBLEM THIS CLOSES. ADR 0063 shipped the pilot principal mapping and
 * recorded one thing it could not fix in the same card: under
 * `PILOT_EDGE_AUTH=on` the shell still said "Shared workspace — Everyone with
 * access to this deployment sees these threads. There are no separate
 * accounts." Both clauses are false there. `docs/security.md` §Follow-ups
 * called resolving it a prerequisite to inviting anyone, because it is a false
 * statement about data separation shown to the people the separation is for.
 *
 * WHY THIS IS NOT A FEATURE FLAG (SR-07). `05-WEDGE-WORK-ORDERS.md` SR-07
 * keeps the web tier's no-runtime-flags rule: "gating is backend-only",
 * because a flag doubles the state space every axe and Playwright run must
 * cover. Nothing here is a flag. `03-DESIGN-BRIEF.md` §6 says the identity
 * slot is *reserved and occupied by truthful content*, and the truthful
 * content is the principal the server already resolves for this request. This
 * module answers one question — **who did the edge authenticate?** — from the
 * same environment and the same two headers `lib/server/pilot.ts` already
 * reads, and hands the answer down as a value. The shell renders whatever it
 * is given and has no branch of its own to be wrong about.
 *
 * WHY IT DOES NOT GO THROUGH `resolveUpstreamPrincipal`. That function
 * resolves a **credential** and throws rather than returning one it cannot
 * (`PrincipalUnresolvedError`), and `web/tests/principal.test.ts` asserts it
 * is imported by exactly one module: `app/api/[...path]/route.ts`, the sole
 * credential boundary (04 §1.3 constraint 1). Widening that list so a layout
 * could call it would be widening the credential boundary to two document
 * routes in order to render a sentence. So the layouts come in beside it,
 * through the same parser and the same guards, and get back a value that
 * cannot hold a credential: `WorkspaceIdentity` in `lib/identity.ts` has no
 * field for a key, a key id, or a fault.
 *
 * WHAT IT DOES NOT DO. It does not call the upstream API — resolution is
 * local, an environment map and two request headers, exactly as it is in the
 * proxy. It never throws: a layout that threw would replace the page with an
 * error boundary because the header sentence could not be composed, which is
 * a worse outcome than any sentence. And it says nothing about whether the
 * deployment is *servable*; see `deriveWorkspaceIdentity` for the one
 * configuration fault it deliberately cannot see and why.
 *
 * NO `server-only` IMPORT, for the reason `principal.ts` gives at length: the
 * package throws on import under any condition except `react-server`, which
 * would take this module's own unit tests red. What holds the line instead is
 * asserted rather than assumed — `web/tests/pilotPrincipal.test.ts` pins the
 * complete list of modules that import this one (two server layouts) and the
 * complete list of modules that may so much as name a `PILOT_` variable, and
 * scans the built client bundle for both the key material and the names.
 */

import {
  PILOT_EDGE_SECRET_ENV,
  PILOT_MAP_ENV,
  PILOT_MODE_ENV,
  readPilotConfig,
  resolvePilotPrincipal,
} from "@/lib/server/pilot";
import type { PilotEnv, PilotHeaderReader } from "@/lib/server/pilot";
import {
  SHARED_WORKSPACE_IDENTITY,
  UNRESOLVED_WORKSPACE_IDENTITY,
} from "@/lib/identity";
import type { WorkspaceIdentity } from "@/lib/identity";

/**
 * The three `PILOT_*` values, read from an environment that is passed in.
 *
 * Passed in rather than grabbed, for the reason `readPilotConfig` takes its
 * environment as an argument: it makes the derivation a pure function of its
 * inputs, which is the only way a test can present a second configuration
 * without mutating the process it is running in. The parameter is a plain
 * string dictionary rather than `NodeJS.ProcessEnv` for the same reason —
 * `ProcessEnv` requires `NODE_ENV`, which this function has no business
 * caring about, and requiring it would make every test construct one.
 */
export function pilotEnvironment(
  source: Readonly<Record<string, string | undefined>>,
): PilotEnv {
  return {
    mode: source[PILOT_MODE_ENV],
    map: source[PILOT_MAP_ENV],
    edgeSecret: source[PILOT_EDGE_SECRET_ENV],
  };
}

/**
 * Derive the descriptor the shell renders.
 *
 * Args:
 *   env: The three `PILOT_*` values. With the mode unset, empty or `off` —
 *     every deployment on `main` — this function reads one string and returns
 *     the shared descriptor without looking at `headers` at all.
 *   headers: The incoming request's headers, or `null` when there are none to
 *     read (a render outside a request scope). `null` is not treated as a
 *     shared deployment: under pilot mode a page that cannot see the edge's
 *     proof has not been vouched for, and says so.
 *
 * Returns:
 *   `shared`, `pilot` with the edge-authenticated username, or `unresolved`.
 *   Never throws, and never carries a key, a key id or a fault.
 *
 * THE ONE FAULT THIS CANNOT SEE, AND WHY THAT IS DELIBERATE.
 * `readPilotConfig` also refuses a deployment that configures a pilot map
 * *and* `ARXIV_API_KEY` (`shared_key_also_set`) — two answers to "whose
 * credential is this". Detecting it requires reading the shared key, and
 * `web/tests/principal.test.ts` asserts that `lib/server/principal.ts` is the
 * ONLY module in the shipped tree that reads `ARXIV_API_KEY`; a second reader
 * is a second credential path, which is the thing 04 §1.3 constraint 1 says
 * needs its own ADR. So `undefined` is passed and the ambiguity check is
 * skipped here. Nothing is claimed falsely by that: under that fault the
 * proxy refuses **every** request with 503, so the deployment renders as
 * broken everywhere, and the question this module answers — who did the edge
 * authenticate — still has the answer it gives. `web/tests/
 * workspaceIdentity.test.ts` pins the behaviour so it is a decision rather
 * than an oversight.
 */
export function deriveWorkspaceIdentity(
  env: PilotEnv,
  headers: PilotHeaderReader | null,
): WorkspaceIdentity {
  const config = readPilotConfig(env, undefined);
  if (config.mode === "off") return SHARED_WORKSPACE_IDENTITY;
  // An operator's mistake refuses every request (guard 1), so it cannot be
  // rendered as anybody's workspace — and the reason is never shown: it names
  // which part of the configuration is broken, which is not a pilot's
  // business and not a browser's.
  if (config.mode === "misconfigured") return UNRESOLVED_WORKSPACE_IDENTITY;
  if (headers === null) return UNRESOLVED_WORKSPACE_IDENTITY;

  const resolution = resolvePilotPrincipal(config, { headers });
  if (!resolution.ok) return UNRESOLVED_WORKSPACE_IDENTITY;
  // `resolution.username` reached here through the topology guard, the
  // username pattern and the map, in that order (`lib/server/pilot.ts`), so it
  // is lower-case, bounded to 64 characters of `[a-z0-9._-]`, and a name the
  // operator issued. Nothing else off the request is carried.
  return { kind: "pilot", username: resolution.username };
}

/**
 * The descriptor for the request currently being rendered.
 *
 * Called by `app/(workspace)/layout.tsx` and `app/(learn)/layout.tsx`, which
 * are the two places `WorkbenchShell` is mounted.
 *
 * THE HEADERS ARE READ UNCONDITIONALLY, AND THAT IS LOAD-BEARING. Reading a
 * request header opts the segment into dynamic rendering, and a segment that
 * is dynamic is a segment whose layout runs again for every request. The
 * alternative — consult `PILOT_EDGE_AUTH` first and skip `headers()` when it
 * is off — would let a build that ran with the mode off (which is every
 * build: `deploy/pilot/compose.pilot.yml` sets the variable on the *container*
 * at run time, never as a build argument) prerender "Shared workspace" into a
 * static document and then serve that document to a pilot. The whole of this
 * work order would be defeated by a cache. `app/layout.tsx` already reads the
 * CSP nonce and therefore already makes every document route dynamic, so this
 * costs nothing measurable today; it is here so the guarantee is local to the
 * thing that depends on it rather than inherited from a file that could
 * change for unrelated reasons.
 */
export async function resolveWorkspaceIdentity(): Promise<WorkspaceIdentity> {
  const incoming = await incomingHeaders();
  return deriveWorkspaceIdentity(pilotEnvironment(process.env), incoming);
}

/**
 * The request's headers, or `null` when there is no request.
 *
 * The dynamic `import()` and the swallow are `lib/server/csp.ts`'s pattern and
 * exist for its reason: `next/headers` throws outside a request scope, and the
 * unit suite renders both layouts directly with no request at all. Outside a
 * request there is nothing to read and `null` is the honest answer; what
 * `deriveWorkspaceIdentity` does with it depends on the mode, and under pilot
 * mode it is `unresolved` rather than a guess.
 */
async function incomingHeaders(): Promise<PilotHeaderReader | null> {
  try {
    const { headers } = await import("next/headers");
    return await headers();
  } catch {
    return null;
  }
}
