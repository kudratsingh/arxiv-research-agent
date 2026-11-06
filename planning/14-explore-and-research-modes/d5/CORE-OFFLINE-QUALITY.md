# D5 offline quality and limitations

This is software/provenance evidence, not a model-quality qualification. No provider
or count request was made. Human support, learning comprehension, relevance and
usefulness remain unmeasured; their fields are null.

## Repairs and what they establish

The historical V8 diagnostic remains immutable: q01 development; q02/q03 held-out
failures; q04 stopped on repair6765 measured input tokens against6400usable;
q05–q10 unrun. Original completion0/9 cannot meet90% or20-reviewed-item criteria.
Neither a new development fixture nor the proposed D5 cohort changes those results.

D5 replaces the fixed240-character snippet **only in its new contract** with
bounded contiguous complete-sentence groups (≤1600 Unicode characters). Selection
never expands beyond the retained parent span. Chopped edge sentences and very
long sentences are omitted, never cropped into a proposition. Adjacent qualifications
remain together when the bound permits. Sentence recognition is a heuristic:
abbreviations, PDF columns, equations and parser artifacts can still be wrong.
The two inherited PDF samples remain selected excerpts, with their original
extraction warnings; no claim of complete-paper or general PDF support is made.

Up to6 short atomic claims can cite1–3 separately preserved handles. Server-side
resolution supplies exact quotations and page-local Unicode offsets; ambiguous or
repeated text is not located with substring searching. Two-source comparisons need
separately cited claims from two works, an explicit basis and compatible-evidence
review. Nonadjacent passages are never joined into a continuous quote.

Draft/check/repair/recheck are bounded together before admission. Checker requests
contain only each claim's own cited evidence and the optional prose requiring
review. Repair retains authoritative selected units once and removes redundant
resolved quotations. Byte bounds include JSON-in-text escaping and are enforced
again before constructing MockTransport. Estimates and byte units are distinct
from provider token counts and actual usage. This does **not** prove that the
former6765-token request now fits6400: that old authorization remains unchanged.
The proposed fresh envelope needs actual paired measurements.

Every local and transformed wire schema is tested. A complete bad response is
journaled before content acceptance and classified as failed with known synthetic
receipt; truncation/invalid JSON never becomes an accepted recovered summary.
A genuine missing local completion remains unknown and is not automatically
replayed. Real paid reservations/accounting and historical receipts are unchanged.

## Adversarial coverage

| Case | Required behavior | Nature of evidence |
|---|---|---|
| Valid identity but unsupported meaning | Identity alone produces no support; proposed negative review rejects | Deterministic synthetic review, not human gold |
| Missing qualification / misleading comparison / contradictory source | Whole-claim check or abstention; never infer support from quote overlap | Scripted negative cases |
| Abstract-only or insufficient evidence | No promotion to full text; explicit limitation/abstention | Scope and empty-evidence tests |
| Wrong version/hash/parser, fabricated quote/offset, unselected handle | Refuse before checker; retain failure | Mechanical provenance checks |
| Unicode/repeated quotations | Exact code-point offsets, no ambiguous search | Synthetic exact-reference tests |
| Nonadjacent citations / two-source comparison | Separate references and explicit source basis | Local+wire schema and real Postgres round trips |
| Truncated / invalid / schema-incompatible response | Failed content, raw response retained; no accepted partial | MockTransport boundary |
| Checker disagreement or unsupported prose | Hold/fail; optional factual prose cannot borrow a claim's verdict | Scripted checker cases |
| Failed repair/recheck | Maximum4calls/1repair; failed result never published | Durable pipeline regression |
| Cancellation / expired lease / restart / budget refusal | No automatic replay; owned durable state and unknown counters retained | Real isolated Postgres |
| Reordered material IDs | Valid two-source request remains intact after canonicalization | Reproduced browser defect + regression |
| Reordered citation JSON | Saved note uses its own work/version passage | Reproduced browser defect + UI regression |

The default fake checker accepts only exact **whole-unit** quotation. It abstains
on paraphrases, shortened sentences and comparison interpretations. Consequently
real retained excerpts often produce `ready_partial`. Their claim badges say
simulated/abstain and overall factual acceptance stays false. A synthetic positive
means the protocol works; it says nothing about scientific truth or checker error
rates. Optional guide/comparison prose is visibly unverified and sent for a
separate prose review. Unsupported factual prose must hold acceptance, not be
relabelled as inference to pass a gate.

## Reproduce

From the worktree root with the locked Python, sentinel and isolated test database:

```sh
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
$VENV_PYTHON -m pytest tests/test_workspace_assistance.py tests/test_workspace_grounding.py tests/test_workspace_executor.py -q
```

Final exact-source counts/logs belong in STATUS and the evidence manifest, including
initial failed attempts, inherited skips and separate unrun gates. The first full
Python run was6366pass/54skip/1failure: its route-set assertion needed the five new
offline endpoints. The first complete frontend run passed4231tests but missed the
unchanged coverage floors; focused recovery/Reader tests were added. Sandbox-only
local-listener failures are preserved separately from normal-access results.
