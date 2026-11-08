# Independent premise-calibration preflight — offline only

Application `d3a1d05297a7aa4c93f0f7ff6f492030bd06d36e`.
Candidate packet `a6056aa2237fce4385f0f531080c82f1cb53095774f4f893f2582f1f98d40b77`.
Predecessor `ee48fbde1c7c747fa928b5ecf7abc70f4df54a44efbc62d782c16f6703f1a73b`
is retained. The new producer/validator binding changes the packet identity;
[the audited comparison](evidence/premise-preflight-v1/REQUEST-BINDING-PROOF.json)
shows all four opaque IDs and transmitted request bodies are unchanged, including
source/evidence, schemas, model and settings. Neither packet is authorized.

**Actual preflight: READY_FOR_APPROVAL; approved=false.** The owner supplied four
attributed independent-review declarations: two accepts and two rejects. Their
exact passages, claims, question slots, request digests and file hash were
validated. Re-running the real CLI reproduced the supplied receipt exactly.
[Redacted binding receipt](evidence/premise-preflight-v1/VERIFIED-HUMAN-BINDINGS.json).
[Copyable separate approval request](evidence/premise-preflight-v1/APPROVAL-REQUEST.md).
There is one declared reviewer; inter-reviewer agreement is **UNMEASURED**.
Software validates declarations and bindings, not reviewer identity or semantic
correctness. No grant, job, reservation or contact was created.

Private completed worksheet:
`outputs/d5/premise-preflight-v1-human/reviewer-completed.json`.
Supplied passing receipt: `outputs/d5/premise-preflight-v1-human/PREFLIGHT.json.gz`.
Independent CLI reproduction:
`outputs/d5/premise-preflight-v1-human/PREFLIGHT-VERIFIED.json.gz`.
These remain in ignored local outputs; labels and attribution are not published.
The [initial HOLD receipt](evidence/premise-preflight-v1/PREFLIGHT-HOLD.json) and
[blank template](evidence/premise-preflight-v1/reviewer-blank.json) are preserved.

## Concrete command

Run from `/private/tmp/arxiv-agent-eng-calibration-preflight`. The locked venv
is unchanged; the additional declared schema-test packages were restored from
local pip cache into a separate temporary directory, with no network access.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-calibration-preflight-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled

# Actual supplied independent worksheet; never substitute a synthetic fixture.
# The preserved reviewer-blank.json still intentionally produces HOLD / exit 2.
export CALIBRATION_REVIEW_FILE=outputs/d5/premise-preflight-v1-human/reviewer-completed.json

$VENV_PYTHON -m src.calibration.premise_preflight \
  --packet planning/14-explore-and-research-modes/d5/evidence/premise-preflight-v1/packet.json.gz \
  --reviews "$CALIBRATION_REVIEW_FILE" \
  --inputs planning/14-explore-and-research-modes/d5/evidence/premise-preflight-v1/INPUT-TEMPLATES.json.gz \
  --scope-id d5-premise-a6056aa2237fce4385f0f531 \
  --out outputs/d5/premise-preflight-v1-human/PREFLIGHT-NEXT.json.gz
```

Outputs are append-only: choose a new receipt filename for a subsequent attempt;
never overwrite a prior refusal or passing receipt. Exit 0 means
`READY_FOR_APPROVAL`, not approved; exit 2 means `HOLD`. Keep completed reviews
and receipts containing reviewer attribution in ignored local outputs, not in
commits or provider payloads. This command has no DB, approval writer, API-key
reader or HTTP client construction path.

## Validation and exact bindings

This preflight intentionally supports the smallest four-probe scope only. The historical 12/16/28-probe options remain proposals; they need their own validator/policy, packet review and separate approval. Do not split or replay them to evade this bound.

All four distinct packet IDs must be reviewed. Each row must preserve the sealed
request digest, question/index, scored claims and evidence, and remaining prose.
It needs a nonblank reviewer and rationale, timezone-aware nonfuture timestamp,
and `provenance: independent_human`. Blank, uncertain/abstaining, synthetic,
missing, duplicated, stale or mismatched reviews refuse. Accept and reject must
both be present. Premise/disposition conflicts with the frozen contract refuse
for adjudication rather than silently changing the scoring rubric.

Attribution is a declaration, not software proof of a reviewer's identity or
independence. Reviewers must judge before seeing checker verdicts. The command
does not establish semantic correctness of their labels.

A successful receipt binds the canonical completed worksheet digest into every
input and the proposed scope, plus the actual file SHA-256 in the receipt. The
scope includes all four production `case_bindings`, their digest, the validator
code hash, packet identity, isolated principal and 4-job/4-Messages/4-count/
USD0.60 contact envelope. Any substantive review change alters every input hash,
the case-binding digest, scope digest and receipt digest. New input templates
are not authorization. Only the separate operator mechanism may record a later
explicit owner grant against those exact bindings.

The production checker adapter revalidates the complete prereview proof before
client construction, on both mock and provider paths. It does not trust a
caller-supplied digest alone. Compressed local proofs retain the original 32 KB
sealed-input bound and have bounded decompression. Labels, attribution, matching
keys and proof metadata are never added to the transmitted checker body. The
production request reconstruction must exactly match the sealed body/model.
Source, version, selected evidence, revocation, expiry, programme admission,
count pairing and accounting guards remain mandatory at actual dispatch.

## Offline verification and authorization boundary

```sh
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
$VENV_PYTHON -m pytest -q \
  tests/test_calibration_question_premises.py \
  tests/test_calibration_premise_preflight.py
make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
```

The focused tests use permanently offline disposable database schemas,
MockTransport and clearly synthetic declarations of the independent-review
format. They test grading/binding software; they are not independent human
reviews and never populate the actual worksheet. Explicit synthetic provenance
is rejected. The positive CLI fixture is separate from the actual HOLD receipt.

Actual baseline remains 16 programme jobs, 31 Messages, 50 counts,
USD0.825065 estimated spend, pending/unknown zero. No real authorization,
reservation, job or contact is created by preflight. The unchanged four-probe
proposal would require separate approval for at most 4 jobs/4 Messages/4 paired
counts/USD0.60, reaching maximum 20/35/54 and USD1.425065 including historical
spend plus the new reservation. With the unchanged USD1 buffer: USD2.425065.
No cap or expiry amendment is proposed here; programme expiry remains
2026-11-14T07:24:01Z. Everyday generation, recurrence and notifications stay off.
The original v7r2 scope stays stopped at Stage C 3/8 with all receipts and labels
unchanged. Owner3137 and review3178 are untouched.
