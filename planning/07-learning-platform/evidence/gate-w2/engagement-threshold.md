# Gate W2 engagement threshold pre-commitment

Status: **PENDING OWNER RATIFICATION — no pilots may onboard from this file**

Prepared: 2026-09-01  
Ratified: _pending_  
Owner sign-off: _pending_  
First pilot onboarding: _none; WO-W17 is blocked_

## SR-10, verbatim

> Tests A1 on the surviving differentiator (do invited users return in week 2
> without being nudged — a 7-day-return proxy against 00 §6.1's ≥40% target),
> A4 with real measured sessions, and A2's surviving-slice hypothesis.
> Pre-commit the threshold before the pilot, per 03's own OD-12 discipline.

Observation window: **14 days**. “Without being nudged” is structural: Phase W
has no notification channel.

## Proposed decision for W-OD-6

- Proposed threshold: **7-day return ≥40%**.
- Metric implementation: `src/learning/engagement.py`.
- Denominator: principals whose first completed session leaves at least seven
  observable days inside the 14-day window.
- Numerator: those eligible principals with a completed session on day 7 or
  later after their first completed session.
- Small-N warning: with no more than five pilots, one person is at least 20
  percentage points. The evidence report always states the denominator.

This is a prepared approval record, not approval. WO-W17 stays blocked until
the owner explicitly ratifies W-OD-6 and this file is updated with a date and
sign-off that precede every onboarding date.
