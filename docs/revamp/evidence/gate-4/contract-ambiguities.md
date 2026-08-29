# The twelve contract ambiguities — assumption shipped, and who ratified it

**WO-33 acceptance criterion 5:** *"Each of the twelve
[§11](../../04-ARCHITECTURE.md#11-contract-ambiguities-to-resolve-at-gate-2)
ambiguities is listed with the assumption shipped and whether Gate 2 ratified
it."*

Two things this file is careful about.

1. **"Ratified" is not one thing.** Four of the twelve were named individually
   in [`DECISIONS.md` D-010](../../DECISIONS.md)'s sixteen rulings. The other
   eight were ratified as part of the *approved package* — D-010's "Package
   approved: `04-ARCHITECTURE.md` + `05-MIGRATION.md` (PR #70)" — which is a
   weaker, broader act. The table says which, per row, rather than writing
   "yes" twelve times.
2. **"Shipped" is checked against code, not against the plan.** Every row names
   the module that implements the assumption and the test that pins it, read
   out of the tree at `80f6081`. Where the pin is weaker than the claim, the
   row says so.

**[§4.3](../../05-MIGRATION.md#43-what-gate-4-must-not-claim) forbids claiming
these are resolved, and this pack does not.** They remain frontend
*assumptions* ratified by the coordinator under the D-010 delegation. None was
answered by the backend, none changed the contract, and each stays exactly as
reversible as it was.

---

## The table

| # | Ambiguity | Assumption shipped | Shipped in | Pinned by | Ratified |
|---|---|---|---|---|---|
| 1 | `last-event-id` is forwarded but inert — the proxy allowlists it, `format_sse` never writes an `id:` line | **Reserved, unused.** The allowlist entry stays; no client sets the header; no code change either way | `web/app/api/[...path]/route.ts:50` — `REQUEST_HEADERS = ["accept", "content-type", "last-event-id"]` | `web/tests/apiProxyRoute.test.ts` (forwarding); `web/tests/contract/sse.test.ts` + `web/tests/job/checkpoint.test.ts` (no backlog / resume contract exists) — **see the note below** | **Named ruling** — D-010 r15 |
| 2 | `stream_timeout` had no client handler; the old adapter dropped it silently | **Handle it and reopen immediately** (04 §4.4) | `web/lib/job/useJobStream.ts:402-408` — dispatch, then `openStreamRef.current(jobId)` in the same tick; reducer `timeoutFrame`, `web/lib/job/machine.ts:516` | `web/tests/job/stream.test.ts` — *"opens a new connection in the same tick, with no timer to wait out"*; *"is not a terminal event"*. E2E `web/e2e/stream.spec.ts` | Package (04 §4.4) |
| 3 | Terminal payloads are asymmetric between live and replay, in both directions — one event name, three shapes | **Every terminal frame is a signal only; all values come from `GET /research/{id}`** (H9) | `web/lib/job/machine.ts:332` `signalTerminal()` → phase `reconciling`, recording only name/shape/arrival; the read fires at `web/lib/job/useJobStream.ts:417` | `web/tests/job/terminal.test.ts` — *"records only the name, the shape and the arrival time"*, *"displays the settled JobDetail, whichever shape signalled it"* (six payload shapes → one rendered answer), *"does not believe a replay frame's status over the read"* | Package (04 §3.2, H9) |
| 4 | `plan_ready` can legitimately arrive twice on the in-memory path | **Idempotent handling; no duplicate-detection warning shown** | `web/lib/job/machine.ts:493` `planFrame` — log the frame, set the same state | `web/tests/job/stream.test.ts` — *"a second frame changes nothing but the log"*, *"is idempotent in the reducer too"*, *"survives the plan arriving from JobDetail and then again as a frame"* | Package |
| 5 | `ReviewResponse.status` is always `pending_review` — a 200 does not mean the run resumed | **Enter `resolving` and wait for SSE or a poll** (04 §4.5) | `web/lib/job/machine.ts:836` — `review_accepted` → `phase: "resolving"` | `web/tests/plan/review.test.tsx` — *"enters resolving and waits for a frame or a poll"* (and asserts the DOM never says "resumed"), *"shows the run moving only once the server says it moved"* | Package (04 §4.5) |
| 6 | `GET /conversations` has no `total` or `has_more`; the legacy client sent no `limit`/`offset` and truncated silently at 50 | **Explicit paging with "Load more"; no page counts** (04 §4.6) | `web/lib/queries/conversations.ts:110` infinite query; params at `web/lib/api/client.ts:300`; control at `web/components/patterns/ThreadList.tsx:277` | `web/tests/queries/conversations.test.ts` — *"the list sends explicit limit and offset"*, *"pagination is Load more"*, *"exposes no total, no page count, and no 'showing 50 of N'"* | Package (04 §4.6) |
| 7 | Export permits a **failed** job's partial report while the legacy UI hid it. §11 marks this ***needs a product ruling*** | **Show it and allow export, clearly labelled partial** (H5) | `web/components/patterns/ExportDisclosure.tsx:32-36` — *"has no `status` prop and cannot acquire one"*; labelling in `web/components/patterns/ReportReader.tsx:285-308` (`data-partial`) | `web/tests/patterns/ExportDisclosure.test.tsx` — *"offers the same three links for a failed run's retained briefing"*; `web/tests/patterns/ReportReader.test.tsx`; E2E `web/e2e/export.spec.ts` | **Named ruling** — D-010 r2 |
| 8 | The 429 `detail` is an object while every other error is a string; the legacy client rendered raw JSON to the user | **Normalize in `errors.ts`** (04 §3.4) | `web/lib/api/errors.ts:237-250` — `readRetryAfter`, `readLimitPerHour`, `rateLimitMessage` | `web/tests/apiErrors.test.ts` — *"429 with the object detail and Retry-After"* (asserts the sentence, `retryAfterSec`, `limitPerHour`, and that `message` never contains `key_id`); the shared body asserts `message` never contains `{` or `[` | Package (04 §3.4) |
| 9 | 404 means both "missing" and "not yours" — correct by design | **The UI must never guess which** (H8) | `web/lib/copy/errors.ts:92-109`; `web/lib/copy/trace.ts:146`; `web/components/patterns/NotFound.tsx:47-53` | `web/tests/copy/recovery-copy.test.ts` — *"the backend really does answer 404 for an ownership mismatch"* (reads the real `_check_ownership` in `src/api/routes.py` and asserts 404, not 403), *"names both causes"*, *"claims neither: never 'deleted', never 'no permission'"*; `web/tests/copy/forbidden.test.ts` | Package (H8) |
| 10 | `node_completed.state_delta` has no schema — scalars only, unfixed node vocabulary | **Opaque pass-through; unknown keys tolerated** (H11) | `web/lib/job/machine.ts:111-116` `readStateDelta` — no filtering; typed `Record<string, unknown>`; the spine deliberately reads none of it | `web/tests/diagnostics/ring.test.ts` — *"passes unknown event names and unknown state_delta keys through (H11)"*; `web/tests/patterns/TraceSpine.test.tsx` — *"nothing reads state_delta"*; `web/tests/contract/sse.test.ts` | Package (H11) |
| 11 | `hitl_bypass` is accepted from any caller and the proxy would forward it | **Never exposed**, with test-enforced absence (H12) | Retained only in the typed client (`web/lib/api/models.ts:116`, `web/lib/api/client.ts:185`); **no UI module references it** | `web/tests/api.test.ts` — *"is referenced by no module outside `lib/api`"* (walks `app/`, `components/`, `lib/`, `tests/`), *"is never sent unless a caller opts in"*; `web/tests/features/QueryComposer.test.tsx` — *"offers no control that would set it"* | **Named ruling** — D-010 r5 |
| 12 | The web container healthcheck proved only Next `/`, so a misconfigured `API_INTERNAL_BASE` yielded a *healthy* container serving a broken app | **Probe `/api/healthz`, require HTTP 200, do *not* fail on `status: degraded`** | `web/scripts/healthcheck.mjs` — `DEFAULT_URL = …/api/healthz`, `HEALTHY_STATUS = 200`, exit code keyed on the status code alone; `status`/`dependencies` are parsed, reported, and never gate. Wired at `web/Dockerfile:59` and `docker-compose.yml:150-155` | `web/tests/healthcheck.test.ts` — *"exits 0 on a healthy 200"*, *"exits non-zero on the 503 a misconfigured `API_INTERNAL_BASE` produces"*, *"distinguishes a degraded 200 from a healthy 200, and fails neither"*, *"is what Compose probes too, so the two cannot drift"* (reads the real Dockerfile and compose file). Green on the wire in [`ci/web-image.log`](ci/web-image.log) | **Named ruling** — D-010 r10 |

**Items 7 and 12 are the two §11 singled out as wanting an explicit human
answer. Both were answered under the D-010 delegation and both shipped exactly
as ruled** — item 7 cites D-010 ruling 2 in the component's own header comment;
item 12 implements the proposed probe verbatim, degraded carve-out included.

---

## The one row whose pin is weaker than its claim

**Item 1.** The *forwarding* half is pinned — `apiProxyRoute.test.ts` sends
`last-event-id: "six"` and asserts it reaches upstream. The *reserved, unused*
half is provable only from absence: no client module sets the header, and two
tests assert that no backlog or `Last-Event-ID` resume contract exists
(`contract/sse.test.ts`'s reconnect-gap test says in as many words *"if a
backlog or Last-Event-ID contract ever appears, this fails"*, and
`job/checkpoint.test.ts` pins that every open resets the checkpoint to
unknown). But **no test is named for the reservation and no comment on
`route.ts:50` marks the entry as reserved.** The ruling lives outside the code,
in [`DECISIONS.md` D-010 r15](../../DECISIONS.md).

That is a real, small gap between a ruling and its enforcement: a future reader
deleting the allowlist entry, or a future client setting the header, would take
nothing red. It is recorded as **RR-14** in
[`residual-risks.md`](residual-risks.md) rather than fixed here — WO-33 fixes
nothing.

---

## One stale reference, for the record

§11 item 2 cites `web/lib/useResearchStream.ts:59-66`. **That file was deleted
by [WO-31](https://github.com/kudratsingh/arxiv-research-agent/pull/114)**; the
behaviour lives in `web/lib/job/useJobStream.ts`, whose header records the
deletion. The architecture document is a Gate 2 artifact and is not edited by
this pack; the pointer is noted so a reader following it does not conclude the
handling is missing.
