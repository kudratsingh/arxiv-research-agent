# Review grading demonstration — synthetic, no human validation

The inputs are retained public data and the protected **mock-only** v3 replay. All supplied labels are scripted synthetic fixtures in separate stores. The actual owner worksheet is blank. No provider/count contact or new spend occurred.

| Report | Labels | Grading outcome | Qualification |
|---|---|---|---|
| [Unreviewed](unreviewed/REPORT.md) | None | HOLD | HOLD |
| [Synthetic supplied labels](synthetic-hold/REPORT.md) | Scripted fixture, not human | HOLD | HOLD |
| [Synthetic unsupported claim](synthetic-fail/REPORT.md) | One claim marked unsupported in a separate fixture | FAIL | HOLD |

The mock run has12 fresh generated claims, below the unchanged20-fact minimum. Synthetic all-positive labels can exercise per-case grading but do not create more facts. The fake checker abstains, leaving conditional false-pass/error-rate denominators unscored rather than perfect. Actual independent-human supported claims and reviewed probe items remain0. Logical case PASS counts in the synthetic report are software-fixture outcomes, never accepted everyday outputs.

The sufficient-sample PASS branch is tested with explicitly fabricated software fixtures in `tests/test_workspace_d5_reviews.py`; it does not fill this benchmark's minimums. That test also requires qualification to remain HOLD. No real case/claim is added after results.

[CLI proof](proof.json) records validation, idempotent re-import and raw-results/blank preservation. [v2 analysis receipt](v2-explicit-analysis/analysis-receipt.json) explicitly binds the predecessor packet/raw result to the new scorer. [Binding/refusal proof](checks/review-bindings-and-refusal-proof.json) shows old results cannot be relabelled v3 and the unapproved validation DB still refuses before transport.

[Owner worksheet](owner-worksheet-v3.json.gz) is all-null,45 items. The original v2 blank worksheet remains unchanged at [its original path](../human-review-blank.json.gz). Use a new export from any future actual paid result; these labels do not transfer to a different result digest.

Run the production commands in [the review runbook](../../HUMAN-REVIEW-RUNBOOK.md). Replay the demonstration with:

```sh
ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1 \
$VENV_PYTHON - --packet "$PACKET" --results "$RESULTS" --out outputs/d5/review-demo-new \
  < planning/14-explore-and-research-modes/d5/tools/review-demo.py
```

The same real export/validate/import/score commands create JSON, Markdown, HTML and analysis receipts. Input evidence, financial rows and approvals are never edited by import or scoring.

## Final local verification

Applicationf962ff8; unit-tier-only test correction55287e2. **6,503 passed /54 inherited skips /53 separate-tier deselections**,94.61%total coverage,97%patch (7,310changed lines/183missing), all package floors pass. [Full log](checks/review-full-gate-final.log), [package floors](checks/review-package-floors.json), [verification identity](checks/verification.json). Focused133passed with99.46%new-module coverage and100%review-scorer coverage. Harness/grading87passed; documentation95passed; mypy189sourcefiles and repository-wideRuff pass. Separate e2e53/53, mockresearch20/20 at$0, registry260/0. No floor, tier or assertion was weakened.

The earlier failed full run (2missing-tier guard failures,6501other passes) is retained in `checks/review-full-gate.log.gz`; the corrected gate supersedes it. A focused development run made while the final parser edit was in progress correctly tripped producer-drift protection; it is not final-source evidence. The stable-source133pass run is authoritative.

Current preview **http://localhost:3193/workspace/today?mode=learn**. [Eight browser journeys](browser/report.json) cover both modes at1440×1000/390×844 in both themes, with0serious/criticalaxe findings and0console exceptions, failed-save retry, exact source and Library resume. [PDF exact-text checks](pdf-passages/report.json) pass all4contexts. The frontend source/build/budgets are unchanged from the prior4261test/22budget checkpoint; final exact-headCI reruns them separately. Owner3137/review3178 and their data are untouched.

[Desktop recording](browser/1440-light/walkthrough.webm), [mobile recording](browser/390-light/walkthrough.webm), [desktop result](browser/1440-dark/research-retrieval-result.png), [mobile result](browser/390-light/learn-method-result.png). The PDF harness scrolls to the mark before capture; it proves exact text/version/offset binding, not automatic visibility of every line. Retained samples remain partial.

Readable log copies normalize terminal whitespace only; byte-exact originals and hashes are in [the raw-log index](checks/raw-log-index.json). RemoteCI is independently tied to the exact final published head in the owner checkpoint.

Report display copies trim terminal trailing whitespace/blank EOF only; adjacent `REPORT.md.gz` files preserve exact CLI Markdown bytes. Original observed JSON and analysis receipts are unchanged.
