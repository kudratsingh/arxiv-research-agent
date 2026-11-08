# v8r3 offline verification

Source/application: `d3a1d05297a7aa4c93f0f7ff6f492030bd06d36e`.
Starting published head: `bc36c721888a72d048debf5158de2ce9d8367b3b`.
The refresh changes planning artifacts only, not runtime, schemas, prompts,
source selection, scoring thresholds or producer source hashes.

| Check actually run | Result |
|---|---|
| `make test-cov-diff VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python` | Exit 0; 6816 passed, 54 skipped, 53 separate-tier tests deselected; 924.10 s |
| Total Python coverage | 94.58%, existing 89% floor preserved |
| Patch coverage against `origin/main` | 97%, existing 90% floor preserved |
| Documented claims / hygiene / calibration-document tests | 95 passed, 25.95 s; subset, not additional independent test count |
| `python -m src.workspace.d5_benchmark verify --packet …/packet.json.gz` | Verified packet `42aa787ca0aa9e22dd92a6eddb5a7b8642a9f8364526bccf3af66b3947de2b4c`; zero contacts |
| Production adapter initial request exports | Constructed with denying MockTransport and sentinel; no HTTP contacts |
| Frozen field comparison | All 16 checked corpus/profile/case/scoring/producer fields unchanged |
| Approval/amendment/request digests and budget arithmetic | Passed; [artifact audit](ARTIFACT-AUDIT.json) |
| Active ledger final read-only audit | 20 jobs / 35 Messages / 54 counts / USD 0.904053; pending/unknown 0; caps 24/80/80/USD 10; no new scope |
| Original v7r2, calibration result and calibration accounting files | Three original SHA-256 bindings unchanged |
| Disposable replay | Permanently provider-disabled DB; financial history matches, zero operative budget policies/new scope grants |
| Public/private separation | Full financial replay and human prereview proofs remain ignored local files, mode 0600 / directory 0700; published request context excludes calibration proofs |
| `git diff --check` | Passed |

Full coverage log SHA-256: `9dd803dacf3b2a97a79a9015d997933c401f1e105a2e0a304eb80b0f28eb5183`.
Local logs are in `outputs/d5/v8-ledger-refresh/`; raw financial replay is private.
No provider calls, token measurements, paid approvals, cap activation or spend
were performed. No frontend code changed; no new browser acceptance is claimed.
The count-cap extension boundary tests are **not implemented/run**; they are a
separate prerequisite listed in the capacity proposal, not passing evidence.

Remote CI is separate from these local results. The publication must identify
the exact branch head and Actions run; consult the final handoff/publication
receipt for its actual status. No predecessor green run is claimed as this head's CI.

## Publication correction

The first published artifact head `961c339a` has an archived CI run:
https://github.com/kudratsingh/arxiv-research-agent/actions/runs/42474203668 .
Global Ruff caught the new planning helper's unused import and formatting. Those
were fixed without changing runtime source or the packet; the
[helper audit](HELPER-FORMATTING-AUDIT.json) proves normalized AST equivalence
and retains the original executed-generator hash/commit. Global `ruff check .`
now passes locally. The same first CI run also timed out after 5000 ms in the
unchanged frontend test `tests/daily/experience.test.tsx` (interests editing).
That failure is preserved, not hidden by a timeout or assertion change.
The subsequent publication must be assessed on its own exact-head results.

After the lint cleanup, the mandatory `make test-cov-diff` gate was rerun in
full: 6816 passed / 54 skipped / 53 separate-tier deselected, 94.58% total and
97% patch coverage, exit 0 in 924.10 seconds. Global Ruff, packet verification
and all 41 local review-document links also passed. No thresholds changed.
