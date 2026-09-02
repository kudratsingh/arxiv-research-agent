# MT-01 — End-user multi-tenancy for the web UI

> ## ⚠ STATUS: PROPOSED
>
> **Nothing in this document is approved, decided, or implemented.**
> No code, config, schema, or deployment change described here exists
> on `main`. This is a [proposal](README.md), not an
> [ADR](../decisions/README.md) — an ADR will be written *if and when*
> a human approves one of the options below, and it will record what
> was actually decided rather than what this document recommends.
>
> Every option here costs money and engineering time. Read
> [§5 Phased delivery](#5-phased-delivery-plan-for-the-recommendation)
> before agreeing to anything: the first gate is deliberately cheap and
> the expensive gates are deliberately later.

- **Workstream**: MT-01
- **Date**: 2026-08-28
- **Decider**: kudratsingh — **pending**; nothing here is decided (see §8)
- **Raised by**: [`docs/revamp/DECISIONS.md` D-009](../revamp/DECISIONS.md#d-009--gate-1-human-decisions)
  — the user rejected the shared-principal deployment model as the end
  state at Gate 1 of the frontend revamp
- **Scope**: backend + edge + web auth layer. **Explicitly outside**
  the frontend revamp's frozen-backend boundary
  ([D-002](../revamp/DECISIONS.md), D-009 consequence 3)
- **Builds on**: ADR [0033](../decisions/0033-safety-hardening-bundle.md),
  [0036](../decisions/0036-per-principal-store-scoping.md),
  [0037](../decisions/0037-redis-rate-limiter-and-keystore-reload.md),
  [0039](../decisions/0039-admin-null-owner-migration.md),
  [0042](../decisions/0042-api-guardrails-and-deploy-hygiene.md),
  [0043](../decisions/0043-conversation-store-hardening.md),
  [0054](../decisions/0054-hetzner-production-boundary.md)

---

## 1. Problem statement

### 1.1 The backend is already multi-tenant

Per-principal data ownership is not missing. It shipped in ADR 0036 and
was hardened by ADR 0043. Concretely, on `main` today:

- Both durable resources carry an owner column:
  `Job.principal_key_id` (`src/api/jobs.py:90`) and
  `Conversation.principal_key_id` (`src/api/conversations.py:82`),
  backed in Postgres by `principal_key_id TEXT NULL` plus a partial
  index on non-NULL values (`src/tools/postgres_pool.py:71-91`) and in
  Redis by the `_persistent_fields()` round-trip
  (`src/api/redis_store.py:157,182,255`).
- Rows are stamped at creation from the authenticated caller —
  `src/api/routes.py:184` for jobs, `src/api/routes.py:550` for
  conversations, both via `_principal_key_id()`
  (`src/api/routes.py:87-93`).
- Reads and mutations are ownership-checked. `_check_ownership()`
  (`src/api/routes.py:59-84`) returns **404, not 403**, on a mismatch
  so an attacker cannot enumerate another tenant's ids; it is wired
  into every job route (`src/api/routes.py:231,259,363,432`).
- Listing pushes the filter into SQL rather than filtering after the
  fact (`src/api/routes.py:586-590` →
  `src/api/conversations.py:362-364`), and delete carries the owner
  inline in a single statement (`src/api/routes.py:645-648` →
  `src/api/conversations.py:540-542`).
- Cross-tenant piggybacking on `POST /research` is blocked: a caller
  submitting into a `conversation_id` must own it
  (`src/api/routes.py:173-177`), which is what keeps another
  principal's prior-report context out of the planner prompt.
- The rate limiter buckets per principal
  (`src/api/auth.py:538`), Redis-backed so the bucket holds across
  workers (ADR 0037; `src/api/auth.py:229-297`).

The property this buys is real and tested — `tests/test_api_auth.py`
and `tests/test_per_principal_scoping.py` prove that principal B gets
404 on principal A's conversations, on delete, and on the piggyback
path (`docs/security.md:392-402`).

### 1.2 The web layer collapses every browser user into one principal

> **Note added 2026-09-02 — seam S1 now carries a pilot mode, and this
> document is still `PROPOSED`.** WO-W17 shipped a default-off,
> topology-guarded mapping at exactly the seam §5.7 names: with
> `PILOT_EDGE_AUTH=on`, the pilot edge authenticates one `basic_auth`
> user per pilot and `resolveUpstreamPrincipal` maps that username to
> that pilot's per-principal key
> ([ADR 0063](../decisions/0063-pilot-principal-edge-mapping.md),
> `web/lib/server/pilot.ts`). It is a deliberately hand-run slice of
> §3's **Option C1**, sized for five invited people over fourteen days,
> and it implements §6's **T6** mitigation verbatim — off by default,
> explicit opt-in, never inferable, with the trust asserted by a shared
> header secret rather than assumed from the network layout.
>
> **This does not approve, decide, or partially implement MT-01.** No
> option below is chosen, no gate is passed, and nothing in §5 is built.
> MT-01 **replaces** the pilot mapping rather than growing from it: ADR
> 0063 is marked to be superseded, its whole surface is one web-tier
> module plus a deploy overlay, and none of §1.3's five findings is
> fixed by it — F1 is handled by a human rule in
> `docs/runbooks/pilot.md`, and F3, F4 and T7 are unchanged. The
> paragraphs below describe the deployment with the mode off, which is
> every deployment on `main`.

The Next.js server proxy attaches a single process-wide API key to
every upstream request, with no per-request identity of any kind:

```ts
// web/app/api/[...path]/route.ts:81-82
const apiKey = process.env.ARXIV_API_KEY;
if (apiKey) headers.set("X-API-Key", apiKey);
```

**That is the injection point, and it is the entire problem.** Two
different humans in two different browsers produce two requests that
are byte-identical at the FastAPI boundary. `require_principal`
(`src/api/auth.py:480-518`) resolves both to the same
`ApiKeyPrincipal`, so ADR 0036's ownership check
(`src/api/routes.py:78-84`) correctly concludes that both of them own
everything the other one created. The scoping machinery is working
exactly as designed; it is being fed one identity.

The deployment wiring confirms this is the intended shape today, not a
misconfiguration:

- Base compose passes the secret through as `ARXIV_API_KEY`
  (`docker-compose.yml:125`) with auth off by default
  (`docker-compose.yml:94`).
- The production overlay uses **the same `WEB_API_KEY` value** for both
  halves: it is the whole keystore
  (`API_KEYS: web:${WEB_API_KEY}`, `deploy/hetzner/compose.prod.yml:15`)
  and the proxy's injected key
  (`ARXIV_API_KEY: ${WEB_API_KEY}`, `deploy/hetzner/compose.prod.yml:27`).
  The deployed keystore has exactly one entry, named `web`.
- The only human-facing gate is Caddy `basic_auth` with one
  username/password pair (`deploy/hetzner/Caddyfile:8-10`). ADR 0054
  says so in its own consequences: *"Caddy basic auth is intentionally
  a one-user gate, not product identity or multi-tenant browser
  authorization"* (`docs/decisions/0054-hetzner-production-boundary.md:131-132`).
- The frontend discovery reached the same conclusion independently and
  raised it as a blocking Gate 1 question: *"The current Caddy + one
  server-side API key architecture is not end-user multi-tenancy"*
  (`docs/revamp/00-DISCOVERY.md:367`).

So the product is a **shared single-owner workspace with a shared
password**. Everyone who gets through Caddy sees everyone else's
research, can delete it, and spends from the same budget.

### 1.3 Five findings that constrain every option

These came out of reading the auth and scoping code and are not
documented as multi-tenancy constraints anywhere else. Each one shapes
the options in §3.

**F1 — `key_id` is simultaneously the owner token, the rate-limit
bucket, and a human display name, and it is permanent.** It is the
`name` half of a keystore entry (`src/api/auth.py:99`), what gets
stamped on every row (`src/api/routes.py:87-93`), and what the limiter
buckets on (`src/api/auth.py:538`). `docs/security.md:145-149` states
the consequence: renaming a key orphans that principal's rows;
reusing a retired name hands the new holder the previous tenant's
data. Both parsers reject duplicate names for exactly this reason
(`src/api/auth.py:94-98`, `src/api/auth.py:350-359`). Any option that
mints one principal per user inherits a requirement for globally
unique, never-reused, immutable user identifiers. `docs/security.md:463-466`
already carries the fix as an open follow-up — *derive the stored owner
from the secret as a stable `owner_id` instead of the mutable display
name* — and MT-01 is what forces it.

**F2 — key lookup is deliberately O(number of keys) per request.**
`_lookup_principal` (`src/api/auth.py:127-133`) runs
`hmac.compare_digest` against **every** configured secret and
deliberately does not short-circuit, because early return leaks timing
about which prefix matched. That is the right call at the current
scale — the deployed keystore has one entry. It is a per-request cost
of N constant-time comparisons if the keystore becomes the user table,
paid on every poll, every export, and every SSE reconnect. At a few
hundred users this is unremarkable; at ten thousand it is a hot-path
regression with no index to add, because the whole point is that the
loop is uniform.

**F3 — the keystore is a plaintext JSON `{name: secret}` file with
~30s propagation.** `load_keystore_from_file`
(`src/api/auth.py:332-389`) parses cleartext secrets; there is no
hashing path. `KeystoreReloader` polls mtime
(`src/api/auth.py:451-477`) at `api_keys_reload_interval_sec`, default
30 (`src/config.py:230-238`). Using it as a user credential store means
plaintext per-user credentials at rest **and** up to 30 seconds of
revocation latency — the number that matters when you are trying to
lock out a compromised account. `initial_load` also raises on a bad
parse (`src/api/auth.py:416-430`), so a signup writer that corrupts the
file blocks the next worker restart.

**F4 — the cost ceiling is per *run*, and there is no aggregate cap
anywhere.** `max_cost_usd` is documented and enforced as a per-run
ceiling (`src/config.py:598-607`, `docs/security.md:110-123`). The
hourly limiter is per principal (`src/api/auth.py:538`) at
`api_key_hourly_limit`, default 100 (`src/config.py:196-205`). Today
one shared principal means one shared budget — which the frontend
discovery already logged as a usability defect (*"twenty hourly slots
permit only ten fresh landing-page runs"*,
`docs/revamp/00-DISCOVERY.md:348`, because ADR 0043 made
`POST /conversations` draw from the same bucket,
`docs/decisions/0043-conversation-store-hardening.md:95-99`). Give each
user their own bucket and the deployment's worst-case hourly exposure
becomes `n_users × api_key_hourly_limit × max_cost_usd`, against a
single Anthropic account, with **no global stop anywhere in the
codebase**. This is the single most dangerous consequence of MT-01 and
it is a prerequisite, not a follow-up.

**F5 — auth-off does not mean "no tenancy", it means "everyone owns
everything".** `_check_ownership` returns early when `caller is None`
(`src/api/routes.py:78-79`), and base compose ships
`ENABLE_API_AUTH=false` (`docker-compose.yml:94`). MT-01 therefore
makes `enable_api_auth=true` a hard requirement of any deployment that
has more than one human on it, and makes the auth-off local-dev path a
mode that must be kept obviously distinct rather than a smaller version
of production.

Two smaller notes worth carrying forward:

- The runner re-fetches the conversation to build prior context
  **without re-checking ownership** (`src/api/runner.py:1005-1007`); it
  relies entirely on the submit-time check at
  `src/api/routes.py:173-177`. Correct today, and a seam that must hold
  for any future job-creation path.
- Jobs have no list endpoint and no `list_by_principal` — ADR 0036
  deferred it explicitly
  (`docs/decisions/0036-per-principal-store-scoping.md:95-99`). A
  per-user "my runs" view is new backend work under every option.

---

## 2. Goals and non-goals

### Goals

1. Two humans using the same deployment cannot see, resume, export, or
   delete each other's jobs and conversations — enforced by the ADR
   0036 machinery that already exists, fed a real per-user principal.
2. A user's identity survives a browser reload and a new device, and is
   revocable by an operator within a stated, short, and *measured*
   time budget.
3. The deployment's total spend stays bounded by an operator-set
   ceiling regardless of how many users exist or how they behave (F4).
4. Existing data reaches a decided end state — owned, archived, or
   deleted — with an auditable, dry-run-first tool, following the ADR
   0039 precedent.
5. The frontend revamp is never blocked by, and never silently
   inherits, this workstream. MT-01 lands behind flags that the revamp
   can ignore.
6. Local development and the eval runner keep working with no identity
   provider and no accounts, exactly as they do today.

### Non-goals

1. **Public self-serve signup.** Not proposed. Every option here
   assumes a bounded, operator-controlled user set (invite, allowlist,
   or an identity provider's own membership). Opening signup to the
   internet is a separate decision with its own abuse, cost, and
   moderation surface.
2. **Billing, plans, quotas-as-a-product, or usage attribution for
   invoicing.** F4's global cap is a *safety* ceiling, not a metering
   system.
3. **Organizations, teams, sharing, or per-resource ACLs.** One user
   owns their own data; there is no "share this conversation" concept.
   The 404-not-403 rule (`src/api/routes.py:82-84`) assumes binary
   ownership and sharing would reopen that design.
4. **A role/permission model beyond the minimum.** An admin role has
   been deferred three times
   (`docs/decisions/0036-per-principal-store-scoping.md:84-87`,
   `docs/decisions/0039-admin-null-owner-migration.md:139-141`,
   `docs/security.md:449-452`). MT-01 should decide whether it is now
   in scope (open question Q5) rather than assume it.
5. **Retiring `X-API-Key` for machine clients.** The eval runner, CLI,
   and any future programmatic client keep the existing mechanism.
6. **SSO/SCIM provisioning, audit-log export, or compliance
   attestations.**
7. **Per-user isolation of the derived caches.** `paper_cache` and
   `embedding_cache` carry no owner by design
   (`src/tools/postgres_pool.py:35-64`) and stay shared — see §7.3.

---

## 3. Options

All three assume `enable_api_auth=true` (F5) and all three require the
global spend cap (F4). Those are not differentiators; they are the
floor.

### Option A — Session→principal mapping in the Next.js proxy

This is the shape D-009 guessed at: *"most plausibly a web login/session
mapped to per-user principals in the Next.js proxy"*
(`docs/revamp/DECISIONS.md:104-106`).

**Design sketch.** Next.js gains a login route and a signed, httpOnly,
`SameSite` session cookie. A server-side user record maps a session to
a `(key_id, secret)` pair. The proxy's single line
(`web/app/api/[...path]/route.ts:81-82`) becomes a per-session lookup:
resolve the session, fail 401 if absent, inject *that user's* secret.
Provisioning writes a new `{name: secret}` entry into the file behind
`api_keys_file`, atomically (write-tmp-rename, which ADR 0037 already
relies on,
`docs/decisions/0037-redis-rate-limiter-and-keystore-reload.md:142-144`),
and `KeystoreReloader` (`src/api/auth.py:392-477`) picks it up without
a restart. FastAPI is untouched on the happy path.

**Where the user records live is the unresolved question.** The `web`
container has no database today — its entire environment is
`API_INTERNAL_BASE` and `ARXIV_API_KEY`
(`docker-compose.yml:124-125`, `deploy/hetzner/compose.prod.yml:26-27`).
Three sub-options, all bad in different ways:

- *A1: the keystore file is the user database.* Cheapest, and walks
  straight into F2 (O(N) lookup per request), F3 (plaintext credentials
  at rest, 30s revocation latency), and a file that a web-tier process
  now writes and an API-tier process parses-or-crashes
  (`src/api/auth.py:416-430`).
- *A2: give `web` its own datastore.* Correct, and adds a container or a
  second Postgres role to a 4 GB box the discovery already flags as
  tight (`docs/revamp/00-DISCOVERY.md:308`).
- *A3: give `web` credentials to the existing Postgres.* Avoids new
  infrastructure and hands the browser-facing tier direct database
  access, which is precisely the boundary ADR 0054 built the network
  topology to prevent (`deploy/hetzner/compose.prod.yml:12,24` — neither
  `app` nor `web` publishes a port).

**Security posture.** You are building an authentication system —
password storage, hashing, login throttling, reset, session lifecycle —
in TypeScript, in the tier that today holds exactly one secret and no
user data. The credential custody problem is entirely yours. Session
fixation, account enumeration on login/reset, and CSRF (§6) are all new
and all yours. On the plus side, the blast radius is genuinely
contained: a bug here cannot corrupt the ownership check, because the
ownership check is not changing.

**Blast radius.** `web/` grows an auth subsystem and its tests.
`src/api/` changes only for the F4 cap and (if a "my runs" view is
wanted) a jobs list endpoint. `deploy/` needs the keystore volume to
become writable by the right container.

**Migration burden.** Existing production rows are owned by the literal
string `web` (`deploy/hetzner/compose.prod.yml:15`) — **not** NULL. ADR
0039's tool targets NULL-owner rows specifically (`scan_null_owner_jobs`,
`docs/decisions/0039-admin-null-owner-migration.md:42-48`), so it does
not apply as-is; it needs a new predicate. See §7.

**Operational cost.** Low if you accept A1's compromises; medium
otherwise. No external dependency, works offline, no recurring fee.
Ongoing cost is the one nobody budgets: you now operate a credential
system, including the support load of password resets and lockouts.

**What the frontend shell needs.** A login page, a logout control, a
"signed in as" affordance, 401→login redirect in the data layer, and
per-user rate-limit error copy. This is the largest frontend ask of the
three options.

### Option B — First-class backend user/account model

**Design sketch.** `users` and `sessions` (or refresh tokens) tables in
the existing Postgres, following the idempotent `SCHEMA_DDL` pattern
(`src/tools/postgres_pool.py:71-91`). `require_principal`
(`src/api/auth.py:480-518`) grows a second resolver — bearer token or
cookie — that returns a principal carrying a stable `user_id` and,
optionally, a role. `X-API-Key` stays for machine clients. The owner
column becomes a stable `owner_id`, closing `docs/security.md:463-466`
structurally rather than by convention. Password hashing (argon2 or
bcrypt), email verification, reset, and session revocation are all
in-scope backend work.

**Security posture.** The strongest and the most conventional: one
identity concept, one place to reason about it, revocation is a row
update rather than a 30-second poll, and credentials are hashed. It is
also, honestly, the largest greenfield security surface in this
repository's history, and every component of it — reset tokens, session
fixation, timing on login, enumeration on signup — is a known footgun
that this codebase has never had to get right before. ADR 0033 rejected
exactly this direction once already, on the grounds that it *"adds an
identity provider dependency (or an in-repo OIDC issuer) that dwarfs
the actual security problem"*
(`docs/decisions/0033-safety-hardening-bundle.md:102-106`). D-009
changes the requirement, not that arithmetic.

**Blast radius.** The widest by a distance: `src/api/auth.py`, every
handler's `Depends` in `src/api/routes.py`, both stores, the Postgres
schema, `src/api/admin_migrate.py`, the whole auth test suite
(`tests/test_api_auth.py`, `tests/test_per_principal_scoping.py`,
`tests/test_keystore_reloader.py`), plus the same frontend work as
Option A. It reaches into files the frontend revamp is treating as
frozen.

**Migration burden.** The column type is not the problem —
`principal_key_id TEXT` already holds an arbitrary string. The problems
are (a) deciding what `web` and NULL mean, and (b) doing it without a
migration framework: ADR 0039 explicitly rejected Alembic for a data
fix (`docs/decisions/0039-admin-null-owner-migration.md:105-108`) and
`SCHEMA_DDL` is idempotent-DDL-only. A column *rename* (to `owner_id`)
is a genuine two-phase migration with dual writes, which is a larger
decision than it looks.

**Operational cost.** Highest, and permanently. No new infrastructure,
but every credential-system operational burden is now in-house, and the
support surface is real.

**What the frontend shell needs.** Everything Option A needs, plus
signup, email verification, and password-reset flows.

### Option C — External identity at the edge, mapped to principals

**Design sketch.** Replace Caddy's `basic_auth`
(`deploy/hetzner/Caddyfile:8-10`) with an OIDC forward-auth — an
`oauth2-proxy` sidecar, or Caddy's security plugin — in front of the
existing `reverse_proxy web:3000` (`deploy/hetzner/Caddyfile:29`). The
identity provider (Google, GitHub, Auth0, a self-hosted Authentik) owns
credentials entirely. The edge authenticates the browser and forwards a
trusted identity header. Two variants:

- *C1 — map in the Next.js proxy.* The proxy reads the trusted header
  and swaps line `web/app/api/[...path]/route.ts:81-82` for a lookup
  from IdP subject → per-user upstream key. Backend untouched.
- *C2 — map in FastAPI.* `require_principal` gains a
  trusted-header resolver behind a flag; the proxy forwards the header
  instead of a key. Removes the per-user key entirely, at the cost of
  moving trust onto a header.

**Security posture.** The best credential custody available: this
repository never stores a password, never hashes one, never emails a
reset link, and never has a credential database to leak. It also moves
the entire model onto *"the identity header is trustworthy"*, which is
only true if nothing can reach `web` or `app` except the edge. That is
true in the production overlay today — neither service publishes a port
(`deploy/hetzner/compose.prod.yml:12,24`) — and **false** in base
compose, which publishes both to loopback
(`docker-compose.yml:44,126`). A resolver that is safe in production and
unsafe locally is exactly the failure shape ADR 0039 documented when it
found availability being decided by the wrong signal
(`docs/decisions/0039-admin-null-owner-migration.md:70-76`). The
mitigation is that the header resolver must be off by default, must
require an explicit opt-in setting, and must never be inferable from
"a URL happens to be configured".

Note also that the IdP `sub` claim — not email — must be the mapping
key. Email is mutable and reassignable, and F1 says a reassigned
identifier hands one user another user's data.

**Blast radius.** The smallest inside the application. `deploy/` gains
a container and Caddyfile changes; `web/` gains a header read and a
logout link; under C1 `src/api/` changes only for F4. Under C2 the
change is one new resolver in `src/api/auth.py` plus a setting.

**Migration burden.** Identical to Option A — rows owned by `web`, plus
a stable `sub`→principal mapping table that has to live somewhere
(which reintroduces a small slice of Option A's "where do records
live" question, though for a mapping rather than for credentials).

**Operational cost.** An extra container and an external dependency.
On the selected CX23 with 4 GB RAM
(`docs/revamp/00-DISCOVERY.md:308`, which already flags the memory
budget as unresolved) `oauth2-proxy` is small but not free, and a
self-hosted IdP is not small. A hosted IdP is a recurring bill and a
login-path single point of failure that this deployment does not have
today. Client-secret rotation becomes an operational task.

**What the frontend shell needs.** The least: a "signed in as" display,
a logout link pointing at the edge's sign-out URL, and 401 handling.
The IdP owns the login UI, so the revamp's *reserved login surface*
(D-009 consequence) may end up being a redirect rather than a page —
which is a cheaper thing to reserve.

---

## 4. Comparison and recommendation

### 4.1 Comparison

| Dimension | A — Session in proxy | B — Backend accounts | C — Edge identity (C1) |
|---|---|---|---|
| Credential custody | **Ours** (plaintext under A1) | **Ours** (hashed, done properly) | **The IdP's** — we store none |
| New security surface | Auth system in the web tier | Largest in repo history | Header-trust boundary |
| Backend blast radius | Small (F4 cap only) | Very large (auth, routes, stores, schema, tests) | Small (F4 cap only) |
| Frontend blast radius | Large (login, session, reset) | Largest (adds signup/verify) | Small (identity display + logout) |
| Revocation latency | ~30s worst case (F3) | Immediate (row update) | IdP session + edge cookie TTL |
| Scaling of key lookup | O(users) per request (F2) | Indexed lookup | O(users) under C1; O(1) under C2 |
| Respects ADR 0054 network boundary | A3 violates it | Yes | Yes (and *depends* on it) |
| Migration burden (`web`-owned rows) | New `admin_migrate` predicate | Same, plus possible column migration | New `admin_migrate` predicate |
| Recurring cost | None | None (but high support load) | IdP fee and/or RAM for a sidecar |
| External dependency | None | None | **Yes** — login fails if IdP is down |
| Local dev / eval unaffected | Yes | Yes, if flagged off | Yes, if flagged off |
| Honest effort estimate | Medium-large | Large | Small-medium + one infra decision |

### 4.2 Recommendation

**Recommended: Option C1 — OIDC at the edge, mapped to per-user
principals in the Next.js proxy — with the global spend cap (F4)
delivered first as a hard prerequisite.**

D-009 hypothesised Option A
(`docs/revamp/DECISIONS.md:104-106`), and this proposal argues against
it on the evidence. That disagreement is the point of writing the
document, and the human decision (Q2, §8) can overrule it.

Rationale:

1. **The dominant risk in MT-01 is credential custody, and C removes it
   rather than managing it.** A and B both end with this repository
   holding user credentials. F3 shows the existing keystore is
   plaintext with no hashing path, so A1 is unacceptable and A2/A3 mean
   building the storage anyway. C is the only option where the worst
   security bug we can write does not leak a password.
2. **Option A's "minimal backend change" framing is misleading.** It is
   minimal in `src/api/` and maximal in `web/`: it builds most of
   Option B's authentication system in the tier with the least
   security tooling, no database, and no existing auth tests. The
   backend line count is small because the work moved, not because the
   work shrank.
3. **C replaces a mechanism the repo has already declared inadequate.**
   ADR 0054 wrote down that its basic-auth gate *is not* product
   identity (`docs/decisions/0054-hetzner-production-boundary.md:131-132`).
   C upgrades that gate in place. A and B add a second, parallel
   authentication mechanism and leave the first one there.
4. **It preserves both revamp constraints.** D-002's Next.js server
   boundary is untouched — the proxy still injects a server-only key,
   just a per-user one. And the frozen-backend rule holds: under C1 the
   only backend change is the F4 cap, which is a safety fix that stands
   on its own merits.
5. **C1 over C2** because C1 keeps the trusted header confined to the
   edge↔web hop and leaves FastAPI's authentication model exactly as it
   is — one mechanism, `X-API-Key`, tested. C2's flagged header
   resolver is a second authentication path into the API whose safety
   depends on network topology, and §3's ADR-0039 analogy says that is
   the class of thing this codebase has been bitten by before. C2
   remains the right answer *if* per-user keys prove operationally
   painful at scale (F2), and the migration C1→C2 is contained.

**Recommended fallback if an external IdP dependency is rejected
(Q2): Option B, not Option A.** If we must own credentials, we should
own them in the tier that has the database, the schema discipline, the
test suite, and the security review history — not in the browser-facing
proxy.

**What would change this recommendation:** an answer to Q1 of "one
small trusted team, invite-only, ≤10 people" makes C's recurring cost
and external dependency look heavy relative to the risk it removes, and
makes a *hand-provisioned* variant of A2 defensible. Conversely, any
answer involving people outside the operator's direct control makes C
stronger still.

---

## 5. Phased delivery plan for the recommendation

Six phases, each ending at a human gate. **No phase begins until the
prior gate is answered.** Gates MT-C onward each carry an explicit
cost line, because MT-01 is the first workstream in this repository
that can incur a *recurring* bill.

Standing rules for the whole workstream:

- **No paid model or API calls without separate written approval.**
  This follows the D-004 precedent
  (`docs/revamp/DECISIONS.md:33-41`): synthetic local data and a
  deliberately invalid Anthropic key are the default for anything that
  needs a populated state.
- **Every phase ships behind a default-off flag** and leaves
  `docker compose up` a zero-config, auth-off, single-user demo
  (`docker-compose.yml:94`).
- **MT-01 never lands a change the frontend revamp must adopt to keep
  working.** See §5.7.

### 5.1 Gate MT-A — approve the direction (this document)

**Deliverable**: this proposal. **Cost so far**: documentation only.
**Decision needed**: which option, plus answers to §8's questions —
particularly Q1 (who are the users), Q2 (is an external IdP
acceptable), and Q3 (the spend ceiling). **Exit**: an approved option,
or a rejection that closes MT-01.

Nothing below this line is authorized by this document.

### 5.2 Phase 0 — Global spend cap (prerequisite, no identity work)

Delivers F4: an operator-set aggregate ceiling that binds independent
of how many principals exist. It is the only piece of MT-01 that is
worth shipping **even if MT-01 is cancelled**, because it also bounds
the existing single-key deployment. It needs its own ADR and touches
the cost-enforcement choke point that ADR 0051 established
(`docs/security.md:110-123`).

Scope: a deployment-wide budget and its enforcement point; a decision
on the window (rolling hour / day / month) and on the failure mode
(refuse new submits vs. degrade). Explicitly *not* metering or
billing.

**Gate MT-B** — the operator confirms the ceiling value, the window,
and what a user sees when the deployment is at its cap. Blocking:
**per-user principals must not be enabled before this ships**, because
the moment they exist the aggregate exposure multiplies (F4).

### 5.3 Phase 1 — Identity spike, non-production, no user-visible change

An `oauth2-proxy` (or equivalent) in front of Caddy in a local overlay
only. Proves: the IdP round-trip works; the trusted header arrives at
`web`; the header cannot be spoofed from outside the edge; sign-out
works; and the SSE path survives the edge (native `EventSource` cannot
set headers — `web/lib/useResearchStream.ts:121` — so the session must
be cookie-borne through the whole stream, which is the specific thing
to prove rather than assume).

Also settles the stable-identifier question (F1): `sub`, not email; and
what the principal name derived from it looks like given that
duplicate names are rejected (`src/api/auth.py:350-359`).

**Gate MT-C** — review the spike. **Cost checkpoint**: choose the IdP
and state its recurring cost, and decide whether the CX23/4 GB target
absorbs the extra container or MT-01 forces a resize
(`docs/revamp/00-DISCOVERY.md:308`). A resize is a recurring
infrastructure bill and needs explicit approval.

### 5.4 Phase 2 — Per-user principal mapping and provisioning

The proxy stops reading `process.env.ARXIV_API_KEY`
(`web/app/api/[...path]/route.ts:81-82`) and starts resolving a
per-user principal from the edge identity. Provisioning creates the
principal on first successful login for an allowlisted subject.
Includes the §6 hardening: origin checking on the proxy's mutating
methods, and a decision on `X-API-Key` fallback for machine clients.

Ships **flag-gated and off**; the single-key path remains the default
until Gate MT-E.

**Gate MT-D** — review the security posture against §6 before anything
is enabled anywhere.

### 5.5 Phase 3 — Data migration (irreversible)

Extend `src/api/admin_migrate.py` with a reassign predicate for
`web`-owned rows, preserving every ADR 0039 safety property: dry-run by
default, `--yes` to write, Redis TTL preservation
(`docs/decisions/0039-admin-null-owner-migration.md:69-72`), one
structured log record per destroyed row
(`docs/decisions/0039-admin-null-owner-migration.md:77-82`), and
`--limit`/`--older-than-days` bounds. See §7.

**Gate MT-E** — the operator decides the fate of existing data (Q4)
and personally runs the migration after reviewing a `report` output.
This gate is destructive and cannot be un-run.

### 5.6 Phase 4 — Cutover, then Phase 5 — hardening

Cutover flips the flag in the production overlay, retires
`basic_auth` from the Caddyfile, and rotates `WEB_API_KEY`. Rollback is
the flag plus the previous Caddyfile — which is only true while the
single-key path still exists, so **do not delete it in the same
change**.

**Gate MT-F** — go/no-go on the production cutover.

Phase 5 collects what deliberately did not block cutover: a jobs
`list_by_principal` for a "my runs" view (deferred by ADR 0036,
`docs/decisions/0036-per-principal-store-scoping.md:95-99`); the stable
`owner_id` derived from the secret (`docs/security.md:463-466`); a
per-principal conversation ceiling (`docs/security.md:460-462`); and
the role model, if Q5 says yes.

### 5.7 Interaction with the frontend revamp

D-009 requires the revamp's Phase 2 brief to design the shell so
identity *can* be added without rearchitecture — navigation, ownership
affordances, and a reserved login surface — while the implemented
revamp keeps targeting the single-principal proxy
(`docs/revamp/DECISIONS.md:99-106`). Two seams therefore touch both
workstreams, and both are one-directional:

1. **The reserved login surface.** MT-01 should publish, at Gate MT-C,
   whether identity arrives as a redirect to an external IdP (C) or as
   an in-app page (A/B), because those reserve differently. Until then
   the revamp reserves the more general shape. MT-01 does **not** get to
   require the revamp to build it.
2. **401 handling in the data layer and proxy.** The proxy already
   forwards `www-authenticate` and returns upstream status verbatim
   (`web/app/api/[...path]/route.ts:19-25,110-114`), and the client has
   an `ApiError` carrying status (`web/lib/api.ts:15-23`). A 401 today
   means "the server key is wrong"; after MT-01 it means "your session
   expired". The revamp can render a generic recoverable-auth-error
   state that is correct under both without knowing MT-01 exists.

**The rule, stated so it can be enforced:** MT-01 must never merge a
change that breaks the revamp's single-principal target, and the revamp
must never merge a change that simulates identity (D-009 consequence 3).
If MT-01 needs a frontend change the revamp has not built, MT-01 builds
it behind MT-01's flag. Neither workstream's gate approves the other's
cost.

---

## 6. Threat-model deltas versus `docs/security.md`

[`docs/security.md`](../security.md) currently models one class of
caller: a key holder. It has no concept of a session, a login, or a
human identity. These are the deltas MT-01 introduces. **None of them
is defended today because none of them exists today.**

| # | New threat | Why it is new | Where it lands |
|---|---|---|---|
| T1 | Session fixation / session riding | No session concept exists in `docs/security.md` | Edge (C) or web tier (A/B) |
| T2 | CSRF against the proxy's mutating routes | Today there is no ambient browser credential | `web/app/api/[...path]/route.ts` |
| T3 | Per-user key custody at rest | Keystore is plaintext (F3) | `src/api/auth.py:332-389` |
| T4 | Aggregate spend explosion | Per-run cap only (F4) | `src/config.py:598-607` |
| T5 | Account enumeration | Resource enumeration is closed; accounts are new | Login/provisioning surface |
| T6 | Identity-header spoofing | Trust model becomes topological (C) | Edge ↔ `web` hop |
| T7 | Revocation latency | 30s keystore poll (F3) | `src/config.py:230-238` |
| T8 | Admin surface without a role model | `admin_migrate` bypasses ownership by design | `src/api/admin_migrate.py` |

**T1 — session fixation and session management.** Under C the IdP owns
the user session, but the edge proxy's own cookie is a new asset with
its own TTL, rotation, and sign-out semantics. Requirements: rotate the
session identifier on login, `httpOnly` + `Secure` + `SameSite`, a
short absolute lifetime, and a sign-out that invalidates server-side
rather than only clearing the cookie. Under A/B all of this is ours to
build.

**T2 — CSRF on the proxy.** This is the sharpest delta. The proxy
accepts `POST` and `DELETE` (`web/app/api/[...path]/route.ts:36-49`)
and performs **no origin check, no `Sec-Fetch-Site` check, and no CSRF
token**. It is safe today only by accident of architecture: the sole
credential is a server-side env var, so a cross-site request would be
authenticated anyway, and Caddy's shared basic-auth is the actual gate.
The moment a session cookie exists, the cookie is ambient, the browser
attaches it cross-site, and the proxy dutifully injects the upstream
key — turning any page on the internet into a trigger for a *paid,
non-idempotent* research submission
(`docs/revamp/00-DISCOVERY.md:328` lists exactly-one-submit as a
must-keep contract). Compounding it: the SSE path uses native
`EventSource` (`web/lib/useResearchStream.ts:121`), which cannot set
headers, so the session credential **must** be cookie-borne. A
header-token design is not available. Mitigation is therefore an
explicit `Origin`/`Sec-Fetch-Site` check on mutating methods in the
proxy plus `SameSite`, and it is not optional.

**T3 — key custody.** F3. Under A the keystore becomes a user
credential database in cleartext, readable by anything that can read
the mounted file. Under C the keystore stays small, or disappears
entirely under C2. Whatever holds per-user secrets needs an at-rest
story that `src/api/auth.py:332-389` does not currently have.

**T4 — rate-limit fairness and aggregate cost.** Two separate things
that MT-01 conflates if you are not careful. *Fairness* improves: the
limiter already buckets per principal (`src/api/auth.py:538`), so
per-user principals automatically fix the shared-budget complaint in
`docs/revamp/00-DISCOVERY.md:348`. *Aggregate exposure* gets worse in
direct proportion (F4). A per-user budget without a deployment budget
is a strictly worse position than today. This is why Phase 0 precedes
everything.

**T5 — account enumeration.** ADR 0036 closed resource enumeration with
the 404-not-403 rule (`src/api/routes.py:82-84`). Login, provisioning,
and any "user exists" response reopen it at a different layer. Under C
the IdP absorbs most of it, which is another point in C's favour.

**T6 — identity-header spoofing.** C-specific and load-bearing. The
resolver must be off by default, gated by an explicit setting, and must
never be enabled by inference. The production overlay's no-published-
ports topology (`deploy/hetzner/compose.prod.yml:12,24`) is the trust
anchor and base compose does not have it (`docker-compose.yml:44,126`).
`docs/decisions/0039-admin-null-owner-migration.md:70-76` is the
cautionary precedent: availability decided by the wrong signal produced
a path where a destructive command would have succeeded against the
wrong data.

**T7 — revocation latency.** Under A, locking out a compromised account
takes up to `api_keys_reload_interval_sec` (default 30,
`src/config.py:230-238`) after the file is written. Under C it is the
IdP session plus the edge cookie TTL, which is typically longer unless
sign-out is propagated. Whichever option wins, **the number must be
measured and written into `docs/security.md`**, not assumed.

**T8 — admin surface.** `admin_migrate` deliberately bypasses the
API's ownership checks
(`docs/decisions/0039-admin-null-owner-migration.md:122-124`) and is
only as safe as the operator running it. With one principal that is a
data-repair tool. With real users it is a cross-user data tool, and its
per-row delete logging
(`docs/decisions/0039-admin-null-owner-migration.md:77-82`) becomes the
only audit trail that a user's data was touched. There is still no role
model on `ApiKeyPrincipal` (Q5).

**Not changed by MT-01**, and worth stating so the scope stays honest:
prompt injection (ADR 0020/0033), transport hardening, PDF bounds, and
XXE (`docs/security.md:90-108`) are all orthogonal. Also unchanged and
still open: the request body is fully buffered before auth runs
(`docs/security.md:458-459`) and again in the proxy
(`web/app/api/[...path]/route.ts:84-85`); Caddy's 1 MB cap
(`deploy/hetzner/Caddyfile:14-16`) is the only bound, and it is at the
layer MT-01 proposes to modify — so do not lose it.

---

## 7. Data migration

### 7.1 What exists and who owns it today

| Data | Store | Owner column today | Under MT-01 |
|---|---|---|---|
| Conversations + `conversation_jobs` | Postgres (`src/tools/postgres_pool.py:71-106`) | `principal_key_id` = `web` in prod (`deploy/hetzner/compose.prod.yml:15`), or NULL from any auth-off history | Reassign, archive, or delete (Q4) |
| Jobs (status, result, plan) | Redis, TTL-bounded (ADR 0027) | Same field (`src/api/jobs.py:90`) | Same decision; much of it expires on its own |
| `paper_cache` | Postgres (`src/tools/postgres_pool.py:35-52`) | **None — no owner column** | Stays shared (§7.3) |
| `embedding_cache` | Postgres (`src/tools/postgres_pool.py:55-64`) | **None** | Stays shared (§7.3) |
| LangGraph checkpoints | Postgres, keyed by `thread_id = run_id` (`src/api/runner.py:299`) | **None** | Reachable only via an owned job |
| Rate-limit counters | Redis `ratelimit:{key_id}`, self-expiring (`src/api/auth.py:274-278`) | Keyed by principal | New buckets appear; old one drains |

### 7.2 The migration itself

The important correction to the obvious plan: **production rows are not
NULL-owner, they are `web`-owned.** ADR 0039's tool scans for NULL
specifically (`scan_null_owner_jobs`,
`docs/decisions/0039-admin-null-owner-migration.md:42-48`), so
`admin_migrate` as it stands will report zero rows and do nothing on the
data that actually matters. Both populations must be handled:

- **`web`-owned rows** — everything created since auth was turned on.
  Needs a new predicate (`--from-owner web`) alongside the existing
  NULL scan.
- **NULL-owner rows** — anything created while `enable_api_auth=false`
  (`docker-compose.yml:94`), already invisible under auth-on
  (`src/api/routes.py:78-84`) and already handled by ADR 0039.

Three end states for the operator to choose from (Q4):

1. **Reassign** all `web`-owned rows to a designated first user. Correct
   when the deployment has had exactly one real human. Cheapest, and
   wrong the moment that assumption is wrong — and per F1 and ADR
   0036's original reasoning
   (`docs/decisions/0036-per-principal-store-scoping.md:88-93`),
   assigning a wrong owner converts an access problem into a
   cross-tenant disclosure.
2. **Archive**: leave `web` as a principal nobody's session maps to. The
   data becomes unreachable through the API but survives for an
   operator to inspect or reassign later. This is the safe default and
   costs only storage.
3. **Delete**, with `--older-than-days` bounding the blast radius.

Whichever is chosen, the ADR 0039 safety properties are non-negotiable
and must be preserved by the new predicate: dry-run by default,
`--yes` to write, `report` never writes, Redis TTL preserved on rewrite
(`docs/decisions/0039-admin-null-owner-migration.md:64-66`), one
structured log record per destroyed row (`:77-82`), availability
decided by the *selected* store rather than a configured URL
(`:68-75`), and `--limit` bounding per store (`:126-128`).

Note that jobs and conversations diverge over time: Redis job rows
expire under ADR 0027 retention while Postgres conversations are
durable. A user's visible history is therefore already asymmetric —
old threads survive with their reports, old job rows do not — and any
user-facing promise about "your history" must say so.

### 7.3 Data that will never have an owner

`paper_cache` and `embedding_cache` (`src/tools/postgres_pool.py:35-64`)
are content-addressed caches of **public arXiv papers**. They carry no
owner column and this proposal recommends keeping it that way: sharing
them across tenants is the cache's entire value, and the content is
public. LangGraph checkpoints (`src/api/runner.py:299`) are keyed by
`run_id` with no owner, reachable only through an owned job.

The consequence must be stated plainly rather than papered over: **a
"delete my data" action can honestly cover jobs, conversations, and
reports, but not the derived caches of the public papers a user
happened to read first.** If a stronger deletion promise is required
(Q7), that is separate work — and note that `docs/security.md:471-474`
already lists a cache purge command as an open follow-up with no
per-user dimension.

### 7.4 Schema mechanics

There is no migration framework, and ADR 0039 rejected introducing one
for a data fix
(`docs/decisions/0039-admin-null-owner-migration.md:105-108`). Schema
changes follow the existing idempotent pattern —
`ADD COLUMN IF NOT EXISTS` alongside the `CREATE`
(`src/tools/postgres_pool.py:83-91`). Adding a nullable column fits.
**Renaming `principal_key_id` to `owner_id` does not**: it is a
two-phase dual-write migration and should be treated as its own
decision, not smuggled into MT-01.

---

## 8. Open questions for the human decision

Q1 and Q3 are blocking — the recommendation is not safe to act on
without them.

1. **Who are the users?** Invite-only colleagues (≤10)? Anyone with a
   Google/GitHub account on an allowlist? Something broader? This
   single answer moves the recommendation more than anything else in
   this document: a tiny trusted set makes C's recurring cost and
   external dependency look expensive relative to the risk it removes,
   while anyone outside the operator's direct control makes C stronger.
   **Blocking.**
2. **Is an external identity provider acceptable at all?** If yes,
   which, and what is its recurring cost and its availability
   implication for login? If no, §4.2's fallback is Option B, not
   Option A — confirm that reading.
3. **What is the deployment-wide spend ceiling, over what window, and
   what happens at the cap?** Refuse new submits, or degrade? Who is
   told? Phase 0 cannot start without a number. **Blocking.**
4. **What happens to existing data?** Reassign to a first user,
   archive under the `web` principal, or delete (§7.2)? The safe
   default is archive; the cheap default is reassign; the honest
   question is whether the deployment has ever had more than one human
   using it.
5. **Is an admin role in scope now?** It has been deferred three times
   (`docs/decisions/0036-per-principal-store-scoping.md:84-87`,
   `docs/decisions/0039-admin-null-owner-migration.md:139-141`,
   `docs/security.md:449-452`). MT-01 either decides it or explicitly
   keeps `admin_migrate` shell access as the only admin surface (T8).
6. **Does the CX23/4 GB target absorb an extra container, or does
   MT-01 force a resize?** The discovery already flags the memory
   budget as unresolved (`docs/revamp/00-DISCOVERY.md:308`). A resize
   is a recurring bill needing its own approval at Gate MT-C.
7. **What deletion promise are we willing to make?** §7.3 means "delete
   my data" cannot cover the shared public-paper caches without
   separate work. Is the narrower promise acceptable?
8. **Sequencing against the frontend revamp.** Does MT-01 wait for the
   revamp to ship, run in parallel behind flags, or take priority? §5.7
   assumes parallel-behind-flags; that assumption should be confirmed
   rather than inherited.
9. **Machine clients.** After cutover, does `X-API-Key` remain a valid
   way to reach the API from outside the browser (eval runner, CLI,
   scripts), and if so how are those keys distinguished from user
   principals in the ownership model?

---

## 9. Evidence index

Primary sources for every claim above, for a reviewer who wants to
check the work:

- **Single-key injection**: `web/app/api/[...path]/route.ts:81-82`;
  wiring at `docker-compose.yml:125` and
  `deploy/hetzner/compose.prod.yml:15,27`.
- **Ownership machinery**: `src/api/routes.py:59-93,173-177,184,550,586-590,645-648`;
  `src/api/conversations.py:82,362-364,540-542`;
  `src/api/jobs.py:90`; `src/tools/postgres_pool.py:71-91`.
- **Auth and keystore**: `src/api/auth.py:94-98,127-133,332-389,392-477,480-518,538`;
  `src/config.py:174-245,598-607`.
- **Edge**: `deploy/hetzner/Caddyfile:8-16,29`;
  `deploy/hetzner/compose.prod.yml:12,24`; `docker-compose.yml:44,94,126`.
- **Prior art and precedent**: ADR
  [0033](../decisions/0033-safety-hardening-bundle.md),
  [0036](../decisions/0036-per-principal-store-scoping.md),
  [0037](../decisions/0037-redis-rate-limiter-and-keystore-reload.md),
  [0039](../decisions/0039-admin-null-owner-migration.md),
  [0042](../decisions/0042-api-guardrails-and-deploy-hygiene.md),
  [0043](../decisions/0043-conversation-store-hardening.md),
  [0054](../decisions/0054-hetzner-production-boundary.md);
  threat model in [`docs/security.md`](../security.md); storage matrix
  in [`docs/architecture.md`](../architecture.md#storage-matrix).
- **Revamp context**: [`docs/revamp/DECISIONS.md`](../revamp/DECISIONS.md)
  D-002 and [D-009](../revamp/DECISIONS.md#d-009--gate-1-human-decisions);
  [`docs/revamp/00-DISCOVERY.md`](../revamp/00-DISCOVERY.md) lines
  308, 328, 348, 367.
