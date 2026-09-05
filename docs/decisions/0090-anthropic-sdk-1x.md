# 0090. Anthropic SDK 1.x

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: agent-capability lane (CAP-05)

## Context

`pyproject.toml` capped the model SDK at `anthropic>=0.39.0,<1.0` and
both lockfiles pinned `0.116.0`. The cap was doing real work — it kept
an upstream major out of a fleet whose entire spend, retry and
observability story funnels through one module — but it had also
started to cost something. `planning/08-assurance/02-STANDARDS.md` §6.1
recorded the reason as a landmine to defuse deliberately rather than
discover in CI:

> The model SDK's 1.x line runs on **`httpx2`**, and as a direct
> consequence `respx`, `pytest-httpx` and OpenTelemetry's HTTPX
> instrumentation **do not see the SDK's requests** unless an aliasing
> call is made at startup; passing a plain `httpx` client raises
> `TypeError`.

Two things forced the decision now. The cap blocks every later
capability order that wants a 1.x-only surface, and the longer it
stands the larger the version jump becomes. And the assurance lane
needs to know whether this repository is actually exposed to the §6.1
hazard before it plans around it.

The assumption that would change this answer: that the repository
mocks HTTP by patching `httpx`. It does not — see **Consequences**.

## Decision

Pin `anthropic==1.4.0` (the latest published 1.x) in both lockfiles and
widen the range to `anthropic>=1.0,<2.0`. Four things follow, and
nothing else in `src/` changes.

**The request body is unchanged, and that is checked rather than
claimed.** `tests/test_llm_request_golden.py` pins the exact kwargs
`src/llm.py` sends for four representative calls. The fixture
`tests/fixtures/llm/request_kwargs_golden.json` is **byte-identical**
across the upgrade (sha256
`58b0d893bc15e54a2bf0de67dedaf97775dd817f8ac30ee898bb3af82adba051`
before and after), so the wire request this gateway builds on 1.4.0 is
the request it built on 0.116.0. No line of the fixture was
regenerated.

**Structured outputs keep using `anthropic.transform_schema`.** ADR 0077
chose the transform over `client.messages.parse` because
`messages.with_raw_response` wrapped only `create` and `count_tokens`,
and this gateway reads `retries_taken` off the raw response — ADR 0051's
retry-visibility fix. The obvious question at a major bump is whether
1.x finally offers `with_raw_response.parse`, which would let the
transform go away. It does not: on 1.4.0 `MessagesWithRawResponse`
exposes `create`, `count_tokens` and `batches`. The ADR 0077 rationale
therefore survives the upgrade intact, and the comment in
`call_llm_json` now records that it was re-checked at 1.4.0 rather than
asserting a fact about a version nobody is running.

**The timeout is now `anthropic.Timeout`, not a bare float.** The SDK
re-exports `httpx2.Timeout` under its own name, which keeps the one
timeout this fleet configures typed at the boundary it crosses without
putting `httpx2` in `src/llm.py`'s imports. It is the same request
either way — `httpx2.Client(timeout=120.0).timeout` and
`httpx2.Client(timeout=anthropic.Timeout(120.0)).timeout` both
normalise to `Timeout(timeout=120.0)`, all four of
connect/read/write/pool at the configured value, which is exactly what
handing `httpx` the float did on 0.x. `_retry_envelope`'s arithmetic,
the clamp, and the `llm_client_configured` / `llm_retry_budget_clamped`
lines are untouched.

**Three test modules move to `httpx2`.** `tests/test_llm.py`,
`tests/fault/test_model_provider_faults.py` and
`tests/fault/test_supervisor_routing_faults.py` build a *real*
`anthropic.APIStatusError` / `APITimeoutError` from a real response,
deliberately, so that `call_llm`'s reads of `exc.status_code` and
`exc.request_id` cannot rot unnoticed. On 1.x a real SDK error carries
an `httpx2.Response`, so those three now `import httpx2 as httpx` — an
alias, so every call site below reads unchanged.

Error classes (`anthropic.APIStatusError`, `anthropic.APIConnectionError`,
`anthropic.APITimeoutError`), the `UpstreamModel` / `UpstreamModelOutput`
mapping, `NOT_GIVEN`, and cost accounting are all unchanged.

## What was verified, and how

Everything below was checked **without a live API call**. No request
left the machine; `ANTHROPIC_API_KEY` was `local-preview-disabled`
throughout, and the suite's own network guard was left armed.

- **Request shape.** The golden fixture is byte-identical (above). This
  is a statement about the body `src/llm.py` *builds*, not about what
  Anthropic does with it.
- **Isolation guards still bind on the new transport.** A throwaway
  probe drove a real `httpx2.Client` and a real `anthropic.Anthropic`
  1.4.0 client at `api.anthropic.com`; both were stopped by
  `tests/conftest.py`'s `_network_guard`, which patches
  `socket.socket.connect` / `connect_ex` and so is indifferent to which
  HTTP library sits above it. `_spend_guard` is likewise keyed on
  `src.llm._get_client` and `src.llm.anthropic.Anthropic`, neither of
  which the SDK major touched. The probe was not committed — it proves
  a property of the guards, not of this diff.
- **Full gate.** 5078 passed, 54 skipped, 0 failed; `mypy src/` clean on
  130 files; `ruff check src/ tests/` clean. Run in a throwaway venv
  built from `requirements-lock.txt` alone, so it is lock-exact.
- **The lock is a real lock.** `pip check` exits 0 unscoped, and
  `scripts/derive_runtime_lock.py --check` is clean.

## What CAP-06 (funded smoke) must verify live

Nothing above touches provider behaviour. **No live call was made, so
Anthropic's behaviour on the new SDK is unverified.** A funded smoke
must confirm, against the real API:

- a plain `call_llm` round trip returns text, and `record_llm_call`
  receives non-zero `input_tokens` / `output_tokens` — the cost table
  is derived from these and no test exercises the real `usage` object;
- `raw.retries_taken` is populated by the 1.x raw-response class on a
  call that actually retried (every test supplies this field from a
  double);
- the prompt-cache buckets `cache_read_input_tokens` /
  `cache_creation_input_tokens` still arrive under those names on a
  `cache_system=True` call;
- a structured-output call with `output_config.format` built by
  `anthropic.transform_schema` is accepted and returns schema-valid
  JSON — the golden fixture proves the body is unchanged, not that the
  provider still accepts it;
- an induced 4xx/5xx surfaces as `anthropic.APIStatusError` with a
  readable `request_id`, so `_log_upstream_error` records what an
  on-call engineer needs.

## Alternatives considered

- **Stay on 0.116.0.** Free today, and the cap keeps working. Rejected
  because it defers a jump that only grows, and because §6.1 was
  written specifically so that this move would be taken deliberately
  rather than under pressure from a later order that needs a 1.x-only
  surface.
- **`httpx2.alias_httpx()` at the entry point.** The migration guide's
  process-wide switch, and the fix §6.1 names. Rejected: it is aimed at
  applications that share transports between the SDK and other `httpx`
  code, or that depend on tooling which patches `httpx`. This
  repository does neither — see below — so aliasing would buy nothing
  and would add a hard ordering constraint (it must run before anything
  imports `httpx`, or it raises `RuntimeError`) to every entry point
  and to pytest startup. Three aliased imports in three test modules
  are cheaper and local.
- **Switch structured outputs to `with_raw_response.parse`.** Would
  retire `transform_schema`. Not possible: the method does not exist on
  1.4.0 (above).
- **Pin `anthropic>=1.4,<2.0`.** Rejected; nothing in `src/` uses a
  post-1.0 addition, so the floor would advertise a constraint the code
  does not have. The lock records 1.4.0 as what was tested.

## Consequences

- **Positive**: the cap that blocked every later capability order is
  gone, and the §6.1 landmine is defused with the exposure measured
  rather than assumed.
- **Positive**: the §6.1 hazard turns out **not** to apply here. The
  repository contains no `respx`, no `pytest-httpx`, no `vcrpy`, no
  `httpx.MockTransport` and no `HTTPXClientInstrumentor` — the model is
  faked at `src.llm._get_client` and at `src.llm.anthropic.Anthropic`,
  above the HTTP layer entirely, and the network guard sits below it at
  the socket. That is why the upgrade cost three import lines instead
  of a test-seam rewrite, and it is an argument for keeping fakes at
  those two seams.
- **Negative**: the tree now carries two HTTP client libraries.
  `httpx` drives the FastAPI app in-process through `ASGITransport` in
  a dozen test modules and never meets the SDK; `httpx2` is the SDK's.
  Both are declared in the `dev` extra with a comment saying which is
  which, but a reader who does not notice can write a test that hands
  an `httpx` object to the SDK. It will not fail loudly: 1.4.0 accepts
  an old `httpx.Response` when constructing `APIStatusError`, which is
  precisely how a fake drifts from what the SDK really produces.
- **Negative**: the lock grew three transitive pins (`httpx2`,
  `httpcore2`, `truststore`) that nothing in `src/` imports directly.
  `truststore` in particular is new attack surface in the runtime
  image, reached only through the SDK's default TLS path.
- **Negative**: the four changed lock lines were frozen on Python 3.13,
  not the 3.14 the other 125 pins and CI use. All four are
  `py3-none-any` wheels, so the resolution is interpreter-independent,
  but the lock header now has to say so.
- **Follow-ups**: CAP-06's funded smoke, per the list above — until it
  runs, provider behaviour on 1.x is unverified. `planning/08-assurance/
  02-STANDARDS.md` §6.1 should be annotated to say the cap was raised
  and the hazard did not land; that file is the assurance lane's to
  edit, not this order's.
