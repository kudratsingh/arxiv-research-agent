/**
 * IdentitySlot — seam S4 (04-ARCHITECTURE.md §10), and it returns `null`.
 *
 * D-009 is binding: the revamp must not fake login or per-user views. So
 * this component renders NOTHING. Not an avatar, not "Sign in", not a
 * disabled button, not a placeholder box — 03-DESIGN-BRIEF.md §6 is
 * explicit that "a disabled login button is still a fake login".
 *
 * WHAT IT IS FOR, THEN. Two things, both real:
 *
 *   1. A position in the header's DOM order that MT-01's account control
 *      will occupy without re-laying-out the header around it.
 *   2. A module name and an import site, so MT-01's diff is one file rather
 *      than a search for "where does the account menu go".
 *
 * The truthful content that occupies the header today is the workspace
 * indicator string beside it (`WORKSPACE_INDICATOR` in WorkbenchShell.tsx),
 * which says what is actually true of this deployment: the workspace is
 * shared. That string is the occupant; this slot is the reservation.
 *
 * A server component: no hooks, nothing to hydrate, no bytes in any route's
 * client chunk union.
 *
 * web/app/(workspace)/IdentitySlot.stories.tsx asserts that it renders
 * nothing at all (criterion 11's `IdentitySlot/Empty`), and
 * web/tests/shell/identity.test.tsx asserts the same against the rendered
 * shell — no `img`, no link or button whose name mentions signing in.
 */

export function IdentitySlot(): null {
  return null;
}
