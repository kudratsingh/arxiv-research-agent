"""Deterministic policy decisions the research graph makes without a model.

A policy here is a pure function from `ResearchState` to a named,
bounded action. The distinction this package exists to hold is the one
`docs/agent-engineering/02-target-architecture.md` §5 draws when it says
"reflect again is not a recovery policy": a failed check has to return a
*named* action a router can dispatch and an evaluation can count, and
asking a model which repair to attempt would make the recovery itself
unmeasurable — the same input could produce a different action on every
run, and a campaign could not attribute an outcome to the policy.

Nothing in this package calls an LLM, reads settings, or performs I/O.
That is what makes each decision unit-testable row by row (ADR 0076) and
what keeps the repair path free of a second, hidden model call the cost
ceiling would have to bound.
"""
