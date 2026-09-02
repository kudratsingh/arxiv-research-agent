# Gate W2 pilot record

Status: **NO PILOT ONBOARDED — WO-W17 is blocked on W-OD-5**

Prepared: 2026-09-02 (WO-W17, the no-cost half)
W-OD-5 decided: _pending_
W-OD-6 ratified: _pending_ — see [`engagement-threshold.md`](engagement-threshold.md)
First onboarding: _none_

This file is the **register**. It is the only mapping from a `key_id` to a
human that exists anywhere in this system, and
[`docs/runbooks/pilot.md`](../../../../docs/runbooks/pilot.md) §1's
never-reassign rule is unenforceable without it. WO-W20 authors the Gate W2
index; this is a producing file that the index will cite.

Nothing below may be filled in before the owner records the W-OD-5 and W-OD-6
approvals in §1. The [standing cost lock](../../STATUS.md) applies: no pilot
invitation without a fresh explicit owner approval.

---

## 1. Approvals, recorded before anything else

| Decision | What it covers | Value | Date | By |
|---|---|---|---|---|
| **W-OD-6** | ≥40% 7-day return, 14-day window, ratified **before** the first onboarding | _pending_ | _pending_ | _pending_ |
| **W-OD-5** — cohort | The ≤5 invitee names | _pending_ | _pending_ | _pending_ |
| **W-OD-5** — deployment | The DEPLOY unblock, or an owner-hosted box | _pending_ | _pending_ | _pending_ |
| **W-OD-5** — inference budget | The number the owner is willing to lose | _pending_ | _pending_ | _pending_ |
| **W-OD-5** — at-cap behaviour | `refuse` or `degraded_close` (`LEARNING_SESSION_COST_CAP_BEHAVIOR`) | _pending_ | _pending_ | _pending_ |
| **W-OD-5** — research rights | Whether pilot keys keep `POST /research`, and by which of runbook §9's three options | _pending_ | _pending_ | _pending_ |

W-OD-6's date must **precede** every onboarding date in §3. That ordering is
the whole of the WO-W18 → WO-W17 dependency edge: a threshold ratified after
the data exists is a negotiation, not a commitment (03 §8's OD-12 discipline).

## 2. SR-09 arithmetic, as approved

Copied from [`docs/runbooks/pilot.md`](../../../../docs/runbooks/pilot.md) §3
with W-OD-5's numbers substituted. Re-checked in the Gate W2 report.

```
worst_case_usd  =  N  ×  L  ×  24 × D  ×  C_max
```

| Term | Value | Where it is set |
|---|---|---|
| `N` — pilots | _pending_ | The list in §3 |
| `L` — accepted submissions per principal per hour | _pending_ | `API_KEY_HOURLY_LIMIT` |
| `D` — window in days | 14 | SR-10, fixed |
| `C_session` | _pending_ | `LEARNING_SESSION_MAX_COST_USD` |
| `C_research` | _pending_ | `MAX_COST_USD`, or 0 if research rights are withheld |
| **`worst_case_usd`** | _pending_ | Computed |
| **Approved budget** | _pending_ | W-OD-5 |
| Provider account limit | _pending_ | Set on the Anthropic account, independently |

The bound holds only while the cohort is ≤5. SR-09: any cohort beyond five,
any public opening, or any scheduled (system-initiated) work re-triggers the
MT-01 F4 prerequisite — that is a different decision, not a bigger pilot. The
web tier refuses a sixth entry in `PILOT_PRINCIPAL_MAP` rather than serving
one.

## 3. The cohort

**One row per pilot, written at the moment they are onboarded, never
retrospectively.** The 14-day clock is per pilot and starts on *their*
onboarding date, so a cohort onboarded over four days has four different
day-14s. WO-W20's report cannot reconstruct these afterwards.

| # | `key_id` | Edge username | Human (name / contact) | Onboarded (UTC date) | Day 7 | Day 14 | Revoked | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | — | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 4 | | | | | | | | |
| 5 | | | | | | | | |

Rules this table exists to enforce (runbook §1):

- A `key_id` appears in this table **once, ever**. A revoked row is never
  reused, edited into a different human, or renamed. Add a new row instead.
- The naming convention is `pilot-<given-name>-<YYYY-MM>`, so reuse is
  impossible by construction rather than by discipline.
- "Onboarded" is the date the pilot first received working credentials, not
  the date they were decided on and not the date they first logged in.

## 4. Per-pilot onboarding checklist

Tick per pilot; runbook §4 is the procedure.

| Step | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Backend key written to `pilot-keys.json` | | | | | |
| `PILOT_PRINCIPAL_MAP` entry added, `web` restarted | | | | | |
| Edge line written to `pilot-users.caddy`, edge reloaded | | | | | |
| Smoke test: authenticated 200, unauthenticated 401 | | | | | |
| `pilot_principal` log line shows `outcome: resolved` | | | | | |
| Onboarding note sent (runbook §8) | | | | | |
| Row added to §3 with the date | | | | | |

## 5. Revocations

| `key_id` | Revoked (UTC date) | Reason | Keystore entry deleted | Edge line deleted | Map entry deleted | Data erased? |
|---|---|---|---|---|---|---|
| | | | | | | |

Deleting the keystore entry is the revocation; the other two are cleanup
(runbook §5). Data erasure is a separate, explicit act and the pilot is told
which of the two happened.

## 6. Blocking issue carried from WO-W17

**The shell still says the workspace is shared.** `web/lib/copy/threads.ts`
renders "Shared workspace — Everyone with access to this deployment sees these
threads. There are no separate accounts." Under `PILOT_EDGE_AUTH=on` neither
clause is true. WO-W17 did not own `web/lib/copy/**` and left the string
alone; the runbook's onboarding note tells pilots to ignore it, which is a
mitigation and not a fix.

**This must be resolved before the first invitation.** It is a false statement
about data separation, shown to the people the separation is for. Record the
resolution here:

| Resolved by | Date | How |
|---|---|---|
| _pending_ | _pending_ | _pending_ |
