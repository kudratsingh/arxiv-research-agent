# RC-03 — the legacy-removal equivalence table

**Why this file exists.** [WO-31](../../06-WORK-ORDERS.md#wo-31--legacy-removal-and-ratchet)
criterion 2 requires that "**the deletion PR shows a test-count and behaviour
equivalence table** — each retired `useResearchStream` test mapped to its
replacement in `web/tests/job/`. A retired test with no replacement blocks the
PR." WO-31 produced it, in full, **in the body of PR
[#114](https://github.com/kudratsingh/arxiv-research-agent/pull/114)** — and a
PR body is not a repository artifact. [WO-32](../../06-WORK-ORDERS.md#wo-32--adrs-and-documentation-refresh)
flagged the gap while refreshing the docs; [WO-33](../../06-WORK-ORDERS.md#wo-33--gate-4-evidence-pack-and-residual-risks)
closes it by committing the table into the Gate 4 pack, where the twelve
deletions it justifies can still be audited after the PR body has scrolled out
of anyone’s memory.

| | |
|---|---|
| Source | PR [#114](https://github.com/kudratsingh/arxiv-research-agent/pull/114), *“WO-31: legacy removal, the equivalence table, and the ratchet”* |
| Merged | 2026-08-29T16:02:46Z, as `cf61462` |
| Branch | `chore/wo-31-legacy-removal` |
| Measured on | `main` at `d3460a7` (PR #111), which the branch was rebased onto |

**Everything between the two rules below is PR #114’s body, verbatim.** It is
reproduced without edit — headings, wording, emphasis and all — so that this
file is a transcript rather than a retelling. WO-33 adds nothing to it and
corrects nothing in it; the only WO-33 content in this file is the header above
and the two notes after the closing rule.

---

## Criterion 2 — the RC-03 equivalence table

**Verdict: no blocker. All 10 retired `useResearchStream` tests map.** 69 retired `it(...)` tests were mapped in total (the 10 adapter tests RC-03 names, plus the 56 legacy component tests and the 3 shim tests that go with the deletion). Assertion bodies were read on both sides — a title match was not accepted as a mapping.

### `tests/job/adapter.test.ts` — retired 10 → 28 replacements

| Retired test | Replacement | Same claim? |
|---|---|---|
| `the legacy surface is unchanged › attaches stream-first and synchronously, as its callers pin` | `tests/support/msw.test.tsx :: the harness composes … › drives useJobStream from live_success to the settled JobDetail`; inverted at `tests/job/attach.test.ts :: the request order › issues GET /research/{id} before constructing the EventSource` | **Retired by design.** The claim was ABOUT the adapter's opt-out from the machine's GET-first contract (§4.3); the retired file says so itself. See the residual on `attachMode` below. |
| `… › settles from GET /research/{id}, not from the terminal frame` | `tests/job/stream.test.ts :: live_success end to end › settles from the read, closes the stream, and opens no second one`; `tests/job/terminal.test.ts :: terminal frames are signals … › displays the settled JobDetail, whichever shape signalled it`; `… › keeps no value from the frame, not even the ones JobDetail lacks` | **Same claim**, strengthened — six terminal payload shapes instead of one. |
| `… › keeps the composer usable when the stream fails permanently` | `tests/job/stream.test.ts :: live_success end to end › a permanently failed connection is the unavailable dead end`; `tests/job/attach.test.ts :: a 404 is a clean 'no longer available' › leaves the surface usable — a new question is a new run`; `tests/job/machine.test.ts :: … › unavailable + submit_requested → submitting` | **Equivalent, different mechanism.** Two named differences: the sentence no longer names the job id or guesses "expired" (H8 — `attach.test.ts` asserts it must *not* guess); and the state is `unavailable`, not `idle`, its usability pinned by the transition table rather than a status string. |
| `… › narrates a transient drop as a stream_note event` | `tests/job/stream.test.ts :: live_success end to end › narrates a transient drop and never unlocks mid-run` | **Same claim.** |
| `… › exposes a replayed plan and clears it on review` | expose: `tests/job/stream.test.ts :: plan_ready is idempotent › a second frame changes nothing but the log`; clear: `… :: resolving the review pause › a 200 means 'wait', not 'resumed'`; plus `tests/job/attach.test.ts :: … › renders a pending_review plan from JobDetail, with no SSE frame` | **Same claim**, split into its two halves and strengthened. |
| `… › reports a settling read that failed, with its status code` | `tests/job/machine.test.ts :: … › reconciling + detail_unreachable → settled`; `tests/job/terminal.test.ts :: … › success signalled, settling read never came back → "finished"`; `tests/diagnostics/ring.test.ts :: … › records a failure as its normalized kind, plus the raw string` | **Equivalent, different mechanism.** The composed `fetch result failed (502): …` is gone; the status lives in `state.failureStatus`/`failureMessage` and routes to the diagnostics ring, while the surface gets the honest `"finished"` (H9). |
| `… › reports a rejected review, with its status code` | `tests/job/machine.test.ts :: … › awaiting_review + review_rejected → awaiting_review`; `tests/plan/review.test.tsx :: criterion 4 — a 422 that still arrives lands on the row › marks the field FastAPI named, and nothing else`; `… › leaves the surface usable — one attempt, still editable` | **Equivalent, different mechanism.** A page-level string became FastAPI's `loc` mapped onto the offending row. "The pause is still the pause" survives as the transition-table row plus "still editable". |
| `… › reports a review with no job the way it always did` | `tests/job/machine.test.ts :: … › idle + review_requested is inert`, and the eight other non-`awaiting_review` phases, exhaustively | **Equivalent, different mechanism.** The string `"no active job to review"` became a deliberate no-op, pinned exhaustively rather than by one defensive assertion. See coverage note C1. |
| `what the adapter deliberately withholds › handles stream_timeout without surfacing it as an event` | `tests/job/stream.test.ts :: stream_timeout reopens the stream immediately › opens a new connection in the same tick, with no timer to wait out` (+3 siblings) | **No replacement needed — the claim was ABOUT the retired module's own compatibility shim.** The withholding existed only because `EventLog.tsx:10` keyed an exhaustive `Record<SseEventName, string>` off the legacy union. The replacement additionally asserts the frame *is* now logged — the deliberate inversion. |
| `… › keeps every name the legacy union does carry` | `tests/job/stream.test.ts :: unknown names and unknown keys are tolerated › ignores event names the backend does not emit today`; `… › passes unknown state_delta keys through …`; `tests/contract/events.test.ts :: … › keeps the legacy union exactly the server set minus stream_timeout, plus the client notes` | **Same claim**, and the union is now pinned against the contract rather than against the hook. |

### The legacy component tests — retired 56 → 93 replacements

| Retired file | Retired → replacements | Home of the replacements | Unmapped |
|---|---|---|---|
| `ConversationThread.test.tsx` | 12 → 19 | `tests/features/routeComposition.test.tsx`, `tests/shell/conversationRoute.test.tsx`, `tests/job/*` | none |
| `QueryForm.test.tsx` | 7 → 11 | `tests/features/{QueryComposer,LandingComposer}.test.tsx`, `tests/primitives/{Textarea,Field,Button}.test.tsx` | none |
| `ConversationSidebar.test.tsx` | 7 → 12 | `tests/threads/{list,rail,bridge,confirmDialog}.test.tsx`, `tests/queries/conversations.test.ts` | none |
| `EventLog.test.tsx` | 6 → 9 | `tests/diagnostics/Diagnostics.test.tsx`, `tests/patterns/{TraceSpine,spineState}`, `tests/copy/errorType.test.ts` | none |
| `PlanReview.test.tsx` | 10 → 15 | `tests/plan/{PlanEditor,review,schema}.test.*` | **B1 — closed in this PR** |
| `JobSummary.test.tsx` | 3 → 9 | `tests/patterns/MetricsStrip.test.tsx`, `tests/copy/metrics-copy.test.ts` | none |
| `ReportView.test.tsx` | 4 → 8 | `tests/patterns/{ReportReader,SectionRail}.test.tsx`, `tests/copy/report-copy.test.ts` | none |
| `ExportDropdown.test.tsx` | 7 → 10 (2 at the e2e tier) | `tests/patterns/ExportDisclosure.test.tsx`, `tests/primitives/{Disclosure,Menu}.test.tsx`, `e2e/export.spec.ts` | **B2 + C8 — closed in this PR** |
| `api.test.ts :: the M0 compatibility shim` | 3 → 4 | rewritten in place as `` `@/lib/api` resolves to the real surface, with the shim deleted `` | none |

### Retired by design — no replacement needed, with the reason

- **`adapter › handles stream_timeout without surfacing it`** — the claim was about the adapter's own compatibility with `EventLog`'s exhaustive label record. Underlying behaviour pinned in `tests/job/stream.test.ts`.
- **`adapter › attaches stream-first and synchronously`** — the claim was about the adapter's opt-out from the GET-first contract.
- **`QueryForm › shows the job id when provided`** — 03 §1.4 enumerates eight composer slots and none is a job id; the set is asserted exhaustively by `QueryComposer.test.tsx :: criterion 1 — 03 §1.4 verbatim › parsed a block with every slot the brief prints`. The id now lives in `?job=`.
- **`ConversationSidebar › creates a new conversation and navigates to it`** — thread creation moved onto the landing composer, so a thread is never created without a question in it; a rail-created bare thread would spend a `routes.py:545` rate-limit slot on an empty row.
- **`ConversationSidebar › highlights the active conversation`** (colour-class half) — `expect(link.className).toMatch(/bg-blue-100|bg-blue-950/)` could not survive the token gate; the behaviour is now `aria-current="page"`.
- **`EventLog › formats job_completed elapsed as one decimal`** — a diagnostics log must print wire values verbatim; the 1-dp convention survives where a duration is actually presented (`MetricsStrip.test.tsx :: formats › prints quality to two and duration to one`).
- **`api.test.ts › re-exports every name 05-MIGRATION.md §1.1 pins`** — the claim's subject no longer exists; its successor pins the resolution directly.

### Two affordances that were removed by design but **asserted nowhere** — both closed here

Neither is a criterion-2 blocker (the behaviour was deliberately retired by an already-merged work order, not orphaned), but in both cases *nothing recorded the decision*, so a later PR could have reintroduced the control with no test noticing. Three small assertions were added rather than leaving the equivalence table with an asterisk:

- **B1 — `PlanReview › Reset restores the original plan after edits`.** WO-17's control set is one relabelling primary plus Cancel; Reset is not in it, and unlike the two retired approve buttons its absence was unpinned. → `tests/plan/PlanEditor.test.tsx › has no Reset control — the third legacy button, retired with the other two`.
- **B2 — `ExportDropdown › closes the menu when an item is clicked`.** RC-09 replaced the menu with a disclosure of `<a download>` links, which has no activation-dismisses-the-container contract — and taking the Markdown copy then the PDF is one intent. The resulting behaviour was unpinned *in both directions*. → `tests/patterns/ExportDisclosure.test.tsx › stays open when a format is taken, so a second one needs no re-open`.
- **C8 — the export href's single-path-segment claim.** The retired test split on `/` and asserted `["", "api", "research", "a%20b%2F1", "export"]`; the surviving space-only case does not reach it, and a `/` in the id would silently become a path separator with the same-origin test still green. → `tests/patterns/ExportDisclosure.test.tsx › keeps the job id in one path segment, whatever it contains`.

### Coverage notes — narrowings that are real, none a blocker

- **C1** `useJobStream.ts`'s `if (jobId === null) return;` guard in `review()` has no direct test; the machine-level no-op is pinned exhaustively.
- **C2** No surviving test renders the job machine inside `<StrictMode>`; the guard it exercised (`useJobStream.ts:530-533`) is pinned by repeated `attach()` calls instead.
- **C3** `ActiveRunPanel`'s `unavailable` sentence is covered by the Storybook project's `play` function, not by a vitest `it`.
- **C4** The composer's trim is asserted on the ⌘/Ctrl+Enter path only, not the click path; both funnel through one `trySubmit()`.
- **C5** No test asserts a *mixed* list's revise payload has shed a blank row; the rule is proven through the approve branch.
- **C6** No test types into a newly added row and then asserts that row in the submitted plan; the composition holds by transitivity across two files.
- **C7** Cancel's state during an in-flight review is unpinned (`PlanEditorFields.tsx:412` still hard-disables it).
- **C9** In the rewritten shim block `shim` and `surface` now resolve to the same module, so the binding identity check is `x === x`. What carries weight is `expect(shim).toHaveProperty(name)` — the tree's only nine-name export-surface pin — plus the new `is not a file:` sibling.

---


## Two notes from WO-33

**1. The verdict, restated so criterion 2 is readable without arithmetic.**
RC-03’s blocker condition is *a retired test with no replacement*. The table
above reports **69 retired `it(...)` tests mapped** — the 10 `tests/job/
adapter.test.ts` tests RC-03 names by hand, plus the 56 legacy component tests
and the 3 shim tests that had to go with them — against **121 replacements**
(28 + 93). Seven retirements have **no** replacement and each carries a written
reason: in every one of the seven, the claim was about the retired module’s own
compatibility shim or about an affordance a merged work order had already
removed by design. Two of those (B1, B2) plus one narrowing (C8) were judged
unpinned-in-both-directions and were closed with three new assertions **inside
PR #114 itself**, rather than left as an asterisk. **No retired test was
dropped silently**, which is the property criterion 2 exists to establish.

**2. What is verifiable from this repository, and what is not.**
The right-hand column names live test titles in `web/tests/`, so a reader can
check every mapping directly — `npx vitest run -t "<title>"` from `web/`. The
left-hand column names **files that no longer exist**; they are recoverable
only from history (`git show d3460a7:web/tests/job/adapter.test.ts`,
`git show d3460a7:web/tests/ConversationThread.test.tsx`, and so on). WO-31’s
own risk note verified the whole deletion is reversible:
`git revert --no-commit d3460a7..HEAD` applies cleanly and leaves
`git diff d3460a7` **empty**.

The nine coverage narrowings (C1–C9) are real and are **not** residual risks in
the [`residual-risks.md`](residual-risks.md) sense — they are places where a
behaviour is pinned indirectly rather than not at all, and each says how. They
are reproduced here so the narrowing survives with the table that created it.

One residual **is** carried forward from this PR:
`attachMode: "stream-first"` outlived the adapter it existed for. It is
**RR-04** in [`residual-risks.md`](residual-risks.md).
