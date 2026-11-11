# Coverage authority v10 — offline verification

Application `3c94e566228e6dc536518887e93c41d8832f8478` from clean publication
e5fd2264, isolated worktree `/private/tmp/arxiv-agent-eng-workspace-coverage-authority`.
[Runbook/proposal](../../COVERAGE-AUTHORITY.md), [packet](packet.json.gz),
[bindings](BINDINGS.json), [immutable regression](REGRESSION.json),
[synthetic successor](SYNTHETIC-SUCCESSOR.json), [protected replay](REPLAY-EVIDENCE.json).

The archived wire schema is JSON-equal to its exported v9
schema. Original v9 semantic rejection remains request_part_claim_binding_mismatch.
The v10 local/wire models forbid part_ids; only the separately synthetic deletion
fixture derives c4/c5 as p2 answers and p3 context. Mapping never establishes
whole-claim support, relevance, scientific quality or human evidence.

Focused command: tests/test_workspace_coverage_authority.py,
test_workspace_coverage_authority_runner.py, test_workspace_request_boundary.py,
test_workspace_coverage_adapter.py, test_workspace_coverage_shapes_runner.py:
**63 passed in96.47s**. Unit v10 controls18passed in1.23s; preceding old/new wire
controls49passed in1.50s. The first sandboxed unit invocation passed but mirakuru's
atexit process inventory reported sandbox PermissionError; subsequent checks use
normal permitted subprocess/loopback access, not a changed test/timeout.

Ruff all source/tests PASS. Mypy205source files PASS. Web typecheck/lint PASS.
Full frontend221files/4280passed/9skipped; coverage98.16statements,
94.35branches,94.06functions,99.48lines; unchanged floors. Python workflow E2E
53passed/7150deselected in16.72s. Mock research20/20,0errors,USD0.0000.
Registry parity260objects/0mismatches; no registry object changed.

The sealed CLI replay used a new empty permanent-fixture database, full captured
public/financial inputs, production admission/adapter and MockTransport. B before
a separate grant was refused. A1 plus B4 synthetic Messages/paired counts yielded
copy33jobs/67Messages/92counts; copied known spend remainsUSD1.828877,
pending/unknown0. The held live ledger is not this fixture database. All four
stages and exact dynamic contact digests are in REPLAY-EVIDENCE.json. Synthetic
A/B authorization never left the fixture. No real credential was loaded.

Full patch-coverage gate completed; exact-publication CI is tracked separately
in the final publication receipt under outputs/d5/coverage-authority-v10/. No frontend runtime file, performance ceiling, coverage floor,
provider envelope or programme capacity is changed. A test-only follow-up adds
explicit checker-input role assertions after full-suite collection; it receives
a separate focused result and final-head CI.

## Final local gate

```text
7096 passed, 54 skipped, 53 deselected in 1137.09s (0:18:57)
Required test coverage of 89.0% reached. Total coverage: 94.62%
Coverage: 97% (diff-cover)
```

Package floors on the same complete coverage data: API88/agents96/security100/eval95%, all pass. New packet module92/92lines and100%branches; assistance_coverage226/231lines,97.84%line coverage. [Check log hashes and captured outputs](CHECKS.json). The final two archived-response variants passed2tests in12.01s, including the added exact checker role assertions. Documentation/claim/hygiene checks80passed in11.87s.

[Full live-ledger/artifact preservation](PRESERVATION.json) verifies135files and identical complete snapshots; the new live scope is absent. Provider/count contacts0, new grants0, new spendUSD0.

Exact published-head CI must be read from the GitHub run linked in the final handoff, rather than inferred from these local checks. No frontend runtime changes; local production-build/browser replay was not repeated. Remote CI includes its existing build/budget/browser tiers. No PR,merge or deployment.
