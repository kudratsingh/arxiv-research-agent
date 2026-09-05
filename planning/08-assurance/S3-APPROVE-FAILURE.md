# WO-S3 — a failed plan approval must say so

Status: **DELIVERED** (branch `assurance/wo-s3-approve-failure`)

One of the S-series product bugs the frontend presentability survey returned,
authorised by the owner through ruling R6. This file records S3 only: the
S-series index, and S2's own record, belong to the coordinator and to the S2
branch respectively, and are deliberately not written here so that two
branches cannot collide on one file.

## The defect

`POST /research/{job_id}/review` is the request that commits money, and
**every way it could fail rendered nothing at all.**

The user presses `Approve plan`. The request is rate-limited, or 500s, or is
refused as invalid. The surface does not move. Nothing appears. A rate limit,
a server fault and a click that missed the button are indistinguishable — at
the one moment in the product where the user is authorising spend.

Two adjacent findings in the same flow:

- `PLAN.cancelHint` — *"Cancelling here is the only way to stop this run. Once
  it is approved there is no way to stop it."* — was written by WO-17, is
  asserted by `web/tests/copy/plan-copy.test.ts` against its `REVIEW`
  counterpart, and was rendered by **no component**. Users approved an
  unstoppable run without being told it was unstoppable.
- A 409 (`job_not_awaiting_review`) took the editor off screen entirely and
  put nothing in its place, and a 422 on the review reached no row: the panel
  passed neither `failure` nor `issues` to the editor.

## Root cause

Not one bug; three surfaces each doing something defensible.

1. `web/lib/job/machine.ts` records a failed review (`review_rejected`) and
   leaves the phase alone. **That is correct** — the server never heard the
   decision, so the run really is still `pending_review` and the user's edits
   are still the thing on screen. Moving to a terminal phase would have
   unmounted the editor and thrown the working copy away.
2. `web/components/features/ActiveRunPanel.tsx` gated its only banner on
   `phase === "submit_failed"` — a phase a review failure never produces. So
   the panel asked the one question that has no answer for this failure. The
   question that does is `failureSource === "review"`.
3. `adoptDetail` clears every failure field on any successful read. Sound in
   general; wrong for this one case. A `GET /research/{id}` answering
   `pending_review` is proof the decision did **not** take effect, not proof
   it was never made — so the liveness poll erased a rate-limit explanation
   twenty seconds after it appeared, and the 409's own account of itself was
   erased by the refetch the 409 itself triggers.

`planStatusOf`'s `stale` branch had been written and was unreachable for the
same reason: nothing kept the surface mounted long enough to render it.

## The fix

- The plan editor takes a `failure` prop and states it, branching on
  `ApiFailure.kind` — never on a message string. Rate-limited names the wait
  and the hourly ceiling from `Retry-After` and the body; a 500 says transient
  and offers a retry the user performs; 502 and 503 are told apart because
  their remedies differ; a 409 keeps the existing `stale` banner and its
  re-read control. `role="alert"` is guarded by severity, because
  `StatusBanner` throws on an `info` one.
- A 422 that names fields still lands on those rows and raises no page-level
  banner (WO-17 criterion 4 stands). A 422 that names none now speaks, because
  it has no row to land on and that was where the silence was.
- The editor stays mounted through a failed review, including the 409's trip
  through `attaching`.
- `adoptDetail` preserves a `review`-sourced failure across a read that finds
  the run *still awaiting review* — **except a 409**. A conflict is a claim
  about the run's state, and a read answering `pending_review` contradicts it
  outright; the read is newer and is the authority on that question, so the
  surface comes back actionable rather than stranded behind a banner. That is
  `routes.py:261-264`'s own answer to a conflict and is what
  `e2e/slice.spec.ts` step 3 already asserted in a browser. Every other kind
  is a claim about the *request*, which the read says nothing about, so it
  stands. Everything that genuinely resolves a preserved failure still clears
  it: the next decision, a run that has moved on, a reset.
- `PLAN.cancelHint` is rendered above the actions row and describes the
  primary control, since approving is the act it warns about.

## Evidence

`web/tests/features/approveFailure.test.tsx` drives the real panel, the real
provider, the real machine and the real request layer over MSW, using the
recorded envelopes in `web/contract/fixtures/error.*.json`. **Thirteen of its
fourteen cases fail on `main`**; the fourteenth is the success path, which is
asserted unchanged. `web/tests/plan/PlanEditor.test.tsx` covers the surface
contract per failure kind, `web/tests/job/machine.test.ts` covers the reducer
change, and three `Patterns/PlanEditor` stories put the states through the
axe gate at every width and in both themes.

The browser evidence for the original finding — the 110 PNGs from the
Playwright harness — belongs to the survey branch and is not duplicated here.

## Still open after this work order

- A successful approval unmounts the editor immediately (`review_accepted`
  sets `plan: null`) and the spine carries the pause from there. That is
  WO-20's existing behaviour, is asserted so it cannot drift, and is not this
  work order's to change.
- `staleCause: "hitl_timeout"` is wired from the refetched run's `error_type`,
  but a run that timed out is terminal, so the editor unmounts and the spine
  states the outcome instead. The prop is correct; the window in which it
  renders is narrow.
- The 409's `stale` banner still replaces the fields rather than sitting above
  them, and it lasts only as long as the re-read it triggers. That is WO-17's
  deliberate design for a plan that is no longer reviewable, and
  `e2e/slice.spec.ts` step 3 pins the end state; neither was reopened here.
- **Two darwin-only screenshot sets need one regeneration between them.**
  `plan-review` is one of the twelve `@visual` states and is also
  `docs/images/workbench-plan-review.png`, which WO-D2 (PR 209) has just bound
  as a `readme` snapshot — and that surface now carries the irreversibility
  hint. Neither gate runs in CI: both sets are darwin-only and both suites
  skip a platform with no committed set. S2 is changing the layout of the same
  surface, so the honest sequence is one regeneration after both S2 and S3
  land — `npm run e2e:visual:update` plus the `readme` project — rather than
  two that invalidate each other.
