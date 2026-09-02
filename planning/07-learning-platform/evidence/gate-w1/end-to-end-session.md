# The end-to-end guided-read session, and the mid-session reload

Gate W1's first two rows:

> Full guided-read session end-to-end on the seeded local stack, disabled key,
> zero paid calls | Playwright run + the no-client-construction test | W03,
> W13, collected by W19
>
> Mid-session reload resumes from checkpoint | Playwright + integration test |
> W03, W13

Both **resolve**. Both were unreachable in a browser until PR
[#150](https://github.com/kudratsingh/arxiv-research-agent/pull/150) merged as
`3ccb650`, six hours before this pack was assembled — see
[`known-gaps.md`](known-gaps.md) §11.

---

## 1. The browser proof

`web/e2e/session-flow.spec.ts` — **2 tests**, both green in CI on `3ccb650`
(run [33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183),
job *web e2e (chromium + axe)*, attempt 2: **264 passed, 52 skipped, 0
failed**). They were green on attempt 1 too, whose job failed for an unrelated
reason — [`known-gaps.md`](known-gaps.md) §7.

| Test | What it drives |
|---|---|
| *"a session started from the path view runs, survives a reload, and closes"* (`:72`) | start from `/learn/paths/[id]` → `awaiting_learner` → learner turn → `page.reload()` → second turn → close |
| *"the start action refuses one entry without disturbing the others"* (`:231`) | the service's own 404, mapped to a sentence, one entry refused, two still offering the action, URL unchanged |

**Corroborated on the merged tree.** The coordinator state-probe of main
`3ccb650`, 2026-09-02 (an Opus agent run, not a CI run) re-ran the whole
chromium project against `3ccb650` itself: **313 passed, 3 skipped, 0 failed**,
with the guided-read row recorded `creates=1 turns=2 mode=mock-pass-through`,
`runtime=verified`, and **zero paid calls**. CI proves the spec green on the
tree the PR was built on; the probe proves it green on the tree that merged.

`web/e2e/session.spec.ts` — **4 tests**, WO-W13's, green beside it:

- *"renders the checkpointed margin, and renders it again after a reload"* (`:64`)
- *"the paper stays the source of record beside the briefing companion"* (`:100`)
- *"one submitted turn is exactly one turn write, and no research write"* (`:115`)
- *"the create route is interdicted too, before any surface issues it"* (`:152`)

**The reload assertion is not self-fulfilling, and both cards say how.** PR
[#146](https://github.com/kudratsingh/arxiv-research-agent/pull/146) quotes its
own earlier draft as the failure it fixed: *"a reload that re-renders a
transcript the test supplied is a test asserting against itself."* On
`3ccb650` the margin the assertion looks for exists **only** in the LangGraph
checkpoint — PR #150: *"`tutor_agent` writes it as a `HumanMessage`;
`_transcript` reads it back out of the snapshot — in no fixture, no SSE frame
and no job row"* — and the session id is *"a 16-hex backend id, not the
harness's."*

## 2. The cost boundary on that run, in three independent places

**(a) The key.** `web/e2e/support/compose.e2e.yml:113` pins
`ANTHROPIC_API_KEY: local-preview-disabled` on the `app` service. It is the
same sentinel every job in `ci.yml` uses.

**(b) Mock mode, asserted before any write is forwarded.**
`web/e2e/support/mock-mode.ts::assertMockModeStack()` reads the overlay's
`services.app.environment` *and*, when a Docker daemon answers, the running
container's environment, and throws with the fix rather than skipping. Its
header states the stronger claim the disabled key alone cannot make:

> Under `USE_MOCK_DATA=true` the session graph makes **no model call at all** —
> `check_in_agent` takes `_fallback_plan` (`src/agents/tutor.py:159`),
> `_tutor_prompts` returns two constants (`:248`), and the assessment agent
> takes its own mock branch (`src/agents/assessment.py:178`). Zero paid calls
> by construction, not by a key that happens to be invalid.

The line it prints is in the CI log and in the report artifact, verbatim:

```
[mock-mode] guided-session pass-through armed: overlay=e2e/support/compose.e2e.yml USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled runtime=verified (arxiv-wo21-app)
```

(run 33630982183, job *web e2e (chromium + axe)*, 12:54:37Z on attempt 2 and
12:45:22Z on attempt 1; also line 33 of
[`artifacts/research-post-count.txt`](artifacts/research-post-count.txt))

**(c) The outcome, read back from the API.** `session-flow.spec.ts:186-188`
asserts on the finished session:

```ts
expect(detail.status).toBe("succeeded");
expect(detail.llm_calls, "a model call was made on the e2e stack").toBe(0);
expect(detail.cost_usd ?? 0).toBe(0);
```

A precondition plus an outcome. PR #150 ran the A/B for (b): with
`USE_MOCK_DATA` commented out of the overlay and the container recreated,
**312 passed, 1 failed, 3 skipped** — the single failure is the pass-through
test refusing, naming both halves of the check, *"and no other spec's result
moved in either direction."*

## 3. The no-client-construction test (WO-W03 c5)

`tests/test_guided_session_graph.py::TestTutorHonesty::test_mock_mode_never_constructs_a_client`
(`:310`) monkeypatches `tutor.call_llm_json` to raise and asserts
`check_in_agent` still returns a plan.

WO-W10 runs the same assertion **at campaign scale**, which is stronger:
`tests/test_simulate_learner.py::TestScriptedTierRunsTheFullSet` (9 tests)
drives all 15 scenarios through the *real* compiled graph with
`src.llm._get_client` monkeypatched to raise. PR
[#145](https://github.com/kudratsingh/arxiv-research-agent/pull/145) records
the mutation check: *"flipping `use_mock_data` to `False` makes it fail with
`AssertionError: Anthropic client constructed in the scripted tier` from
`check_in_agent`."*

## 4. Reload from checkpoint, below the browser

`tests/test_guided_session_graph.py::TestCheckpointReattachment::test_a_new_graph_process_reads_the_parked_transcript`
(`:341`) builds the workflow, streams to the park, closes the checkpointer's
exit stack, builds a **second** workflow, and asserts `after.next`,
`after.values["turn"]` and the message count all match. A new graph process,
not a re-read of the same object.

## 5. The stack the browser evidence runs on — and its one caveat

`compose.e2e.yml` turns the whole flag ladder on
(`ENABLE_API_AUTH`, `ENABLE_LEARNER_PROFILE`, `ENABLE_SESSION_LOOP`, both
stores on Postgres, `USE_MOCK_DATA=true`), and `fixtures/seed.sh` stamps every
`baseline-*` row with the stack's single principal and writes the learner
profile `create_session` requires. PR #146 flags the blast radius in its own
Tradeoffs section, and PR #150 adds the profile.

This is a **harness** configuration, not the shipped default. What it proves is
that the guided read works when its ladder is on. It does not prove anything
about `docker compose up` with no environment at all —
[`known-gaps.md`](known-gaps.md) §3.
