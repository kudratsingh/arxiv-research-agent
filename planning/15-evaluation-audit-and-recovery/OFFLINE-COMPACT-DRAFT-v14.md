# Prospective compact draft contract v14

`src/workspace/assistance_compact_draft.py` is a pure offline contract module.
Its revision is `workspace-assistance-compact-coverage-v14`. It neither selects
a provider route nor grants execution authority. Historical v10 exports and
stopped provider outputs remain unchanged.

The claim-bearing wire shape shares one cited claim definition and one evidence
handle enum between `answer` and `comparison_abstention`. Abstention text is
locally derived from disposition. Learn's single-paper shape has no cross-source
comparison fields. Research has `comparison_claims` and `comparison_basis`;
comparison-only notes require both to be empty. The existing source-resolution
path still requires independently cited basis claims from at least two distinct
selected works for a comparison. Merely naming two claim IDs does not establish
this condition or factual support.

Coverage contains fixed-shape arrays named `answered`, `lacks_evidence`, and
`omitted`. Every row names a sealed `part_id`. Answer rows contain nonempty
`answer_claim_ids` and optional context references. Evidence and omission rows
contain their separate reason enums and context references, with no answer
reference field. This removes repeated per-part unions. The local validator
requires every sealed part exactly once across groups, forbids duplicate or
unknown IDs, checks referenced claims and ordering, and rejects orphan claims.
`claims.part_ids` remains forbidden. Normalization deterministically restores
the existing per-part rendering representation and invokes the v10 coverage,
task-policy and procedural response validators.

Full abstention is a separate response branch without claims, question/section
references, comparison fields, or coverage reference fields, including empty
reference arrays. Missing application context permits only this branch, retains
the exact required `context_requests`, and requires every part to declare the
application-context evidence gap. It cannot omit parts instead.

The six-claim and 8,000-byte draft limits, 360-character claim texts, one to three
selected handles per claim, bounded procedures and coverage arrays remain local
requirements. The actual Anthropic SDK transformation drops some character and
array maxima; the transformed schema retains their descriptions and local
validation enforces them. Cross-row partition, relevance, whole-claim support,
source scope, preserved qualifications and factual review remain separate
checks. JSON Schema validity does not establish those outcomes.

For the exact archived three-part Learn/Compare selections, offline exports have
these sizes. Bytes are compact reconstructed UTF-8 JSON, nodes count schema
values including unexpanded definitions, and alternatives sum every `anyOf`
array's length. These measures are **not** provider compiler measurements.

| Metric | Learn historical v10 | Learn v14 | Compare historical v10 | Compare v14 |
|---|---:|---:|---:|---:|
| Schema bytes | 7,623 | 7,465 | 10,795 | 7,921 |
| JSON nodes | 453 | 322 | 633 | 338 |
| `anyOf` sites | 7 | 1 | 7 | 1 |
| Total `anyOf` alternatives | 17 | 2 | 18 | 2 |
| Root response alternatives | 2 | 2 | 3 | 2 |
| Claim definitions | 1 | 1 | 2 | 1 |
| Repeated c1-c6 enums | 9 | 1 | 15 | 1 |

`fixture_payload()` makes an owned, explicitly synthetic format derivative;
callers must label it accordingly. It does not revise archived provider output
or confer acceptance. The preserved Learn draft can be converted and validated
locally, while its stopped checker remains incomplete. The rejected Compare
request has no historical draft to convert. Synthetic comparison controls test
software behavior separately. Reduced schema branching and bytes do not prove
remote grammar acceptance, successful completion, checker qualification, human
review, or factual quality. No provider or token-count call is required or
permitted by this module.

All rights reserved. No license or reuse permission is granted.
