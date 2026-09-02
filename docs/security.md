# Security

## Threat model

The workflow ingests arXiv PDFs. That's untrusted content: anyone
can publish a paper, and the reader passes paper text directly into
a Claude call whose output the workflow acts on. Sprint 2 landed a
supervisor loop that reads reader-emitted control tokens, which
made prompt injection a **workflow-control** risk on top of the
existing "the report is wrong" risk.

Attackers we defend against:

- A malicious arXiv paper with a jailbreak in its abstract or full
  text, aiming to redirect the supervisor's next action, stop the
  loop early, or smuggle instructions into the report via evidence
  claims.
- An in-flight MITM sitting between the workflow and arXiv, trying
  to inject attacker-chosen `PaperMetadata` that then drives Claude
  prompts and PDF fetches.
- An adversarial PDF host serving multi-hundred-MB content in
  response to `parse_pdf`, aiming to exhaust worker memory.
- An anonymous HTTP caller trying to drain the Anthropic account by
  hitting `POST /research` at scale.
- A conversation follow-up where a prior report — itself derived
  from adversarial-controllable paper text — carries a jailbreak
  that redirects the planner on the next turn.

Not in scope:

- Content-safety filtering (offensive text in abstracts).
- Injection via user-supplied query strings (short, controlled).
- Compromised Claude / Anthropic infrastructure.
- Compromised arXiv delivery infrastructure (the workflow does not
  cryptographically verify PDFs).

## Defenses

### Reader prompt-injection isolation (ADR 0020)

Behind `settings.enable_prompt_isolation` (default off; **flip on
whenever `enable_supervisor` is on**). Three layers:

1. **Delimiter isolation**. Paper-derived text (abstract + ranked
   chunks) is wrapped in `<untrusted_paper_text>...</untrusted_paper_text>`
   tags in the reader's user prompt. Close tags in the content are
   escaped so a paper can't terminate the wrapper.
2. **Explicit system-prompt instruction**. `ISOLATION_SYSTEM_INSTRUCTION`
   is prepended to the reader's system prompt when the flag is on.
   It names the delimiter tags and the exact control fields it's
   protecting (`analysis_complete`, `request_more_sections`,
   `missing_context`).
3. **Output sanitization on control fields**.
   `sanitize_control_string(missing_context)` trims / caps at 300
   chars / blanks on jailbreak markers.
   `sanitize_section_names(request_more_sections)` drops entries
   longer than 50 chars, entries with disallowed characters, and
   entries with jailbreak markers. `_parse_claim` runs the same
   filter on `EvidenceClaim.claim` and drops the claim on match.

Source: `src/security/prompt_isolation.py`. Wired at
`src/agents/reader.py::_analyze_paper` and
`src/agents/reader.py::_parse_recovery_signal` /
`src/agents/reader.py::_parse_claim`.

**Not sanitized**: `EvidenceClaim.source_text` (the verifier judges
against it; must be verbatim), `key_findings` / `methodology` /
`results_summary` / `limitations` (flow to synthesizer, not to
supervisor control tokens). These are follow-up work.

### Planner prior_context isolation (ADR 0033)

Behind the same `settings.enable_prompt_isolation` flag. When
conversation mode (ADR 0032) retrieves prior-report chunks into
`state.prior_context`, the planner:

1. Wraps the text with
   `<untrusted_prior_context>...</untrusted_prior_context>` tags via
   `wrap_untrusted_prior_context()`. Close tags in the content are
   escaped.
2. Prepends `PRIOR_CONTEXT_ISOLATION_INSTRUCTION` to the system
   prompt. It names the tag pair and the exact control fields it's
   protecting (`sub_questions`, `search_queries`).

Wired at `src/agents/planner.py::_build_user_prompt` and
`src/agents/planner.py::_build_system_prompt`. Same defense pattern
as the reader; distinct tags so the guardrail can name the fields
precisely.

### Learner profile isolation + provenance (ADR 0058)

The `learner_profiles` table is the first data this repo holds about a
**person** rather than a paper, and it carries free text the learner
authored (`profile_note`, goal statements) that reaches a prompt every
session. Same defense pattern as the two above, third tag pair:

1. `wrap_untrusted_learner_text()` wraps that text in
   `<untrusted_learner_text>...</untrusted_learner_text>`, escaping any
   close tag inside it.
2. `LEARNER_TEXT_ISOLATION_INSTRUCTION` names the tag pair and the
   thing it is protecting — the response schema, a claim's provenance,
   and the line between an unconfirmed impression and a stated fact.
3. Both behind `settings.enable_prompt_isolation`, like the reader and
   the planner.

Two properties do **not** depend on that flag, deliberately:

- **No control token is learner-writable.** Skill names, levels,
  sources, and evidence refs are validated to a slug shape at the
  store boundary (`src/learning/profile_store.py`), so a colon, a
  newline, or a tag never enters one. ADR 0020's supervisor lesson
  applied where the value is written rather than where it is rendered.
- **No prompt presents an inferred skill as fact.**
  `render_profile_for_prompt` marks every claim with its provenance,
  confines inferred claims to an "unconfirmed impressions" block, and
  re-reads its own output — a misplaced marker raises rather than
  reaching a model. Provenance itself is non-nullable in the type and
  in the table's `CHECK` constraints, so an unlabelled claim cannot be
  stored by any path, `psql` included.

Deletion is a first-class operation (`DELETE /learn/profile`) covering
the whole row. Its stated exception: the shared paper and embedding
caches hold public arXiv text, are not per-user, and are untouched.

### Transport hardening (ADR 0033)

- `ARXIV_API_URL` is `https://export.arxiv.org/api/query`. An
  in-flight MITM cannot substitute paper metadata.
- Response parsing uses `defusedxml.ElementTree`, which raises
  `EntitiesForbidden` on any DOCTYPE + entity payload — no XXE,
  no billion-laughs.

### PDF fetch guardrails (ADR 0033)

- `_download_pdf` streams with `iter_content` and aborts once
  `settings.pdf_max_bytes` (default 50 MiB) is reached. Servers
  that declare `Content-Length` above the cap are refused before
  any bytes flow.
- `_cache_key` only extracts an arXiv ID when
  `urlparse(pdf_url).hostname` is under `arxiv.org`; other hosts
  fall through to a SHA hash of the full URL, so a URL like
  `https://evil.com/2311.09000/attack.pdf` cannot poison the cache
  slot for the real arXiv paper.

### Per-run cost cap (ADR 0033, moved to `call_llm` by ADR 0051)

`src/llm.py::call_llm` checks the run's accumulated spend against its
effective ceiling **before every LLM call** and raises
`CostBudgetExceeded` at the ceiling (`enforce_cost_cap` lives in
`src/observability/costs.py`). Because every entry point — CLI, eval
campaign, API job — funnels through `call_llm`, the dollar ceiling
now binds on the sync paths that previously had none, and a single
node's parallel fan-out (the reader) cannot overshoot by its whole
spend. The API runner's between-nodes check (the original ADR 0033
enforcement point) remains as the earlier, coarser stop. Under the
API the job terminates as `failed` with
`error_type=cost_budget_exceeded`; on the CLI the run aborts and the
checkpoint salvage (ADR 0052) recovers any finished draft.

ADR 0062 binds `learning_session_max_cost_usd` for session jobs only;
all other paths retain `max_cost_usd`. The binding is task-local,
propagates through the session graph's worker context, and is reset in
the runner's terminal cleanup so concurrent or subsequent research
jobs cannot inherit it. At-cap sessions expose an explicit refused or
degraded-close outcome and never issue another model call for closing
copy.

### API-key auth + rate limiting + CORS (ADR 0033)

Behind `settings.enable_api_auth` (default off; **flip on for any
exposed deployment**). Three layers:

1. **API-key authentication**. Every `/research` and `/conversations`
   route carries `dependencies=[Depends(require_principal)]`. The
   dependency reads the `X-API-Key` header, looks it up in the
   startup-parsed keystore (`settings.api_keys`, format
   `name:secret,name:secret`), and returns an `ApiKeyPrincipal`.
   Missing or unknown key -> 401. Lookup uses `hmac.compare_digest`
   in a non-short-circuiting loop for constant-time comparison —
   over **bytes**, not str (ADR 0042): Starlette decodes headers as
   latin-1, and `compare_digest` on str raises TypeError for any
   non-ASCII character, which used to turn a one-byte probe into an
   unauthenticated 500 with a traceback. `/healthz` and `/docs`
   stay open.

   **A `key_id` (the name half of a keystore entry) is a permanent
   identifier.** It is what ADR 0036 stamps onto every job and
   conversation as the owner. Renaming a key orphans that
   principal's rows (404 on everything); reusing a retired name
   hands the new holder the previous tenant's data. Both parsers
   reject duplicate names for this reason (ADR 0042) — rotate the
   *secret* under a stable name, never the name.
2. **Per-key rate limit**. The rate limiter records submit
   timestamps per principal in a sliding window (in-memory per
   worker, or a shared Redis ZSET — see ADR 0037 below). When a key
   exceeds `settings.api_key_hourly_limit` submits per hour, the
   route returns 429 with a `Retry-After` header. Two routes draw
   from that budget: `POST /research` and `POST /conversations` —
   the latter added by ADR 0043 because a conversation create is a
   durable write a leaked key could otherwise accrete without
   limit. Reads / status calls are not throttled.
3. **CORS allowlist**. When `settings.api_cors_allow_origins` is
   non-empty (comma-separated origins), FastAPI's `CORSMiddleware`
   is installed with those origins allowed, `X-API-Key` in
   `allow_headers`, and credentials allowed. Empty (default) means
   no middleware — same-origin only.

Source: `src/api/auth.py`. Wired in `src/api/app.py::create_app`
and route decorators in `src/api/routes.py`.

### Redis rate limiter + hot-reloadable keystore (ADR 0037)

Follow-up to the ADR-0033 auth bundle:

- `settings.rate_limit_backend`: `memory` (default, per-worker) or
  `redis` (shared ZSET on `ratelimit:{key_id}`, correct across API
  workers). Compose sets `redis`. Reuses the ADR-0027 JobStore's
  Redis client so no extra connection pool is opened.
- `settings.api_keys_file`: optional path to a JSON `{name: secret}`
  file. When set, overrides `settings.api_keys` and enables hot
  reload — a background `KeystoreReloader` polls mtime every
  `settings.api_keys_reload_interval_sec` (default 30) and swaps
  `app.state.api_keys` atomically. Parse failures are logged and
  the current keystore is retained; a bad edit doesn't lock
  legitimate callers out.

Wired in `src/api/auth.py::{InMemoryRateLimiter,RedisRateLimiter,
KeystoreReloader,build_rate_limiter,load_keystore_from_file}` and
`src/api/app.py::create_app`. `enforce_rate_limit` is async now so
both backends fit the same call site.

### API guardrails + deploy hygiene (ADR 0042)

Closes the audit findings on the seams between the ADR 0030/0033/0034
pieces:

- **Bounded HITL plans.** `Plan.sub_questions` / `Plan.search_queries`
  cap at 20 items x 500 chars (the planner emits 2-6). Before the
  cap, one `action=revise` request could hand the search node
  thousands of queries — each an arXiv call plus a hard 3s sleep on
  an executor thread the job timeout cannot cancel.
- **Loud resume-publish failures.** A failed
  `publish_remote_resume` on `POST /research/{id}/review` is logged
  at ERROR with the `job_id` (`hitl_resume_publish_failed`) instead
  of being suppressed — the review's 200 stands (the decision is
  persisted; the same-worker path resumed via the local Event), but
  the incident timeline now contains the drop.
- **Honest `/healthz`.** Pings Redis (via the store's client) and
  Postgres (when configured) under 2s timeouts, reports
  `status: ok|degraded` + a per-dependency breakdown, and computes
  `active_jobs` from the worker's own task set (it was a constant 0
  under the shipped Redis store). Always HTTP 200 — liveness, not
  readiness; see ADR 0042 for why.
- **Bounded drain.** `timeout_graceful_shutdown=10` in `serve.py`,
  which the compose command boots (`python -m src.api.serve`), plus
  `stop_grace_period: 30s`, so SIGTERM actually reaches the
  lifespan cleanup instead of hanging on open SSE streams until
  SIGKILL orphans in-flight jobs. The cleanup itself is bounded at
  every step (ADR 0047): cancelled jobs wait at most
  `runner.SHUTDOWN_DRAIN_SEC` for their node threads to unwind, and
  the node pool's join is capped the same way, so no single wedged
  agent can hold the container open to SIGKILL.
- **Credential redaction.** `redact_url()` in
  `src/observability/logging.py` strips userinfo from connection
  URLs before they hit the indexed JSON log stream; wired at the
  Postgres pool's startup log, remaining call sites migrate as
  their files are touched.

### Turning auth on under compose (ADRs 0042/0054)

The compose stack ships auth-off so `docker compose up` stays a
zero-config demo — which means the API is anonymous and unthrottled
on whatever interface `APP_PORT` is published to. **Never expose the
demo configuration beyond localhost.** To gate it:

```bash
WEB_API_KEY="replace-with-a-generated-secret" \
ENABLE_API_AUTH=true API_KEYS="web:replace-with-the-same-secret" \
  docker compose up
```

All three variables pass through `docker-compose.yml`: the app parses
`API_KEYS`, while the web container receives only the secret as
`ARXIV_API_KEY`. Its server-only `/api` route injects `X-API-Key` on
the private upstream hop. The raw key is neither a build argument nor
a `NEXT_PUBLIC_*` value. Notes:

- Set all three values consistently — `ENABLE_API_AUTH=true` with an
  empty `API_KEYS` boots, but every gated request 500s with
  `api_auth_misconfigured` (fail-closed, nothing is exposed). A missing
  or mismatched `WEB_API_KEY` makes web requests fail 401.
- `/healthz` is auth-exempt by design, so the container healthcheck
  and the `web` service's `service_healthy` gate keep passing.
- The rate limiter activates with auth (it is keyed per principal)
  and is Redis-backed in compose, so the limit holds across
  workers.
- CORS is empty by default because browser requests stay same-origin
  at Next.js. If a separate trusted browser client is introduced,
  configure an explicit `API_CORS_ALLOW_ORIGINS` list, never `*`.
- The proxy streams SSE and exports instead of buffering them, forwards
  only safe headers, rejects credentialed/non-HTTP upstream URLs, and
  maps an unreachable API to 502.

### Browser-facing hardening on the Next.js service (WO-30)

Four controls on the `web` service, all of them in front of the
credential boundary rather than inside it. The boundary itself —
`web/app/api/[...path]/route.ts` — is behaviourally unchanged;
`web/tests/apiProxyRoute.test.ts` passes unmodified, which is the
evidence for that claim.

**Content Security Policy.** `web/middleware.ts` mints a fresh
128-bit nonce per request and sets the policy on every document
response:

```
default-src 'self'; script-src 'self' 'nonce-…' 'strict-dynamic';
style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:;
font-src 'self'; connect-src 'self'; frame-ancestors 'none';
base-uri 'none'; object-src 'none'; form-action 'self'
```

- `'strict-dynamic'` makes the nonce the entire script allowlist, so
  an injected `<script>` — inline or same-origin — does not execute.
  Next stamps its own bundle tags automatically; the pre-paint theme
  script in `app/layout.tsx` carries the nonce explicitly.
- `connect-src 'self'` is sufficient because SSE is same-origin: the
  browser opens `/api/research/{id}/stream` on the Next origin and the
  proxy, not the browser, talks to FastAPI.
- **`style-src-attr 'unsafe-inline'` is the one directive that is not
  in the ratified policy.** It was added because the Report-Only run
  found three violations across the whole state matrix, all of them
  inline `style` attributes written by
  `components/primitives/Skeleton.tsx` for per-instance placeholder
  geometry, which no nonce or hash can cover. Naming `style-src-attr`
  separately leaves `style-src 'self'` intact, so `<style>` elements
  and stylesheet URLs remain same-origin only; chromium, firefox and
  webkit were each measured honouring the narrow form. Removing it is
  a follow-up, listed below.
- The policy is enforcing by default. `CSP_MODE=report-only` is the
  rollout switch for an observation window on a live deployment, and
  `CSP_MODE=off` exists only for `next dev`, whose HMR runtime needs
  `eval` and inline `<style>`.
- `/api/*`, `/_next/static/*` and `/icon.svg` skip the middleware so
  proxy and asset traffic take no extra hop. They are not left bare:
  `next.config.mjs` gives all three `default-src 'none'` plus
  `X-Content-Type-Options: nosniff`, which matters most for the SVG
  icon (a scriptable document when navigated to directly) and for
  proxied bodies the service did not author.

**Proxy request logging.** One structured JSON line per proxied
request on the web container's stdout: method, path **template**,
upstream status, duration, response bytes. Never the API key, never a
header, never a body, never a query string, and never a raw job or
conversation id — a path segment is emitted only when it is a literal
in `web/contract/openapi.json`, and anything else becomes `{id}`.
`ci/proxy-log-sample.txt` is a captured sample.

**Healthcheck.** The container probe was `GET /` and is now
`GET /api/healthz` through the proxy, so a misconfigured
`API_INTERNAL_BASE` no longer yields a healthy container serving a
broken app. It requires HTTP 200 and **does not** fail on
`status: degraded`: `/healthz` is always 200 by design (ADR 0042) and
restarting Next does not fix a dead Redis. It does parse `status` and
`dependencies` and print them, because HTTP 200 alone never means
healthy; `docker inspect` retains the last five reports.

**CSRF is not addressed, and is out of scope pending MT-01.** This
must not be read out of "the proxy is hardened". The proxy forwards
same-origin requests and attaches a server-held credential to every
one of them, and it has no per-user session to protect — so there is
no CSRF token, no `SameSite` cookie policy, and no origin check on
state-changing requests today. What limits the exposure now is that
the credential is not ambient browser state: it is held by the
server, so a cross-site request can only reach the proxy with
whatever the browser would send anyway, and the deployment boundary
(`deploy/hetzner/Caddyfile`'s HTTP basic auth) is a site gate rather
than a user account. **The moment MT-01 introduces a session at seam
S1 or S3, CSRF becomes a live requirement** — a session cookie is
ambient authority, and every state-changing route behind this proxy
(`POST /research`, `POST /research/{id}/review`,
`DELETE /conversations/{id}`) becomes forgeable without one. That
work belongs to MT-01's ADR, not here.

**`/api/auth/*` is reserved.** No route file exists and none is
created. Today the path falls into the catch-all and is forwarded
upstream, where FastAPI 404s it. When MT-01 adds
`web/app/api/auth/[...path]/route.ts`, the App Router's more-specific
segment takes precedence over the catch-all, so the login surface
lands without editing the credential boundary. `resolveUpstreamPrincipal`
in `web/lib/server/principal.ts` is the matching seam on the outbound
side: it returns the environment key unchanged today and is the single
place a session-derived principal would be resolved.

### Internet-facing Hetzner boundary (ADR 0054)

The production overlay in `deploy/hetzner/compose.prod.yml` is stricter
than local Compose:

- FastAPI and Next.js publish no host ports; Redis and Postgres never
  had any. Only Caddy publishes TCP 80/443.
- `ENABLE_API_AUTH=true`, prompt isolation, a per-run spend ceiling,
  and the Redis-backed per-principal rate limiter are explicit.
- Caddy obtains/renews HTTPS certificates, enforces a second
  human-facing bcrypt login over TLS, rejects request bodies above
  1 MB, and proxies only to Next.js on the private network.
- The Postgres password and internal web/API key are required secrets;
  Compose refuses to render the production configuration when either
  is missing.
- The Hetzner Cloud Firewall allowlists SSH from the administrator IP
  and HTTP/HTTPS from the internet; unmatched inbound traffic is
  denied. This is the outer control because Docker-published ports can
  bypass `ufw` rules.

### S7 — the deployment gate is not an identity

**Everything in this section describes the deployment on `main` and the
`deploy/hetzner` overlay. The `deploy/pilot` overlay (WO-W17, ADR 0063)
deliberately breaks two of its claims, and the next section says which.**

The production Caddy edge asks the browser for HTTP basic auth before
anything else is served (`deploy/hetzner/Caddyfile:8-10`):

```caddyfile
basic_auth {
	{$APP_USERNAME} {$APP_PASSWORD_HASH}
}
```

**That prompt is a deployment gate, not a user account**, and the
distinction is the whole of MT-01 seam S7. It is written down here
because the failure mode is a reader — or a future work order —
mistaking the basic-auth dialog for the identity system that
deliberately does not exist yet (D-009).

What it actually is: one site-wide credential, shared by everyone who
has it, checked by the reverse proxy before any request reaches
Next.js. It exists because the UI can initiate paid Anthropic work, so
the site gets a second human-facing gate in addition to the private
API key the proxy holds. It authenticates **access to the deployment**.

What it is not:

- It is **not a session.** Caddy does not issue one, and nothing
  downstream reads the basic-auth credential. It never reaches
  FastAPI, and it has no relationship to `X-API-Key`.
- It is **not a principal.** Every request that clears the gate arrives
  at the API as the same single principal. Two people with the same
  password are indistinguishable at every layer below Caddy.
- It is **not per-user scoping.** The backend's per-principal Job and
  Conversation scoping (ADR 0036, below) is real, but with one
  principal configured it partitions nothing. Everyone sees the same
  threads.

**The rule that follows: the UI must never render it as a signed-in
user.** No avatar, no username, no "signed in as", no account menu, and
no "your threads" — not even disabled, because a disabled login control
is still a claim that login exists. The web tier holds this
structurally rather than by convention: the header's `IdentitySlot`
returns `null` and is asserted to render nothing at all, and the
truthful string that occupies the header instead is "Shared workspace —
Everyone with access to this deployment sees these threads. There are
no separate accounts."

That string is what a deployment **with one principal** resolves, which
is every deployment on `main`. Under the pilot overlay below the same
slot states the principal the edge authenticated instead — still no
avatar, no account menu and no login control, because knowing a
username is not the same as having a session. See
[ADR 0063](decisions/0063-pilot-principal-edge-mapping.md) and
`web/lib/server/identity.ts`.

When MT-01 introduces real identity, it arrives at seam S1
(`resolveUpstreamPrincipal`) or S3 (session middleware) — not by
promoting this gate. Basic auth may then stay as an outer perimeter or
be removed, but it is not the mechanism being replaced, because it was
never doing that job.

### Pilot principals at the edge (WO-W17, ADR 0063)

**Default off. Nothing on `main` enables it, and only the literal string
`on` can.** `PILOT_EDGE_AUTH` is a web-tier setting; unset, empty and
`off` are off, and any *other* value makes the deployment refuse to
serve rather than quietly resolving the shared principal.

With it on, `deploy/pilot/compose.pilot.yml` puts an edge in front of
the web tier that carries **one `basic_auth` credential per pilot**
instead of one for the site, forwards the authenticated username as
`X-Pilot-User`, and `web/lib/server/pilot.ts` maps that username to that
pilot's already-issued per-principal API key from a server-side
environment map. The proxy then injects it as `X-API-Key` exactly as it
injects the shared one, so `web/app/api/[...path]/route.ts` remains the
sole credential boundary and no key ever reaches a browser.

**Two sentences in S7 above become false under this overlay, and they
are the two that matter.** The edge login *is* a principal selector, and
threads *are* per person. **The shell says so (WO-W17b).** The two
group layouts derive a `WorkspaceIdentity` per request from this
section's own setting and its own two headers
(`web/lib/server/identity.ts`) and hand it to the shell, which renders
one of three sentences: the shared one above with the mode off; "Pilot
workspace", naming the pilot the edge authenticated and saying what is
per person (threads, guided sessions, learner profile, ledger) and what
is shared (the paper and embedding caches), with the mode on; and
"Principal not resolved" when the mode is on and the request resolved to
nobody. It is **not** a feature flag — the derivation is a property of
the request, the descriptor carries no key, no `key_id` and no fault,
and with the mode off the rendered element is byte-identical to what it
was before the descriptor existed.

The guards, and what each one is for:

- **The username header is refused unless the request came through the
  edge.** The edge also sends `PILOT_EDGE_SECRET` as `X-Pilot-Edge-Key`,
  compared over SHA-256 digests with `timingSafeEqual`. This is MT-01's
  threat **T6** (identity-header spoofing) and its own mitigation:
  topology is *asserted*, never inferred. Inferring it would be safe in
  the production overlay, which publishes no port for `web`, and unsafe
  in base compose, which publishes it to loopback — the failure shape
  ADR 0039 recorded.
- **An ambiguous configuration refuses to serve.** Pilot map plus a
  non-empty `ARXIV_API_KEY` is a 503 for every request. Two configured
  answers to "whose credential is this" is an unanswered question, and
  the alternative — a fallback chain — is how a pilot silently becomes
  the shared principal.
- **An unknown username maps to no key**, 503, never the shared one.
  Every refusal returns the same body (`pilot_principal_unresolved`), so
  a response never reveals whether a username exists.
- **The map refuses duplicates and a sixth pilot.** Two pilots sharing an
  `api_key` or a `key_id` would read each other's profile and ledger
  under ADR 0036; a sixth pilot is SR-09's re-trigger, not a bigger
  pilot.
- **Nothing mints a key.** Both halves are written by hand into
  `api_keys_file` (hot-reloaded, ADR 0037) and the map, per the runbook.
  Neither file is ever committed; `.gitignore` covers both.
- **The key cannot reach a log.** The resolver's `pilot_principal` record
  type has no field that can hold one, and the username is logged only
  after the topology guard passes, so a forged header cannot write bytes
  into the log.

What it does **not** change: MT-01's findings F1 (`principal_key_id` is
a mutable display name — handled by the runbook's never-reassign rule,
which is a human control), F3 (the keystore is cleartext), F4 (no
aggregate spend cap — SR-09's arithmetic in the runbook is a bound, not
a control), and T7 (revocation latency is
`api_keys_reload_interval_sec`). CSRF is unchanged and still out of
scope: basic auth is not ambient the way a session cookie is.

One deliberate regression: the `web` container's healthcheck stops
probing `/api/healthz` through the proxy, because under pilot mode the
probe is not a pilot and is correctly refused. It reports liveness only;
`app`'s own healthcheck still proves FastAPI is serving, and the
runbook's per-pilot smoke test is an authenticated request through the
whole chain.

Source: `web/lib/server/pilot.ts`, `web/lib/server/principal.ts`,
`deploy/pilot/`. Tests: `web/tests/pilotPrincipal.test.ts` (the guards,
the redaction, and the built-bundle scan) and `web/e2e/pilot.spec.ts`
(two pilots on a seeded stack through the real edge).

### Per-principal Job + Conversation scoping (ADR 0036)

Every `Job` and `Conversation` carries a `principal_key_id: str |
None` field set to the caller's key_id at creation time. Route
handlers call `_check_ownership(resource_key_id, caller,
detail=...)` after every fetch:

- Auth off: caller has no principal; all rows are visible (legacy
  demo behavior).
- Auth on: caller must own the resource; otherwise **404** (not
  403 — leaking "this exists but you can't touch it" is an info-
  disclosure vector).
- Legacy rows (`principal_key_id=None`) are invisible under auth-on
  until an admin cleanup migration.

`ConversationStore.list(principal_key_id=...)` pushes the filter
into SQL for the Postgres store so scaled deployments don't drag
other tenants' rows across the wire per request.

`POST /research` additionally verifies the caller owns the
`conversation_id` they're piggybacking on — otherwise a hostile
key holder could dump their cost-bearing job into another
principal's thread.

Wired in `src/api/routes.py::_check_ownership` and
`_principal_key_id`. Postgres schema migration in
`src/tools/postgres_pool.py::SCHEMA_DDL` (ADD COLUMN IF NOT EXISTS
+ partial index on non-NULL).

### Legacy NULL-owner cleanup (ADR 0039)

ADR 0036 left rows written before it with `principal_key_id = NULL`,
invisible to every principal under auth-on. `python -m
src.api.admin_migrate` (`make admin-migrate`) is the operator tool
for them — deliberately a CLI a human drives, not an automatic
migration, because ADR 0036's reason for rejecting auto-assignment
still holds: the correct owner is usually knowable only by reading
the query text.

Safety properties worth knowing before you run it:

- **Dry-run by default.** Nothing writes without `--yes`. `report`
  never writes at all.
- **Mutations refuse to run under auth-off without an explicit
  opt-in** (ADR 0052). With `enable_api_auth=false` *every* row is
  NULL-owner, so the tool's predicate selects the whole store —
  `assign` and `delete` exit 2 unless the operator also passes
  `--include-all-auth-off`. Deliberately a separate flag from
  `--yes`: `--yes` means "I mean it", this one means "I understand
  the predicate selects everything". `report` is never refused, but
  its output opens with the auth mode and says under auth-off that
  the counts are the size of the whole store.
- **Blast radius is age-boundable.** `--older-than-days N` restricts
  every action to rows created more than N days ago (ADR 0052), so
  a cleanup can target the genuinely-legacy backlog.
- `assign --owner KEY_ID` **validates the key against the live
  keystore** (`api_keys`, or `api_keys_file` when set, matching
  `create_app`'s resolution order). Assigning to a nonexistent key
  would bury the data one level deeper.
- Rewriting a Redis row **preserves its TTL**. A plain `SET` would
  resurrect expired terminal jobs.
- Availability is decided by which store is *selected*, not by
  whether a URL happens to be configured — `postgres_url` is shared
  with the paper cache, embedding cache, and the ADR 0034
  checkpointer, so gating on it alone would point the tool at a
  `conversations` table the running service never reads.
- `delete` emits one structured log record per destroyed row. Once
  a Redis key is gone there is no other surviving evidence of what
  it was, so an aggregate count could never answer "was mine one of
  them?" during an incident review.

Blast radius is bounded by `--limit`, which applies **per store** —
`--store all --limit N` can touch up to 2N rows.
### Job leases and the redrive lock (ADR 0038, 0048, 0053)

Two Redis keyspaces: `joblease:{job_id}` (held by the worker
running a job, owner-checked CAS on refresh and release) and
`redrive:lock` (cluster-wide, held for the duration of one sweep —
startup or the periodic `job_redrive_interval_sec` sweep ADR 0053
added). Both are namespaced by the store's `key_prefix`, so two
deployments sharing one Redis cannot claim each other's leases or
contend for a single global lock. The lock's TTL is 30s (ADR 0048
cut it from 120s) so a worker killed mid-sweep does not lock out its
own restart, and every reclaim is a compare-and-set
(`update_if_status`) so a job that reaches a terminal state while
the sweep is deciding keeps its result.

`job_lease_ttl_sec` is the worst-case delay before a crashed
worker's jobs become reclaimable — and, correspondingly, the window
in which a hung-but-alive worker keeps its jobs off-limits to the
redriver.

### Adversarial tests

- `tests/test_reader_isolation.py` — canned jailbreak strings in the
  abstract, in the LLM's response (simulating a compromised model),
  and in evidence claims. Verifies both flag positions.
- `tests/test_planner_prior_context.py::TestPriorContextIsolation`
  — asserts that adversarial-looking prior_context is wrapped, not
  obeyed, when `enable_prompt_isolation` is on, and that the flag
  gates whether the system instruction is added.
- `tests/test_learner_profile_serializer.py` — jailbreak text planted
  in `profile_note` and in a goal statement (including one that tries
  to close the wrapper early) arrives isolation-wrapped, the guardrail
  instruction names the boundary, a learner cannot forge a provenance
  marker, and no inferred claim renders outside the "unconfirmed
  impressions" block in **either** flag position.
- `tests/test_learner_profile_store.py` — provenance is refused
  without a source, above the inference cap, at a reserved confidence,
  or without an evidence ref — in Python **and** by the table's CHECK
  constraints against a direct `psql` INSERT.
- `tests/test_learn_profile_routes.py` — a request body that names a
  `source` is still stored as `declared`; principal B never sees or
  destroys principal A's profile; the flag is a real off switch.
- `tests/test_arxiv_search.py::test_search_arxiv_rejects_entity_expansion`
  — proves `defusedxml` refuses a billion-laughs payload.
- `tests/test_pdf_parser.py::TestDownloadPdf` — proves declared-
  oversize and mid-stream oversize both abort without allocating
  the whole PDF, and that a URL masquerading with an arXiv-shaped
  path but a non-arXiv host doesn't share a cache slot with the
  real arXiv paper.
- `tests/test_runner_cost_cap.py` — proves `_enforce_cost_cap`
  raises `CostBudgetExceeded` at and above the ceiling, and that
  the empty accumulator never trips.
- `tests/test_api_auth.py` — end-to-end HTTPX suite proves every
  `/research` and `/conversations` route rejects missing / invalid
  keys and accepts a valid key, `/healthz` stays open, and the
  sliding-window rate limiter buckets per principal.
- `tests/test_per_principal_scoping.py` — end-to-end HTTPX suite
  with two API keys: verifies that principal B gets 404 on
  principal A's conversations (read, delete, piggyback via
  `POST /research`), that `GET /conversations` filters by
  principal, that `_check_ownership` treats legacy NULL-owner rows
  as invisible under auth-on, and that auth-off behavior is
  unchanged.
- `tests/test_redis_rate_limiter.py` — fakeredis-backed: under/
  over-limit → 429, sliding window slides, rollback on over-cap
  keeps the ZSET tight, per-key isolation, and — the production
  win — two `RedisRateLimiter` instances against the same Redis
  see the same counter (which the memory backend can't do).
- `tests/test_keystore_reloader.py` — file-format contract
  (bad JSON, non-object shape, empty values, duplicate secrets),
  initial-load seeds mtime, in-flight reload picks up a file
  change, and a broken edit is logged + skipped without evicting
  the current in-memory keystore.
- `tests/test_api_auth.py::test_non_ascii_key_returns_401_not_500`
  — parametrized raw-byte `X-API-Key` values (utf-8 Cyrillic, a
  lone `\xff`, a copy-pasted NBSP) each get a clean 401 instead of
  the pre-ADR-0042 TypeError 500; companion unit tests prove an
  ASCII key still matches when a non-ASCII secret sits in the
  keystore, and that a non-ASCII secret matches its own utf-8
  wire bytes.
- `tests/test_api_hitl.py::TestPlanBounds` — a 21-query or
  501-char-item revise plan is a 422 and is never applied to the
  workflow; a plan at exactly the caps goes through.
- `tests/test_api_hitl.py::TestResumePublishFailure` — a store
  whose `publish_remote_resume` raises still yields a 200 review,
  and the failure lands in the log with `job_id`, action, and
  traceback.
- `tests/test_api_guardrails.py` — compose contract pins (CORS
  allowlist present and never `*`, auth env pass-through, bounded
  drain with grace period above it), uvicorn graceful-shutdown
  wiring, and the Postgres pool's server-side timeouts.
- `tests/test_log_redaction.py` — `redact_url` strips passwords,
  password-only userinfo, and bare usernames while leaving
  credential-free URLs untouched.

## Follow-ups

- ~~**The shell's "Shared workspace" copy contradicts the pilot overlay**, and
  must be resolved before any pilot is invited.~~ **DONE — WO-W17b.** The
  identity slot now states the principal the server resolved for the request:
  the shared sentence with the mode off (byte-identical to what it rendered
  before), "Pilot workspace" naming the edge-authenticated pilot with the mode
  on, and "Principal not resolved" when the mode is on and the request
  resolved to nobody. Not a runtime flag (SR-07): the descriptor comes from
  `web/lib/server/identity.ts`, carries no key, no `key_id` and no fault, and
  is derived in the two group layouts rather than at the credential seam. See
  "Pilot principals at the edge" above and ADR 0063's Consequences.
- **An aggregate spend cap** (MT-01 F4, Phase L0-01). The pilot is bounded by
  the arithmetic in `docs/runbooks/pilot.md` §3 and by the provider account's
  own limit — neither of which is a control in this repository. Any cohort
  beyond five, any public opening, or any scheduled work re-triggers this as a
  prerequisite (SR-09).
- **A role model, so "withhold `POST /research`" is a permission rather than a
  `max_cost_usd` value.** `ApiKeyPrincipal` carries a `key_id` and nothing
  else, so the pilot's expensive action is capped rather than removed (ADR
  0063, runbook §9). This is the same follow-up the ADR 0039 note below asks
  for, reached from the other direction.
- **CSRF on the `/api` proxy**, the moment MT-01 introduces a session
  (seam S1 or S3). Not a gap in the current design — there is no
  per-user session to forge a request on behalf of — and a hard
  requirement as soon as there is one. See "Browser-facing hardening
  on the Next.js service" above.
- Retire `style-src-attr 'unsafe-inline'` from the CSP by tokenising
  `components/primitives/Skeleton.tsx`'s per-instance width/height
  into classes. Three inline `style` attributes are the only reason
  the directive exists; with them gone the policy is exactly the
  ratified one.
- Extend isolation into the synthesizer and verifier prompts (they
  read `EvidenceClaim.source_text` and paper analyses; both are
  vectors even with the reader defended).
- Default `enable_prompt_isolation` on once Sprint 4 baseline
  numbers exist with it enabled.
- Structured logging / metrics on sanitization drops so we can see
  how often the filter fires in production.
- Content-classifier-based rejection at ingest (an extra Claude
  call per paper; scope for Sprint 5+ if the deployment model
  justifies the cost).
- Atomic-write PDF cache (write to `.tmp` sibling, rename on
  completion).
- Role-based access on `ApiKeyPrincipal`, so `admin_migrate`'s
  actions can eventually be driven through an authenticated
  endpoint instead of shell access to a worker (ADR 0039
  follow-up).
- Lua-scripted `check_and_record` for the Redis rate limiter if
  the boundary race becomes observable (ADR 0037 follow-up).
- Expose `RedisJobStore.client` as a public property to remove
  the `_client` coupling in `create_app` and `/healthz`
  (ADR 0037 follow-up).
- Request body-size cap as an outermost ASGI middleware — today
  the full body is buffered before auth runs (ADR 0042 deferred).
- Cap per-principal conversation counts (the rate limit on
  `POST /conversations` landed in ADR 0043, drawing from the same
  hourly budget as `/research`; a total-rows cap is still open).
- Derive the stored owner from the secret (stable `owner_id`)
  instead of the mutable display name — removes the rename/reuse
  hazard structurally; needs a row migration (ADR 0042 interim:
  duplicate-name rejection + permanence rule).
- `/readyz` with 503-on-dependency-failure semantics for
  orchestrators that want dependency-gated routing (`/healthz`
  deliberately stays 200 — ADR 0042; ADR 0053 re-affirmed the
  liveness-only scope when it considered a model-warmup probe).
- Cache purge command for the paper / embedding caches, now that
  the `created_at` indexes exist to support it (ADR 0042 follow-up;
  `admin_migrate delete --older-than-days` covers only NULL-owner
  job / conversation rows, not the caches).
