# v8r3 offline verification

Source/application: `d3a1d05297a7aa4c93f0f7ff6f492030bd06d36e`.
Starting published head: `bc36c721888a72d048debf5158de2ce9d8367b3b`.
The refresh changes planning artifacts only, not runtime, schemas, prompts,
source selection, scoring thresholds or producer source hashes.

| Check actually run | Result |
|---|---|
| `make test-cov-diff VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python` | Exit 0; 6816 passed, 54 skipped, 53 separate-tier tests deselected; 881.65 s |
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

Full coverage log SHA-256: `5ecb0dc1442659fd4130fc6eb400490487a627bf2b5f1cf7d66a89b2e25bce6d`.
Local logs are in `outputs/d5/v8-ledger-refresh/`; raw financial replay is private.
No provider calls, token measurements, paid approvals, cap activation or spend
were performed. No frontend code changed; no new browser acceptance is claimed.
The count-cap extension boundary tests are **not implemented/run**; they are a
separate prerequisite listed in the capacity proposal, not passing evidence.

Remote CI is separate from these local results. The publication must identify
the exact branch head and Actions run; consult the final handoff/publication
receipt for its actual status. No predecessor green run is claimed as this head's CI.
