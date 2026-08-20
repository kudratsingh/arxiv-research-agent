# 0039. Operator CLI for legacy NULL-owner rows

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh
- **Follows**: [ADR 0036](0036-per-principal-store-scoping.md) (per-principal scoping)

## Context

ADR 0036 added `principal_key_id` ownership to Job and Conversation.
Rows written before it have `principal_key_id = NULL`, and under
`enable_api_auth=True` the ownership check makes them invisible to
*every* principal — not leaked to the wrong tenant, which was the
point, but also not reachable by the right one. They are orphaned in
both stores: Redis `job:*` payloads simply lack the field, and
Postgres `conversations` rows hold a literal `NULL`.

ADR 0036 deliberately **rejected** auto-assigning an owner during its
own rollout. The reasoning still holds: any placeholder owner is
arbitrary, and the true owner is usually knowable only by reading the
`Job.query` text and recognising who asked it. Assigning a wrong owner
is worse than leaving the row unreachable, because it converts an
access problem into a cross-tenant disclosure. That ADR listed an
operator-driven cleanup tool as the follow-up; this is it.

The trigger for doing it now rather than later: with auth-on
deployments becoming the expected configuration, the population of
unreachable rows only grows, and nothing in the system reports how
many there are.

## Decision

A CLI, `python -m src.api.admin_migrate` (wrapped as `make
admin-migrate`), which a human drives. Not an automatic migration, not
a startup hook, and not an API endpoint.

The tool's real job is **to help an operator decide**, so `report` is
the default action and prints a bounded sample with a truncated query
preview alongside the counts. The mutating actions exist to carry out
a decision the operator has already made.

- Actions: `report`, `assign --owner KEY_ID`, `delete`.
- Scope: `--store {jobs,conversations,all}`, `--older-than-days N`,
  `--limit N`.
- **Dry-run by default.** Nothing writes without `--yes`; `report`
  never writes at all.
- Exit codes: 0 success (including a clean dry-run), 1 runtime error,
  2 usage or validation error.

The logic lives in small functions (`scan_null_owner_jobs`,
`assign_job_owner`, the four SQL builders) with a thin `main(argv)`
wiring argparse to them, so the behaviour is testable without a
subprocess.

### The four non-obvious correctness requirements

These are the parts that took the thinking, and each has a test:

1. **`assign --owner` validates the key against the live keystore**
   (`api_keys`, or `api_keys_file` when set, mirroring the resolution
   order in `create_app`). Assigning ownership to a key that does not
   exist would bury the data one level deeper than it already is.

2. **Rewriting a Redis row preserves its TTL** via `PTTL`. A plain
   `SET` would resurrect expired terminal jobs without their expiry,
   silently undoing ADR 0027's retention.

3. **Availability is decided by which store is *selected*, not by
   whether a URL is configured.** `postgres_url` is shared with the
   paper cache, the embedding cache and the ADR 0034 checkpointer, so
   gating the conversations half on it would point the tool at a
   `conversations` table the running service never reads. In exactly
   that configuration — which is what compose shipped — `delete --yes`
   would have destroyed another deployment's rows while reporting
   success. The check is on `conversation_store` / `job_store`.

4. **`delete` emits one structured log record per destroyed row.**
   Once a Redis key is gone there is no other surviving evidence of
   what it was, so an aggregate "deleted 412 jobs" could never answer
   "was mine one of them?" during an incident review. Volume is by
   definition the blast radius, which `--limit` already bounds.

## Alternatives considered

- **Auto-assign legacy `NULL` rows to a placeholder owner**, at
  startup or as a one-shot migration. Rejected for ADR 0036's original
  reason — an arbitrary owner turns an access problem into a
  disclosure problem.

- **An authenticated admin endpoint** rather than a CLI. Rejected for
  now: it needs a role model on `ApiKeyPrincipal` that does not exist
  yet (ADR 0036 deferred that too), and it would put a bulk-delete
  behind an HTTP surface before there is any audit trail or approval
  step in front of it. Shell access to a worker is a narrower
  privilege than a route.

- **Deleting the legacy rows outright, with no assign path.** Simpler,
  and the demo-scale expectation is that legacy data is disposable.
  Rejected because a production deployment that has been running with
  auth off may have real conversation history whose owner *is*
  determinable by inspection, and a tool that can only destroy makes
  that determination worthless.

- **Alembic or a migration framework.** Rejected: the schema does not
  change here. This is a data-repair tool, and the existing idempotent
  `SCHEMA_DDL` approach is what governs schema. Introducing a
  migration framework for one data fix would be a large, separate
  decision.

## Consequences

**Positive**

- Legacy `NULL`-owner data is reachable again, through a tool that
  makes the destructive paths explicit, bounded, and auditable.
- An operator can now answer "how much orphaned data is there?", which
  was previously unanswerable without a Redis client and a REPL.
- The dry-run-by-default shape means the dangerous invocation is
  strictly longer to type than the safe one.

**Negative**

- Another surface with direct store access that bypasses the API's
  ownership checks by design. It is only as safe as the operator
  running it.
- `--limit` bounds blast radius **per store**, so `--store all --limit
  N` can touch up to 2N rows. Documented in the help text.
- `scan_null_owner_jobs` holds every matched row in memory when
  `--limit` is omitted. Each row is an id, a timestamp and an 80-char
  preview, so a million orphans is roughly 100 MB. No hard default cap
  was added, because silently truncating a report an operator is about
  to act on would be worse than a large report.
- The tool cannot tell you the *correct* owner. That limitation is
  inherent to the problem ADR 0036 described, and is why the sample
  preview exists at all.

**Follow-ups**

- Role-based access on `ApiKeyPrincipal`, after which these actions
  could move behind an authenticated endpoint with a real audit trail.
- The Postgres half is currently exercised through its SQL builders
  and the unavailable-path branches; a `pytest-postgresql` test that
  runs the statements against a live server is the honest next step.
- Single-statement `DELETE ... WHERE principal_key_id = %s` to collapse
  the get+delete round trip on `DELETE /conversations` (carried over
  from ADR 0036).
