# Proposals

**Pre-ADR documents for work that has not been approved.**

An [ADR](../decisions/README.md) records a decision that was *made* —
it is written before or alongside the code that implements it, and the
code follows. A proposal is the step before that: it states a problem,
lays out the real options with their costs, recommends one, and then
stops. Nothing in this directory is a commitment, and nothing here
describes behavior that exists on `main`.

The rules:

- **Every proposal is labelled `PROPOSED` at the top.** If you are
  reading one and cannot immediately tell whether it is approved,
  the proposal is broken — say so.
- **A proposal never authorizes an implementation.** It ends at a
  human decision point. Approval is recorded elsewhere (a gate answer,
  an issue, a decision log), and the implementation lands with its own
  ADR.
- **Claims are cited.** Proposals argue about the system as it is, so
  assertions about current behavior carry `path:line` references or
  ADR links. An uncited claim about `main` is a bug in the proposal.
- **Options are honest.** The recommendation section is worthless if
  the rejected options are strawmen. Effort, risk, and recurring cost
  are stated even when they make the recommendation look worse.
- **Superseded proposals stay.** When a proposal is accepted, add a
  line at the top pointing at the ADR that accepted it. When one is
  rejected, say so and why. Deleting the losing argument destroys the
  reason the winning one won.

## Index

- [`multi-tenancy.md`](multi-tenancy.md) — **PROPOSED** — end-user
  multi-tenancy for browser users (workstream MT-01). Raised by
  [D-009](../revamp/DECISIONS.md#d-009--gate-1-human-decisions) at
  Gate 1 of the frontend revamp; deliberately outside that revamp's
  frozen-backend boundary.
