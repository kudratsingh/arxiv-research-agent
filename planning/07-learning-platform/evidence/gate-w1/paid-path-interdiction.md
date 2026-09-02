# Paid-path interdiction for session routes

Gate W1's row:

> Paid path structurally interdicted for session routes | interceptor proof | W13

**Resolved.** The artifact is
[`artifacts/research-post-count.txt`](artifacts/research-post-count.txt), copied
byte-for-byte out of the `web-e2e-33630982183` artifact of CI run
[33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183)
(attempt 2 — the green one) on `3ccb650`. It is written by
`web/e2e/support/paid-path.ts::expectSessionExactly` during the chromium
project.

---

## 1. What the file says

Three session rows, and a `mode=` column that is itself part of the evidence.

```
# chromium	a session started from the path view runs, survives a reload, and closes	[mock-mode] guided-session pass-through armed: overlay=e2e/support/compose.e2e.yml USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled runtime=verified (arxiv-wo21-app)
PASS	chromium	guided read, start to close, mock-mode pass-through	expected_session_creates=1	POST /api/learn/sessions=1	expected_session_turns=2	POST /api/learn/sessions/{id}/turn=2	mode=mock-pass-through
PASS	chromium	session create is fulfilled in-browser	expected_session_creates=1	POST /api/learn/sessions=1	expected_session_turns=0	POST /api/learn/sessions/{id}/turn=0	mode=fulfil
PASS	chromium	guided turn, double-clicked	expected_session_creates=0	POST /api/learn/sessions=0	expected_session_turns=1	POST /api/learn/sessions/{id}/turn=1	mode=fulfil
```

`mode=` is new in WO-W13b and PR
[#150](https://github.com/kudratsingh/arxiv-research-agent/pull/150) argues why
it is not decoration:

> without it a `POST /api/learn/sessions=1` row is ambiguous between "the
> harness answered it" and "it reached the backend", and those are different
> claims.

The file's own header, also in the artifact, states the boundary:

> `POST /api/research` is fulfilled in EVERY mode and has no pass-through: its
> count is 0 on every row above, which is criterion 3's claim.

And every research row in the same file still reads `POST /api/research=1` for
an intentional submission and `0` everywhere else — WO-21 criterion 3
unchanged, ten rows of it.

**Reproduced independently.** The coordinator state-probe of main `3ccb650`,
2026-09-02 — an Opus agent run, not a CI run — brought the stack up on the
merged tree and reports **every row PASS with `runtime=verified`**, the
guided-read row `creates=1 turns=2 mode=mock-pass-through`, and **zero paid
calls**. Same file, same claims, obtained a second way.

## 2. Two claims, and they are different strengths

| Route | Posture | Strength of the claim |
|---|---|---|
| `POST /api/research`, `POST /api/conversations` | **fulfilled in the browser, always.** No pass-through mode exists and PR #150 says *"never will"* | **Structural.** A research run under mock mode is still a run |
| `POST /api/learn/sessions`, `POST /api/learn/sessions/{id}/turn` | **counted, then forwarded**, in exactly one spec, under an asserted precondition | **Conditional**, and the condition is asserted in two places and re-checked on the outcome |

The pass-through exists because the alternative proves nothing. A fulfilled
create starts no graph; a graph that never runs cannot park on
`awaiting_learner`, write a checkpoint, or be resumed — so Gate W1's first row
would be a test asserting against its own fixtures.

`web/e2e/support/mock-mode.ts`'s header is explicit that the precondition is
not the proof:

> **WHAT THIS FILE DOES NOT CLAIM.** It is a precondition, not the proof. The
> proof that the run spent nothing is `llm_calls` on the finished session, read
> back from the API in `session-flow.spec.ts`, plus the unchanged
> `POST /api/research = 0` line in `research-post-count.txt`.

## 3. The A/B control, run rather than asserted

PR #150, "The A/B control for the `USE_MOCK_DATA` pin": same tree, same stack,
the pin commented out of the overlay and the app container recreated —
**312 passed, 1 failed, 3 skipped**. The one failure:

```
Error: refusing to forward a guided-session write: the stack is not in mock mode.
  - .../compose.e2e.yml#services.app.environment: USE_MOCK_DATA is unset, must be true
  - container arxiv-w13b-app: USE_MOCK_DATA is unset, must be true
```

Both halves of the check fired; no other spec moved in either direction.

## 4. What the interceptor does not cover

- **The judge path is never driven end-to-end.** PR #146's Deferred note: *"no
  e2e drives the judge, because the judge needs a model."* The
  `Session/Probe` story renders the shape; nothing exercises the route.
- **The pass-through is a browser-tier decision with no ADR.** Coordinator
  ruling, recorded in the index's Execution record. It is argued at length in
  `web/e2e/support/mock-mode.ts`, `paid-path.ts`'s header,
  `web/e2e/support/compose.e2e.yml` and `web/e2e/README.md` instead.
