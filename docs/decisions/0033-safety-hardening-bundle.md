# 0033. Safety hardening bundle: transport, auth, budget, injection

- **Status**: accepted
- **Date**: 2026-07-13
- **Deciders**: kudratsingh

## Context

An audit of the codebase turned up a cluster of production-blocking
defects that share one theme: an anonymous or hostile caller can drive
the workflow at unbounded cost or with attacker-controlled content.

Concretely (all verified in `main` before this ADR):

- `POST /research` had no authentication and no rate limits. Anthropic
  billing was directly reachable by any HTTP client that discovered
  the port.
- `ARXIV_API_URL` used `http://`, so an in-flight MITM could inject
  attacker-chosen `PaperMetadata` that then drove Claude prompts and
  PDF fetches. The XML parse used stdlib `xml.etree` with no XXE
  guard.
- `parse_pdf` called `resp.content` and loaded the full body into
  memory. A 500 MB adversarial PDF would OOM the process. The cache
  key regex matched an arXiv-ID pattern anywhere in the URL, so
  `https://evil.com/2311.09000/attack.pdf` collided with the real
  arXiv paper's cache slot.
- `max_cost_usd` was enforced only by the supervisor. The default
  fixed-DAG path (`enable_supervisor=False`) had no per-run cost
  ceiling — up to `max_iterations` full plan/search/read/synth
  cycles ran unchecked on adversarial inputs.
- Conversation follow-up mode (ADR 0032) fed `prior_context` — text
  drawn from prior LLM reports over adversarial-controllable paper
  input — directly into the planner's user prompt with no isolation,
  reopening the injection surface that ADR 0020 closed for the reader.

Each is small on its own; together they form the surface a hostile
caller would probe first. Bundling them into a single ADR keeps the
"what changed to make this deploy-safe" story in one place.

## Decision

Ship six changes as one bundle. Each is minimal and independently
testable; together they close the audit findings above.

1. **arXiv transport hardened.** `ARXIV_API_URL` moves to
   `https://export.arxiv.org/api/query`. Response parsing switches
   from `xml.etree.ElementTree` to `defusedxml.ElementTree` so
   entity-expansion / XXE payloads are refused at parse time. Added
   `defusedxml` (+ `types-defusedxml` dev) to `pyproject.toml`.

2. **PDF fetch bounded and cache key tightened.** `_download_pdf`
   streams the response body with `iter_content` and aborts once
   `settings.pdf_max_bytes` (default 50 MiB) is reached. Servers that
   declare Content-Length above the cap are rejected before any
   bytes flow. `_cache_key` only extracts an arXiv ID when
   `urlparse(pdf_url).hostname` is under `arxiv.org`; other hosts
   fall through to the SHA hash.

3. **Runner-level cost cap.** `src/api/runner.py` gains
   `CostBudgetExceeded` and a helper `_enforce_cost_cap` called from
   the runner's `on_node` callback between graph nodes. This
   catches the fixed-DAG path where the supervisor's check doesn't
   apply. Overflow terminates the job as `failed` with
   `error_type=cost_budget_exceeded`.

4. **Planner prior_context isolation.** `prompt_isolation.py` gets a
   distinct `<untrusted_prior_context>` tag pair,
   `wrap_untrusted_prior_context()`, and
   `PRIOR_CONTEXT_ISOLATION_INSTRUCTION`. Planner uses them when
   `settings.enable_prompt_isolation` is on and the state carries
   `prior_context`, so cross-turn prompt injection has the same
   defense pattern as reader input (ADR 0020).

5. **API-key auth + per-key rate limit + CORS allowlist** in
   `src/api/auth.py`:
   - `X-API-Key` header, keystore parsed at startup from
     `settings.api_keys` (`name:secret` pairs, comma-separated).
   - `_lookup_principal` uses `hmac.compare_digest` in a
     non-short-circuiting loop so timing stays constant.
   - `RateLimiter` — in-memory sliding-window submit counter, keyed
     by principal, capped at `settings.api_key_hourly_limit`. Only
     `POST /research` is throttled; reads and status calls aren't.
   - CORS middleware installed only when
     `settings.api_cors_allow_origins` is non-empty.
   - All `/research` and `/conversations` routes carry
     `dependencies=[Depends(require_principal)]`. `/healthz` and
     `/docs` stay open — liveness probes and OpenAPI docs must not
     require a key.

6. **Documentation.** `docs/security.md` updated with the new
   threat model (transport, budget, prior_context injection), the
   auth story, and how to configure keys and CORS.

Everything except the arXiv/PDF fixes is **flag-gated off by
default** (`enable_api_auth=False`, empty `api_cors_allow_origins`).
The arXiv/PDF fixes are always on — they are pure hardening with no
behavior change on non-adversarial inputs. This keeps the local-dev
/ eval-runner / existing-test paths byte-identical.

## Alternatives considered

- **Auth via OAuth 2.0 / JWT.** Rejected for this bundle: adds an
  identity provider dependency (or an in-repo OIDC issuer) that dwarfs
  the actual security problem. API keys are the industry-standard
  minimum for a demo-scale service driving Anthropic; upgrading to
  OAuth is a follow-up when a real customer identity system exists.
- **Rate limiter in Redis from day one.** Rejected: this bundle
  already touches auth + budget + injection; adding Redis-backed
  rate limits blows the PR size and forces a Redis dependency on
  the auth-on path. The in-memory limiter is correct per-worker;
  under multi-worker uvicorn the effective limit is
  `limit * n_workers`, which is documented and acceptable for the
  demo scale. Redis-backed limiter is a follow-up alongside the
  Redis-backed cross-worker SSE (ADR 0027 revisit).
- **Per-principal ownership on Job / Conversation stores.** Rejected
  for this bundle: touching the Store protocol + Job dataclass +
  Redis serialization is a large blast radius. Once auth is on,
  only holders of a valid key can hit the endpoints — so the
  "anyone reads anyone's data" issue is much reduced (though not
  gone). Follow-up PR adds `principal_key_id` scoping on `list()`,
  `get()`, `delete()`.
- **Global request-body size limit via middleware** instead of the
  PDF-specific cap. Rejected: the PDF path fetches an external URL,
  not a user upload — a request-body limit doesn't cover it. The
  streaming cap in `_download_pdf` is the correct fix.
- **Drop the runner cost cap and require `enable_supervisor=True`
  for cost protection.** Rejected: making the supervisor mandatory
  is a much larger behavior change than a 20-line runner check, and
  the runner check is cheaper (no LLM call, one float comparison
  per node).
- **Reject prior_context content that matches injection heuristics
  instead of wrapping.** Rejected: consistent with ADR 0020, we
  isolate rather than filter. Filtering is brittle and hides the
  attack from the model; wrapping lets Claude judge in-context with
  the guardrail explicit.
- **New tag reuse for prior_context** (reuse `<untrusted_paper_text>`).
  Rejected: distinct tags let the planner's system instruction name
  `sub_questions` / `search_queries` as the fields to protect, matching
  the reader's guardrail on `analysis_complete` /
  `request_more_sections` / `missing_context`.

## Consequences

**Positive**

- API keys close the "anonymous caller drains Anthropic account"
  hole in one setting toggle. CORS allowlist covers the browser
  side.
- Per-run cost cap now applies uniformly to both graph shapes.
- MITM against arXiv can no longer inject `PaperMetadata`; XXE
  parser surface closed.
- 500 MB adversarial PDF is refused before it lands in memory.
- Cache poisoning across arXiv IDs from arbitrary hosts closed.
- Cross-turn prompt injection via prior_context is contained under
  the existing `enable_prompt_isolation` flag.

**Negative**

- Rate limiter is per-worker in-memory. Under multi-worker uvicorn
  the effective limit is `api_key_hourly_limit * n_workers`.
  Documented as a follow-up (Redis-backed limiter alongside the
  ADR-0027 revisit).
- API-key rotation requires a restart (keystore is parsed once at
  startup). Documented; a future PR can move keystore to Redis and
  hot-reload.
- `Job` / `Conversation` stores are not yet per-principal scoped.
  Once auth is on, only key holders can reach the endpoints, but
  key holders can still read each other's data. Follow-up PR.
- `defusedxml` adds ~25 KB dependency. Acceptable.
- Streaming PDF download loses the "atomic write" property — a
  partial write is possible if the process dies mid-fetch. Callers
  already tolerate zero-length or missing PDFs, but a future PR
  could write to a `.tmp` sibling and rename on completion.

**Follow-ups**

- Per-principal ownership scoping on `Job` + `Conversation` stores.
- Redis-backed rate limiter.
- Hot-reloadable keystore.
- Atomic-write PDF cache.
- Redis pub/sub for cross-worker SSE resume — the crit-2 bug the
  audit flagged; separate PR because it needs the ADR-0013
  `SqliteSaver`-to-`PostgresSaver` switch first.
- Flip `enable_supervisor` / model-routing defaults per the
  ADR-0021 revisit.
