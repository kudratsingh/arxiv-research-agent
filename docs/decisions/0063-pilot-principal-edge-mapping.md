# 0063. Map an edge-authenticated pilot username to a per-principal key at seam S1

- **Status**: accepted — **to be superseded by MT-01** when end-user
  multi-tenancy lands ([`docs/proposals/multi-tenancy.md`](../proposals/multi-tenancy.md),
  §5.4 Phase 2 / L0-03). MT-01 **replaces** this; nothing here is a foundation
  for it to build on, and the supersession note exists so that this does not
  become load-bearing identity infrastructure by accretion.
- **Date**: 2026-09-02
- **Deciders**: kudratsingh
- **Follows**: [ADR 0033](0033-safety-hardening-bundle.md) (API-key auth),
  [ADR 0036](0036-per-principal-store-scoping.md) (per-principal scoping),
  [ADR 0037](0037-redis-rate-limiter-and-keystore-reload.md) (hot-reloadable
  keystore, per-principal rate limit),
  [ADR 0039](0039-admin-null-owner-migration.md) (availability decided by the
  wrong signal — the cautionary precedent),
  [ADR 0054](0054-hetzner-production-boundary.md) (the edge, and the
  deployment gate that is not an identity),
  [ADR 0058](0058-learner-profile-store-and-provenance.md) (the first personal
  data, keyed on `principal_key_id`)
- **Implements**: WO-W17 in
  [`planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md`](../../planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md#wo-w17--pilot-principals-and-onboarding),
  under scope ruling **SR-08**, inside **SR-09**'s spend bound and **SR-02**'s
  never-reassign rule

## Context

Phase W's Rung 2 test needs five invited humans using the guided-reading
surface for fourteen days, each with their own threads, sessions, profile and
progress ledger. The backend half of that already exists and is real: every
`Job`, `Conversation`, `LearnerProfile` and progress event carries a
`principal_key_id`, `_check_ownership` answers 404 rather than 403 on somebody
else's row, and the keystore is hot-reloadable (ADRs 0036, 0037, 0058).

The web tier is where it stops. `resolveUpstreamPrincipal`
(`web/lib/server/principal.ts`) returns one `"shared"` principal for every
request, because until now the deployment genuinely had one. The production
edge asks for HTTP basic auth, but `docs/security.md` is explicit that this is
a **deployment gate, not a user account** (MT-01 seam S7): one credential
shared by everyone who has it, never seen by anything downstream.

So the wedge needs exactly one thing the repository does not have: the web
tier resolving *which* key per request. Everything else is built.

Three constraints shape the answer, and each of them rules out the obvious
version of it.

**D-009 and the revamp's rule.** The frontend "must not fake login or per-user
views". A session system, a login page, or a cookie would be the revamp
building identity, which its own decision log forbids. Whatever is built must
not be, and must not look like, a login.

**MT-01 threat T6, in its own words.** Forwarding an identity header moves the
whole trust model onto *"the identity header is trustworthy"*, which holds
only if nothing but the edge can reach the web tier. That is true of the
production overlay, whose `web` publishes no host port, and **false** of base
compose, which publishes it to loopback. The proposal's mitigation is stated
as a requirement: the resolver "must be off by default, must require an
explicit opt-in setting, and must never be inferable". ADR 0039 is why — it
recorded a path where availability was decided by the wrong signal and a
destructive command would have run against the wrong data.

**SR-09 and MT-01 F4.** There is no aggregate spend cap and Phase W does not
build one. The pilot is acceptable only because the cohort is five named
people and the bound is written down. Anything that makes the cohort growable
without a decision breaks that argument.

The thing being built is therefore deliberately small: a hand-run slice of
what MT-01 L0-03 does properly, at the seam MT-01 already declared, with the
supersession written into this document rather than left to be remembered.

## Decision

**`resolveUpstreamPrincipal` gains one mode, default off, that maps an
edge-authenticated username to that pilot's already-issued per-principal API
key from a server-side environment map.**

The mechanism, end to end:

1. **The edge authenticates.** `deploy/pilot/Caddyfile` carries one
   `basic_auth` credential per pilot, from a bcrypt file that is never
   committed. It forwards the authenticated username as `X-Pilot-User` via
   `header_up`, which is a *set* and therefore overwrites whatever the client
   sent, and the shared `PILOT_EDGE_SECRET` as `X-Pilot-Edge-Key`.
2. **The web tier maps, and mints nothing.** `web/lib/server/pilot.ts` parses
   `PILOT_PRINCIPAL_MAP` — one JSON document, `{"<username>": {"key_id",
   "api_key"}}`, at most five entries — and hands the matched entry to the
   seam. No key is created, derived or stored by any code in this repository;
   the operator writes both halves by hand per `docs/runbooks/pilot.md`.
3. **The proxy is still the sole credential boundary.**
   `web/app/api/[...path]/route.ts` injects the resolved secret as `X-API-Key`
   on the private hop, exactly as it injected the shared one.
4. **The backend is untouched.** Pilot keys live in `api_keys_file`, polled by
   `KeystoreReloader`; issuance is an edit, revocation is a deletion, and the
   latency is `api_keys_reload_interval_sec`. No Python changed for this ADR.

Four guards, each of which refuses rather than degrades:

- **Off unless the literal `on`.** Unset, empty and `off` are off. *Any other
  value refuses to serve*, so an operator who typed `PILOT_EDGE_AUTH=true` is
  told, rather than silently getting the shared principal.
- **Topology is asserted, never assumed.** The resolver refuses the username
  header unless `X-Pilot-Edge-Key` matches `PILOT_EDGE_SECRET`, compared over
  SHA-256 digests with `timingSafeEqual` (the presented value's length is
  attacker-controlled, so the raw strings are never handed to a function that
  throws on a length mismatch).
- **Ambiguity is a refusal.** Mode on **and** `ARXIV_API_KEY` non-empty is
  `shared_key_also_set`: two configured answers to "whose credential is this"
  is an unanswered question, and the deployment 503s rather than picking one.
  Duplicate `api_key` or `key_id` in the map, and a sixth entry (SR-09's
  cohort ceiling), are refused the same way.
- **Refusal leaves the return type.** Every failure throws
  `PrincipalUnresolvedError` instead of returning `null`. `null` already means
  something specific and safe — "send no `X-API-Key` at all", the auth-off
  demo — and a caller that conflated the two would silently downgrade a
  pilot's authenticated request to an anonymous one. The route catches it and
  answers 503 `pilot_principal_unresolved`, identical for every fault so that
  a response never says whether a username exists.

One structured log line per resolution,
`{"event":"pilot_principal","outcome":…,"user":…,"key_id":…}`. The record type
has no field that can hold a secret — the same structural argument
`lib/server/proxyLog.ts` makes — and the username is logged only *after* the
topology guard has passed, so an attacker cannot write bytes into the log by
sending a header.

**With the mode off, nothing changes.** `readPilotConfig` returns after
reading one environment variable and the three lines after it are the three
lines that were there before: same reads, same order, same values, and no
output of any kind. `web/tests/principal.test.ts` and
`web/tests/apiProxyRoute.test.ts` both pass unmodified, which is the evidence
for that claim rather than a restatement of it.

## Alternatives considered

- **Map in FastAPI instead (MT-01 option C2).** `require_principal` grows a
  trusted-header resolver and the proxy forwards the header instead of a key.
  Rejected: it moves trust onto a header at the layer that *enforces*
  ownership, widens the blast radius to `src/api/auth.py` and every route, and
  Phase W's own rule is that no MT-01 work is performed. The web tier is where
  the seam was declared, and it is the layer MT-01 replaces wholesale.
- **A real session at the web tier (MT-01 option A).** Rejected outright by
  D-009: the revamp must not fake login. It also drags in CSRF as a live
  requirement the moment a cookie exists (MT-01 **T2**), which is a hard
  requirement this card is not scoped to meet.
- **Trust the topology, with no shared secret.** The production overlay
  publishes no port for `web`, so "only the edge can reach it" is true there.
  Rejected: it is *false* in base compose and in the e2e tier, and a resolver
  that is safe in production and unsafe locally is exactly ADR 0039's failure
  shape. MT-01 T6 asks for an explicit assertion; a network layout is not one.
- **mTLS between edge and web.** Strongest, and honestly the right answer for
  a system that had a certificate lifecycle. Rejected: this deployment has no
  internal PKI, no rotation story, and no way to test the failure modes; the
  guard would be stronger and the operational surface would be larger than the
  thing it protects.
- **A signed token (JWT or similar) from the edge.** Rejected as more magic
  for no more security here: it needs a key lifecycle to protect a key
  lifecycle, and the shared secret is already an explicit assertion that
  rotates with one `openssl rand -hex 32`.
- **Reuse `deploy/hetzner/compose.prod.yml` and add pilots to it.** Rejected:
  that overlay requires `WEB_API_KEY` at interpolation time, and a pilot
  deployment must not possess a shared web key. Compose interpolates every
  file before merging any of them, so the two are alternatives rather than
  layers, and `deploy/pilot/README.md` says which to use when.
- **Exempt `/healthz` from the mapping so the container healthcheck keeps
  working.** Rejected: a path exemption inside the credential resolver is the
  seed of every "we only skip auth for one endpoint" incident. The probe
  changed instead — see Consequences.

## Consequences

- **Positive.** The pilot becomes possible without a session, a login page, a
  cookie, a credential database, or any backend change. The seam MT-01
  declared is the only edit site, exactly as 04 §10 predicted, so MT-01
  deletes one file and rewrites one function rather than unpicking a design.
  Keys never reach a browser: the map is a server-side environment variable
  read only under `lib/server/`, no client-reachable module may import it, and
  the built bundle is scanned for the material.
- **Positive.** Several rules that were prose become arithmetic. SR-09's ≤5
  cohort is `PILOT_MAX_PRINCIPALS`; SR-02's "one key per person" is refused
  duplicates; "never the shared key" is a refusal rather than a branch order.
- **Negative — the S7 sentence stops being true, and the copy has not caught
  up.** `docs/security.md` says the edge login "is **not** a principal … two
  people with the same password are indistinguishable at every layer below
  Caddy", and the shell renders "Shared workspace — Everyone with access to
  this deployment sees these threads. There are no separate accounts."
  (`web/lib/copy/threads.ts`). Under `PILOT_EDGE_AUTH=on` both statements are
  **false**: the login selects a principal and threads are per person. WO-W17
  does not own `web/lib/copy/**` (WO-W14 does this wave), so the string is
  unchanged and the discrepancy is written down here, in `docs/security.md`,
  and in the runbook's onboarding note, which tells pilots plainly to ignore
  it. **This must be resolved before a pilot is invited** — it is a false
  statement about data separation shown to the people the separation is for.
- **Negative — the container healthcheck loses WO-30 / C5's property.**
  `scripts/healthcheck.mjs` probes `/api/healthz` through the proxy, which is
  the point of C5; under pilot mode the probe is not a pilot and is correctly
  refused. The overlay points it at Next's own root instead, so a healthy
  `web` container proves liveness and no longer proves it reached FastAPI. The
  `app` container's own healthcheck still proves FastAPI is serving, and the
  runbook's per-pilot smoke test is an authenticated request through the whole
  chain.
- **Negative — three files must agree, by hand.** The edge user file, the
  keystore, and the map. A mismatch between the map's `key_id` and the
  keystore's name is a pilot who authenticates and then gets 401. §7 of the
  runbook is the table that turns each mismatch back into a cause.
- **Negative — none of MT-01's findings are fixed.** F1 (mutable owner id) is
  handled by a human rule; F3 (cleartext keystore) is unchanged; F4 (no
  aggregate cap) is unchanged and is why SR-09's arithmetic exists; T7
  (revocation latency) is `api_keys_reload_interval_sec`. All four are listed
  again in the runbook so an operator meets them at the moment they matter.
- **Follow-ups.** MT-01 / L0-03 supersedes this whole ADR. Before that: the
  copy discrepancy above; the aggregate spend cap (L0-01, SR-09's re-trigger);
  and a role model, without which "withhold `POST /research` rights" is a
  configuration choice about `max_cost_usd` rather than a permission.
