# Contract drift proof — all four checks green

Produced by [WO-26](../../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack),
criterion 8. The four checks are
[`04` §3.5](../../../04-ARCHITECTURE.md#35-drift-detection-without-a-live-backend-in-ci)'s.

The backend contract is frozen for this revamp, so "no drift" is the whole
claim: the typed client still describes the API the server actually serves, the
recorded fixtures still parse, and the SSE event vocabulary is identical on
both sides of the wire.

| # | Check | Command | CI job | Result | Raw output |
|---|---|---|---|:-:|---|
| 1 | OpenAPI snapshot | `pytest tests/test_contract_openapi_snapshot.py -q` | `tests` | ✅ **4 passed** | [`openapi-snapshot.txt`](openapi-snapshot.txt) |
| 2 | Generated-type diff | `npm run contract:check` | `web` | ✅ **match** | [`generated-types.txt`](generated-types.txt) |
| 3 | Fixture parse | `vitest run --project=unit tests/contract/fixtures.test.ts` | `web` | ✅ **63 passed** | [`fixtures.txt`](fixtures.txt) |
| 4 | SSE event-name pinning — producer | `pytest tests/test_contract_sse_events.py -q` | `tests` | ✅ **7 passed** | [`sse-events-producer.txt`](sse-events-producer.txt) |
| 4 | SSE event-name pinning — consumer | `vitest run --project=unit tests/contract/{events,sse}.test.ts` | `web` | ✅ **55 passed** | [`sse-events-consumer.txt`](sse-events-consumer.txt) |

**All four are green. 129 assertions across five files, zero failures.**

---

## 1. OpenAPI snapshot

`tests/test_contract_openapi_snapshot.py` asserts
`document == create_app().openapi()` after popping the `x-provenance` key — the
committed `web/contract/openapi.json` is still exactly what the running app
generates. It is a unit test: `create_app()` builds the router only and the
lifespan that would open Redis and Postgres is never started, so the check
needs no stack and no network.

Four assertions: the snapshot matches the live document; the provenance header
is first and says how to regenerate it; the snapshot covers every route the
frontend calls; and `stream` and `export` are deliberately *undescribed*, which
is why the hand-written overlay exists at all.

## 2. Generated-type diff

`web/contract/check-generated-types.sh` regenerates `schema.d.ts` from
`contract/openapi.json` into a temporary directory and `diff -u`s it against
the committed file. `openapi-typescript` is pinned to an exact version (no
caret) precisely because this check compares bytes: a floating minor that
changed its formatting would fail an unchanged `main` with no commit to
revert. The generator runs with `--no-install`, so a missing dependency is an
error rather than a silent download of some other version.

Green is one line, and it is what the raw output contains:

```
contract:check — generated types match contract/openapi.json
```

## 3. Fixture parse

`web/tests/contract/fixtures.test.ts` runs all fourteen recorded fixtures —
five job states, two conversation shapes, seven error envelopes — through the
typed client and validates each against a Zod schema **derived** from the
generated OpenAPI types. The derivation is enforced in both directions:
`proves<Exact<z.infer<typeof schema>, Model>>(true)` fails to *compile* if the
schema and the generated model diverge either way, and `.strictObject` fails at
*runtime* if a recorded body carries a key the schema does not know.

The error envelopes matter most. §3.5 says generation alone produces false
confidence about them (R-06), because FastAPI's `detail` is `Any` and the
generated type therefore says nothing useful; only a recorded body proves the
shape.

The same file also asserts the recorder's own safety properties — that
`web/contract/record.sh` refuses to run in CI, and that it never POSTs to the
endpoint that submits a job.

## 4. SSE event-name pinning

Two halves, and adding a backend event breaks both.

**Producer** — `tests/test_contract_sse_events.py` pins the set to a literal:

```python
PINNED_EVENT_NAMES = frozenset(
    {
        "job_started",
        "node_completed",
        "plan_ready",
        "job_completed",
        "job_failed",
        "job_cancelled",
        "stream_timeout",
    }
)
```

…and then *derives* the same set from the emit sites in `src/api/runner.py`,
`src/api/routes.py` and `src/api/streaming.py` by regex, so a new non-terminal
event fails too. It also reads the literal back out of
`web/lib/api/events.ts`, which is what makes the two halves one check rather
than two.

**Consumer** — `web/tests/contract/events.test.ts` declares the same seven
names and asserts `events.ts` carries exactly that set at the value level *and*
at the type level, that there is no `node_started` (the runner emits only after
a node returns), and that `stream_timeout` is a member of the wire set but not
an outcome. `web/tests/contract/sse.test.ts` is the supporting half: it
validates the nine recorded `.jsonl` scripts against the `events.ts` overlay
and pins their JSON Lines format.

---

## What this does not cover

Drift checks prove the *shape* of the contract has not moved. They do not prove
the running backend behaves as the fixtures describe — that is what the seeded
stack and the Playwright slice are for ([`../playwright/`](../playwright/)) —
and they say nothing about the two endpoints the snapshot deliberately leaves
undescribed, `stream` and `export`, whose behaviour is covered by
`web/e2e/stream.spec.ts` and `web/e2e/export.spec.ts` instead.
