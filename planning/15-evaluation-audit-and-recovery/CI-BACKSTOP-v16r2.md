# CI backstop correction after measured v16r2 cancellation

Run [43681834031](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/43681834031)
on package publication16ce72f3 ended with8successful jobs and Python coverage
cancelled by the60minute job limit. Coverage began05:38:43Z and was cancelled
06:37:08Z on2026-11-15 at94%of8163selected tests. No failed-test or timeout marker
was observed; the five new production union-integration tests had passed. This
is not complete coverage or a green hosted gate. All raw logs, artifacts and the
original source bundle remain in permanent evidence.

The execution-bound change is jobs.tests.timeout-minutes60→90. The existing coverage upload also gains the already-exported build/d5-v15-test-evidence/ journals and build/.coverage database, with hidden-file inclusion confined to those explicitly named paths. All9jobs,
every step and test selector, coverage inputs/floors, network/install bounds,
per-test limits and5minute campaign-step bounds remain identical. The bounded
headroom includes remaining coverage, three existing complete mock campaigns,
E2E, safety, simulation and uploads. Provider60/120/240second operation deadlines,
1200second workflow time, models, request/schema/evidence bindings, spending,
programme caps and expiry are untouched. No provider or token-count contact.

Applicationd3fec6e576ff5223ff414eb5fff29505378b6a0e and packet35292dcc485d8d7f6f7c126453a8dce17409c470debe2b56828898cef8f57d6d remain frozen. The31-file package at16ce72f3 is immutable. A later CI/docs-only publication can have a different commit without changing those runtime/packet bindings. The final handoff must identify both commits and obtain all9checks on that exact follow-up head; the cancelled run establishes no full hosted pass.

Repeat the complete local coverage gate with CI's per-test context collection,
then the unchanged package floors, focused CI/docs contracts and exact packet
verification before push. The final full hosted run remains required. No test,
assertion, floor or quality threshold is weakened.

All rights reserved. No license or reuse permission is granted.

## Evidence-retention correction

The cancelled runner uploaded only a partial coverage summary, not its temporary synthetic database exports. Those unuploaded temporary files are unavailable; no recovery is claimed. All8available artifacts,9rawjoblogs and the fullrunlogarchive are preserved. The permanent canonical replay independently preserves88complete bodies and10current final-check bindings. No original paid-provider evidence or accounting changed. Additive coverage paths close this gap for the follow-up.

## Measured local follow-up

Fresh `make test-cov-diff` with `--cov-context=test --durations=25` passed
8101tests/62skips/53E2Edeselected in
2485.88reported seconds. It recorded9853coverage contexts,
94.520214%project and96%printed patch. Same completed data passes
API88≥86,agents96≥92,security100≥97,eval95≥91. All184affectedCI/docscontracts pass.
No test or runtime file changed after the earlier complete gate. Packet verification
and all14compiled-input equality checks pass;89producer/71adapter hashes remain
unchanged. All coverage data and logs are permanent. Hosted CI still needs a fresh
exact-head run; no cancellation or local result is described as hosted success.

## Lossless artifact container after the completed test gate

The next run43689983976 on d923b207 completed the unit/integration and
coverage gates:8154passed/9skipped/53E2Edeselected in3781.39s;
project94.86%, package floors and patch gate passed. Its upload then failed
because a parameterized raw journal filename contains quotes. Eight other jobs
passed; the whole run is failed, and downstream Python steps were unrun.
All available artifacts and raw logs remain permanent. Unuploaded temporary
journals are unavailable; no recovery is claimed.

The follow-up adds a bounded5minute preservation step before upload. It packs
raw files under safe opaque tar members and stores each exact original name,
size, SHA-256, mode and timestamp in an internal/external manifest. Verification
rehashes every member and refuses missing, duplicate, unlisted or corrupted
bytes. Originals are never renamed, truncated or overwritten; earlier output
packages cannot be replaced. Missing/empty source directories are explicit,
not called complete evidence. Upload contains the safe archive and manifest,
not raw paths. This is compatible with GitHub's documented artifact filename
restriction; the original names remain lossless data rather than upload paths.

Regression tests include the actual quoted/CRLF parameter shape, Unicode,
binary/truncated content, nested/long names, hidden files, duplicate entries,
manifest mismatch, corruption, symlinks and overwrite refusal. The full local
gate and a new exact-head hosted run remain required. The runtime application,
all14compiled inputs and frozen31-file packet are unchanged; this CI helper
and its tests are outside production producer bindings. It changes no provider,
quality, cost or approval rule. No rerun is presented as a successful provider
response or scientific validation.

References: [artifact path validation](https://github.com/actions/toolkit/blob/main/packages/artifact/src/internal/upload/path-and-artifact-name-validation.ts)
and [upload-artifact packaging guidance](https://github.com/actions/upload-artifact#permission-loss).
