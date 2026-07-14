# 0036. Per-principal Job + Conversation store scoping

- **Status**: accepted
- **Date**: 2026-07-13
- **Deciders**: kudratsingh
- **Follows**: [ADR 0033](0033-safety-hardening-bundle.md) (API-key auth)

## Context

ADR 0033 shipped the minimum viable auth surface — `X-API-Key`
header + per-key rate limits + CORS allowlist — and explicitly
deferred per-principal store scoping. Its trade-off: once auth is
on, only key holders can hit the endpoints, so the "any anonymous
caller reads any thread" issue is much reduced. But the audit
finding was broader than that: `GET /conversations` returned every
conversation from every user, and `DELETE /conversations/{id}`
succeeded regardless of who created it. Under auth-on, that means
one authenticated tenant can still read and destroy another
authenticated tenant's data.

That's a data-boundary issue, not an auth-surface issue, and it
lives at the store layer. Auth on its own can't fix it: the store
doesn't know who created a row, so the route can't check.

## Decision

Ship three changes as one bundle.

1. **`principal_key_id` on the resource.** Add
   `principal_key_id: str | None = None` to both `Job` and
   `Conversation` dataclasses. Set at creation from the caller's
   `ApiKeyPrincipal`; `None` under auth-off and on rows written
   before this ADR.
   - Redis: field is included in `_persistent_fields()` so it
     round-trips. `_job_from_json` reads `data.get("principal_key_id")`
     so legacy Redis rows deserialize cleanly with `None`.
   - Postgres: `principal_key_id TEXT NULL` on `conversations`.
     Migration uses `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
     alongside the CREATE, so `init_schema()` is idempotent on
     both fresh and upgraded databases. Partial index on
     non-NULL values so scans of the "all mine" query are cheap.

2. **Ownership helper in the route layer.**
   - `_check_ownership(resource_principal, caller, detail=...)`
     encapsulates the auth-off → allow / auth-on match → allow /
     mismatch → **404** rule. Not 403: leaking "this exists but
     you can't touch it" is an info-disclosure vector.
   - Legacy rows with `principal_key_id=None` are invisible under
     auth-on. Turning auth on effectively quarantines pre-ADR
     data until an admin cleanup migration decides who owns them.
   - `_principal_key_id(caller)` returns the key_id or `None`,
     so route handlers can stamp new rows without repeating the
     `if principal else None` guard.

3. **List filter pushed into the store.**
   `ConversationStore.list(principal_key_id: str | None = None)`.
   `None` means "return everything" (auth-off legacy behavior).
   Under auth-on the route passes the caller's key_id; the
   Postgres store rewrites the SQL to `WHERE principal_key_id = %s`
   so scaled deployments don't paginate through other tenants'
   rows. The in-memory store filters in Python.

Every route now takes `principal` as a parameter (via
`Depends(require_principal)`) instead of the router-level
`dependencies=[...]` shim, so handlers have the principal to hand
to `_check_ownership`. `submit_research` additionally checks that
the caller owns the `conversation_id` they're piggybacking on —
otherwise a cost-bearing job could pollute someone else's
retriever context.

## Alternatives considered

- **Filter in Python (skip the SQL push-down).** Rejected: fine
  at 100 conversations, painful at 100k. Once the shape is
  correct, moving it into SQL is a one-line change we might as
  well make now while the code is fresh.

- **Return 403 on mismatch.** Rejected: 403 confirms the ID
  exists, which is exactly what an attacker needs to enumerate
  another tenant's resources. 404 makes the response identical
  to "genuinely doesn't exist," matching GitHub / Stripe / most
  production APIs.

- **Admin bypass** — a super-key that sees everything. Deferred:
  adds a role hierarchy for a demo-scale service that doesn't
  need one. When it does need one, add it as a separate role
  claim on `ApiKeyPrincipal` rather than a magic key_id.

- **Migrate legacy `NULL` rows to a placeholder owner** during
  the ADR rollout. Rejected: the placeholder is arbitrary and
  the "correct owner" is often knowable from `Job.query`
  content only by inspection. Keeping legacy rows invisible under
  auth-on is safer than assigning them to a wrong principal.

- **Extend the JobStore Protocol with `list_by_principal`.**
  Rejected for jobs specifically: the route layer's ownership
  check runs after fetching a single job, and there's no
  `/research` list endpoint. If one is added later, the same
  pattern used for conversations applies.

## Consequences

**Positive**

- Two authenticated tenants can share the same deployment
  without leaking data across principals. Closes the audit's
  "info disclosure via `GET /conversations`" finding.
- Piggyback attack on `POST /research` with a stolen
  `conversation_id` is impossible: the caller must own the
  target conversation.
- The Postgres list query pushes the filter into SQL, so a
  future 100k-conversation deployment doesn't drag the full
  table over the wire per request.

**Negative**

- Legacy rows written before this ADR (both Redis and Postgres)
  have `principal_key_id=NULL`. Under auth-on they're invisible
  until an admin cleanup. The demo-scale expectation is that
  legacy data is disposable; a production deployment might need
  a one-time migration script.
- `DELETE /conversations/{id}` now does a fetch + delete pair
  under Postgres to check ownership before the destructive call.
  Two round trips instead of one. Fine at demo scale; a future
  optimization could use `DELETE ... WHERE conversation_id=%s
  AND principal_key_id=%s RETURNING 1` in a single statement.
- The `list()` method's signature changed. Any external callers
  of the `ConversationStore` Protocol need the new keyword arg;
  in-repo, all call sites are the route layer.

**Follow-ups**

- Optimize `delete_conversation` to a single SQL statement with
  the ownership check inline.
- Admin cleanup migration script for legacy `NULL`-owner rows.
- Extend the same pattern to Redis-persisted jobs if we add a
  list endpoint (`GET /research?principal=...`) — it doesn't
  exist today.
- Role-based access on `ApiKeyPrincipal` when a real admin
  workflow shows up.
