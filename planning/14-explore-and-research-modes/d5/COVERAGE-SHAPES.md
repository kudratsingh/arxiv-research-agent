# Status-specific coverage repair (offline, v9)

This is a new prospective contract, `workspace-assistance-coverage-shapes-v9`,
from publication `0592bec4`. The stopped `f48b3f24` scope and its rejected Learn
output remain failed and closed. Frozen v8r4b results/scorer and its machine
review are unchanged; human qualification and Stage D remain out of scope.

The observed Learn draft was valid JSON and passed the exact v8 schema sent to
the provider. Its p3 object said `lacks_evidence` but named c5 as an answer. Local
semantic validation correctly rejected it before checker dispatch. That consumed
one funded job, one Message and one paired count, with USD0.023284 estimated
workflow usage. No checker, repair or recheck ran. The later two cases were unrun.

## New contract and rendering

| Status | Wire fields | Allowed gap |
|---|---|---|
| answered | status, **nonempty** answer_claim_ids, context_claim_ids, gap | none only |
| lacks_evidence | status, context_claim_ids, gap; **no answer_claim_ids field** | application_context, source_scope, common_evaluation, methods, protocol, data_splits, metric_definition, uncertainty_calibration, memory_error_persistence |
| omitted | status, context_claim_ids, gap; **no answer_claim_ids field** | claim_budget or not_prioritized |

Full abstention has no claims or claim-reference fields. Missing application
context restricts every coverage row to lacks_evidence/application_context.
Other full abstentions use reference-free evidence-gap or omission objects.
The prior full-abstention task restrictions still determine which dispositions
are allowed. Comparison-only abstention may retain separately cited source notes;
those notes do not answer the comparison.

Every fixed literal is exported as a one-value enum, including disposition,
reason and required context values. Tests call the installed Anthropic SDK's
`transform_schema(model)` and validate against its exact output. The SDK drops
`const`, but preserves `enum`, `minItems: 1` and additionalProperties=false.
Remaining local limits (including maxItems) are visible in the transmitted schema
and prompt descriptions. SDK acceptance by a remote provider remains untested.

Normalization fills absent reference arrays **after** wire/local shape validation
for the existing Reader's coverage component. It retains duplicate/disjoint,
reciprocal claim/part, selected evidence, exact version/hash/quote/offset,
comparison-source and six-claim checks. Legacy v8 shape replay is retained.
New HTTP previews/submissions use v9; explicit null task context is still rejected.
The wire/local revision must match the sealed policy.

c5 in the preserved draft reports a conditional result. In the **synthetic**
corrected control it can answer p2, but appears only in p3's context_claim_ids;
p3 asks for unspecified protocol details and remains lacks_evidence/protocol.
The corrected fixture is software evidence, not a successful provider answer.
A valid status object cannot establish semantic relevance or whole-claim support:
mandatory coverage/atomicity/qualification/prose checking remains necessary.
There is still at most one repair followed by mandatory recheck.

## Preserved evidence and protected replay

The regression fixture preserves the exact original response text, its SHA256,
and the archived transmitted request/schema/response. It is labelled failed and
never rewritten into an accepted result. Tests separately construct corrected
synthetic controls. The source draft and all Stage A/B receipts remain in the
prior worktree's outputs/d5/coverage-stage-b-20261109 and coverage-stage-a-20261109.
The active-pointer bytes and those files are checked before/after.

The protected offline path uses the same D5 adapter, scoped operator record,
programme/amendment checks, reservations, paired counts, contact journal, durable
result and Reader normalization as paid qualification. Only HTTP transport and
explicit disposable authority are synthetic. The fixture-marked database cannot
dispatch a provider request. Blank human labels and HOLD are retained.

The narrow new packet permits only a fresh Learn development identity. A is one
count-only request. B requires its own grant plus the exact A receipt, then admits
one workflow with mandatory checking and capacity for draft/check/repair/recheck.
All dynamic bodies are derived from actual preceding outputs under sealed
schemas/templates and journaled when created. No future bodies are invented.

## Run commands (no paid command was executed)

Run from the isolated repair worktree root with the locked Python:

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export PYTHONPATH=/private/tmp/arxiv-calibration-preflight-deps:$PWD
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
"$VENV_PYTHON" -c 'import src; print(src.__file__)'
"$VENV_PYTHON" -m pytest -q tests/test_workspace_coverage_shapes.py tests/test_workspace_coverage_shapes_runner.py tests/test_workspace_coverage_adapter.py tests/test_workspace_request_boundary.py tests/test_workspace_coverage_packet.py tests/test_workspace_coverage_runner.py
```

The dependency overlay supplies test-only jsonschema; no shared environment was
installed into. The integration fixture creates/removes only UUID test schemas.

To replay the final packet, first create a **new disposable** database on the
isolated Postgres, then use the locally retained reconciled public/financial
snapshot (it excludes private notes/preferences/history and credentials):

```sh
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_coverage_shapes_replay_new
"$VENV_PYTHON" -m src.workspace.d5_coverage_replay replay \
  --snapshot outputs/d5/coverage-shapes-v9/snapshot.json.gz \
  --packet planning/14-explore-and-research-modes/d5/evidence/coverage-shapes-v9/packet.json.gz \
  --out outputs/d5/coverage-shapes-v9/replay-new
```

This command installs synthetic fixture authority only in an empty, permanently
marked disposable database. Do not point it at a live validation ledger. The
ordinary protected runner cannot create its own authority. Future provider
commands and separate decisions are in [the proposal](COVERAGE-SHAPES-PROPOSAL.md).
Owner3137/review3178 and their data are untouched; everyday generation, recurrence
and notifications remain disabled. Nothing is merged or deployed.
