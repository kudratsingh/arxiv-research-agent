# 0093. Exercise supervisor action selection in mock arm D

- **Status**: accepted
- **Date**: 2026-09-06
- **Deciders**: agent-capability lane (W14)
- **Follows**: [ADR 0080](0080-mock-mode-covers-the-whole-research-graph.md)

## Context

P0-WO11 made every supervisor mock run structurally model-free, but its
router always returned the fixed pipeline's next action. That preserved
the old route while leaving the supervisor's real action space untested:
an arm-D campaign enabled verification yet no arm-D episode selected it.
The 300-episode mock matrix therefore proved graph completion, but not a
non-trivial supervisor decision.

Replacing the mock route globally would move existing goldens and the
scripted research tier. Asking a model would violate the mock campaign's
zero-cost and zero-provider guarantees.

## Decision

Add a typed `mock_supervisor_router` setting with two policies:

- `fixed_order` is the default and retains `_default_next_action`
  byte-for-byte; and
- `state_aware` deterministically chooses from the enabled real actions.

The first state-aware rule selects `verify` when the fixed route would
critique, a draft and evidence exist, verification is enabled, and no
verifier outcome has been recorded. Prerequisites and critic-directed
revisions remain owned by the fixed route. The mock verifier records its
outcome, so the next decision proceeds to critique and verification runs
exactly once.

Arm D explicitly selects `state_aware` in the campaign arm table. Other
callers retain `fixed_order`. Both mock policies remain below the existing
loop and cost short-circuits and above prompt construction, so neither can
bypass a stop nor initialize a provider.

## Consequences

- Every arm-D episode in the 20 x 3 x 5 mock campaign traverses the real
  verifier node once, while the matrix remains 300 completed at `$0.000000`
  with zero model/provider calls.
- The default mock route, graph goldens, and scripted research tier remain
  byte-identical.
- The policy is deterministic and intentionally small. Additional mock
  decisions require explicit state predicates and tests rather than an
  imitation judge.
