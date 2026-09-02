/**
 * WO-W17b — the workspace identity descriptor, and nothing else.
 *
 * WHAT THIS MODULE IS FOR. `app/(workspace)/layout.tsx` and
 * `app/(learn)/layout.tsx` are server components; `components/app/
 * WorkbenchShell.tsx` is a client component. The value that crosses between
 * them has to be serialisable, and it has to be a value a browser is allowed
 * to hold. This file declares that value and holds no logic, so a client
 * module can name the type without pulling `lib/server/**` — or `node:crypto`
 * — into its graph.
 *
 * WHAT IT DELIBERATELY CANNOT CARRY. There is no `apiKey`, no `keyId`, no
 * `fault`, and no place to put one. That is the same structural argument
 * `PilotLogRecord` makes in `lib/server/pilot.ts`: a later edit that wanted to
 * hand the shell a key id "just for the tooltip" would have to widen this
 * type, and `web/tests/workspaceIdentity.test.ts` asserts the key set of every
 * descriptor the deriver can produce. The username IS carried, and only under
 * `pilot`: it is the pilot's own, the edge already showed it to them in the
 * browser's own credential dialog, and it is the whole point of the slot.
 *
 * WHY THREE KINDS AND NOT A BOOLEAN. `unresolved` is not a variant of
 * `shared`. Under `PILOT_EDGE_AUTH=on` a request the edge did not vouch for
 * gets no principal at all and every `/api` call it makes is refused (ADR
 * 0063, guard 3). Rendering that as "Shared workspace" would be the same lie
 * this work order exists to remove, one branch further along.
 */

/** Who the server resolved for the request that is rendering this page. */
export type WorkspaceIdentity =
  /** One principal for the whole deployment: every `main` deployment today. */
  | { readonly kind: "shared" }
  /** The pilot edge authenticated this request, and this is who as. */
  | { readonly kind: "pilot"; readonly username: string }
  /** Pilot mode is on and this request resolved to no principal at all. */
  | { readonly kind: "unresolved" };

/**
 * The default, and the only one a component may assume.
 *
 * `WorkbenchShell`'s `identity` prop defaults to this, which is what keeps
 * every story, every unit test and every render that predates this work order
 * byte-identical to what it produced before.
 */
export const SHARED_WORKSPACE_IDENTITY: WorkspaceIdentity = { kind: "shared" };

/** Pilot mode is on; this request is nobody's. Never rendered as `shared`. */
export const UNRESOLVED_WORKSPACE_IDENTITY: WorkspaceIdentity = {
  kind: "unresolved",
};
