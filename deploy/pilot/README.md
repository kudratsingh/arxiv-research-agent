# The pilot deployment overlay

The mechanism half of WO-W17: per-pilot HTTP `basic_auth` at the edge, the
authenticated username forwarded to the web tier, and the web tier mapping
that username to the pilot's already-issued per-principal API key. It is
scope ruling **SR-08**'s "thin, guarded slice at the declared seam", decided
in [ADR 0063](../../docs/decisions/0063-pilot-principal-edge-mapping.md).

> **Nothing here is approved to run.** Owner decision **W-OD-5** — the ≤5
> invitee names, the deployment, the pilot inference budget, the at-cap
> behaviour, and whether pilot keys keep `POST /research` rights — is open.
> This directory is a mechanism, not permission. The procedure that uses it
> is [`docs/runbooks/pilot.md`](../../docs/runbooks/pilot.md); read that
> before anything here.

## Which overlay do I want?

| | `deploy/hetzner/compose.prod.yml` | `deploy/pilot/compose.pilot.yml` |
|---|---|---|
| Edge login | one shared credential | one per pilot |
| What the login is | a **deployment gate** (`docs/security.md`, S7) | a **principal selector** |
| Web tier credential | `ARXIV_API_KEY`, one shared key | a server-side username→key map; `ARXIV_API_KEY` must be empty |
| Backend keystore | `API_KEYS` string, restart to change | `api_keys_file`, hot-reloaded |
| Rows are | shared by everyone | per person (ADR 0036) |

They are **alternatives, not layers.** Both define an edge service and both
harden the same three services; the hetzner overlay additionally requires
`WEB_API_KEY` at interpolation time, which a pilot deployment must not
possess. Compose interpolates every file it loads before merging any of them,
so stacking the two demands a credential whose absence is the point.

`deploy/hetzner/README.md`'s provisioning contract still governs the host —
same server class, same Cloud Firewall, same "only the edge publishes a port"
rule.

## Bring it up

```bash
cp deploy/pilot/env.example .env      # then fill it in per the runbook
docker compose -f docker-compose.yml \
  -f deploy/pilot/compose.pilot.yml up --build -d
```

Two files this repository does not contain and must never contain
(`.gitignore` excludes both):

- `deploy/pilot/pilot-users.caddy` — one `username bcrypt-hash` line per
  pilot, read by the edge.
- `deploy/pilot/pilot-keys.json` — `{"<key_id>": "<secret>"}`, read by
  FastAPI's hot-reloading keystore.

Generating them, and the rule that a key is **never reassigned**, are in
[`docs/runbooks/pilot.md`](../../docs/runbooks/pilot.md).

## How a pilot request travels

```text
browser --basic_auth--> edge (Caddy) --X-Pilot-User + X-Pilot-Edge-Key-->
  web (Next.js) --X-API-Key--> app (FastAPI) --principal_key_id--> rows
```

1. The edge authenticates the browser against `pilot-users.caddy` and sets
   `X-Pilot-User` to the username it authenticated. `header_up` is a *set*,
   so anything the client sent under that name is overwritten.
2. The edge also sets `X-Pilot-Edge-Key` to `PILOT_EDGE_SECRET`. This is the
   whole topology guard — see below.
3. `web/lib/server/pilot.ts` compares the edge key in constant time, refuses
   the username header outright if it does not match, and otherwise looks the
   username up in `PILOT_PRINCIPAL_MAP`.
4. `web/app/api/[...path]/route.ts` injects that pilot's secret as
   `X-API-Key` on the private hop, exactly as it injects the shared key today.
   The proxy remains the sole credential boundary.
5. FastAPI resolves the key to a `key_id` and ADR 0036 scopes every row to it.

## The threat model, and the guard for each item

| Threat | Guard | Where |
|---|---|---|
| A browser forges `X-Pilot-User` | The edge **sets** the header, overwriting the client's | `Caddyfile`, `header_up` |
| Something on the network posts straight at `web:3000` with a forged username | The request carries no `X-Pilot-Edge-Key`, so the resolver refuses it | `web/lib/server/pilot.ts`, guard 2 |
| The mode is on somewhere it should not be | It is off unless `PILOT_EDGE_AUTH` is the literal `on`; any other value refuses to serve | `readPilotConfig` |
| An unknown username silently gets the shared key | Mode-on and `ARXIV_API_KEY` both configured is a refusal; an unknown username is a 503 | `shared_key_also_set`, `unknown_username` |
| Two pilots share a key or a `key_id` | The map refuses duplicates of either | `map_duplicate_api_key`, `map_duplicate_key_id` |
| A sixth pilot doubles the spend the Gate W2 report was written against | The map refuses more than five entries (SR-09) | `PILOT_MAX_PRINCIPALS` |
| A key reaches a browser | The map is a server-side environment variable read in `lib/server/`; no client module may import it, and the built bundle is scanned | `web/tests/pilotPrincipal.test.ts` |
| A key reaches a log | The log record type has no field that can hold one; the username is logged only after the topology guard passes | `PilotLogRecord` |

### Why a shared header secret, and not something cleverer

The alternatives were considered and are recorded in ADR 0063 §Alternatives.
The short version: mTLS between edge and web is the strongest and needs a
certificate lifecycle this deployment has no story for; trusting the network
topology alone is what MT-01's threat **T6** and ADR 0039 both warn against
("availability decided by the wrong signal"), and it is *false* in base
compose, which publishes `web` to loopback; and a signed token needs a key
lifecycle to protect the key lifecycle. A shared secret in a header is the
least magic thing that is an explicit assertion rather than an assumption,
and it is one `openssl rand -hex 32` to rotate.

### What this does not defend

- **CSRF.** Unchanged from `docs/security.md`: the proxy still performs no
  origin check. Basic auth is not ambient the way a session cookie is, so the
  exposure is the same as today's — but this is the closest the repository has
  come to per-user authority, and MT-01 owns the fix.
- **Key custody at rest.** MT-01 finding **F3**: `pilot-keys.json` is
  cleartext, readable by anything that can read the mounted file.
- **Aggregate spend.** MT-01 finding **F4**: there is no global cap. SR-09's
  arithmetic is what bounds the pilot, and it is bounded by construction
  rather than by a control. The table is in the runbook.
- **A stable owner id.** MT-01 finding **F1**: `principal_key_id` is a mutable
  display name. Phase W handles it operationally — pilot keys are issued fresh
  per person and **never reassigned** (SR-02) — and that rule is the runbook's,
  enforced by a human.

## The healthcheck changes, deliberately

`scripts/healthcheck.mjs` probes `/api/healthz` *through the proxy*, which is
WO-30 / C5's whole point: a healthy `web` container proves it reached FastAPI.
Under pilot mode that probe is not a pilot, carries no edge key, and is
correctly refused with 503 — so the overlay points the probe at Next's own
root instead and the container reports liveness only.

What covers the gap: the `app` service's own healthcheck still proves FastAPI
is serving, the edge's healthcheck proves Caddy is, and the runbook's
onboarding smoke test is one authenticated request through the entire chain,
performed per pilot at issuance.
