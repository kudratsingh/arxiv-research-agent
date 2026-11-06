# Current D5 review/grading evidence

The active evaluator/application is **f962ff8**, packetv3 **e1ed94498ce74231621f5c1394ddabd0aee11d3c42b7f88f5983e78d22c6d1da**. See [the review-grading index](review-grading/README.md) for actual commands, computed reports, blank worksheet and binding receipts. Final publication/CI is reported separately for its exact head. All cohorts below remain their original v2/core evidence; they are not recast as new-scorer results.

## Preserved v2 evidence index

Active application **b7240cf34b1ef1331e33fb992870da71528105e2**, frontend build **Mh3EAZc3soYDoaWmy__H5**, system sealv2 **1e5716df09364be0db9501e9d2bc7ff3184fc65655dbbb77c6cd658a2ae6a76f**. Publication commits after this are documentation/artifacts only unless explicitly stated. Remote CI is independently reported for the final published head, never inferred from local checks.

## Reproducible results

- [Markdown scorecard](benchmark-REPORT.md), [HTML scorecard](benchmark-index.html), [raw compressed results/contact journals](benchmark-results.json.gz).
- [Historical and offline accounting](accounting.json); [blank human review](human-review-blank.json.gz).
- [Final Python coverage/patch log](checks/full-patch-published-application.log):6453pass,54inherited skips,53separate-tier deselections,94.54% total,97% patch; package floors in [JSON](checks/package-floors-qualified.json).
- [Frontend coverage](checks/web-coverage-qualified-publication.log):4261tests/219files,0skips; statements98.16%,branches94.32%,functions94.13%,lines99.52%. Floors unchanged.
- [Production build](checks/build-qualified-polish.log), [budgets](checks/budgets-qualified-polish.log), [lint](checks/lint-qualified-polish.log), [typecheck](checks/typecheck-qualified-polish.log), [strict mypy](checks/mypy-qualified-publication.log).
- [Separate workflow e2e](checks/e2e-qualified-final.log):53pass. [Scripted research](checks/simulation-qualified-final.log):20/20,$0. [Registry](checks/registry-qualified-final.log):260objects/0mismatches.
- [Existing live suite](checks/existing-live-final.log):16/16,0retries/skips, exact unchanged3-work/4-version synthetic CI seed on3190/API8190, final frontend/backend. This is separate from the40-real-work benchmark.
- [Restart persistence](checks/restart-verification.json), [restart browser/failure recovery](restart-browser/report.json), [unapproved validation DB/admission](checks/unapproved-validation-readiness.json).

All22 bundle checks pass. CSS24,868/25,600B; Today169,848/169,984B; Reader165,928/169,984B; Projects169,115/169,984B; Thread165,334/169,984B. Lazy Reader assistance is not in initial page bundles; remote provider/token fit and complete lazy-route transfer are not established by first-load budgets. No ceiling/floor or dependency changes were used to pass.

## Final browser walkthroughs

[Machine report](protected-browser/report.json):8 learning/research journeys across1440×1000/390×844 ×light/dark; dark uses reduced motion. No console exceptions, external dispatches or serious/critical axe findings. These use only isolated principal`d5-validation-run` on3192/API8192, never owner3137. Public source metadata is retained; all authored projects/notes/output are verification examples.

| View | Screenshot | Automated full journey recording |
|---|---|---|
| Desktop light | [Learning](protected-browser/1440-light/learn-method-result.png), [Research](protected-browser/1440-light/research-retrieval-result.png) | [WebM](protected-browser/1440-light/walkthrough.webm) |
| Desktop dark | [Learning](protected-browser/1440-dark/learn-method-result.png), [Research](protected-browser/1440-dark/research-retrieval-result.png) | [WebM](protected-browser/1440-dark/walkthrough.webm) |
| Mobile light | [Learning](protected-browser/390-light/learn-method-result.png), [Research](protected-browser/390-light/research-retrieval-result.png) | [WebM](protected-browser/390-light/walkthrough.webm) |
| Mobile dark | [Learning](protected-browser/390-dark/learn-method-result.png), [Research](protected-browser/390-dark/research-retrieval-result.png) | [WebM](protected-browser/390-dark/walkthrough.webm) |

Slower readable demonstrations: [desktop](owner-walkthrough/1440/walkthrough.webm), [390px mobile](owner-walkthrough/390/walkthrough.webm). They show the same stored claims, exact passages, gaps, explicit save controls and Library. They do not independently establish owner comprehension or subjective motion quality. The automated journey recordings were decoded and sampled at15/50/85% in all four contexts; originals remain. Inspected final result/passage frames show readable text/contrast and stable controller/player, with content below the fold requiring normal scrolling.

[PDF exact-text report](pdf-passages/report.json) and four theme/width captures preserve ReAct's exact retained page/offset text. The harness explicitly scrolls the selected mark into view before capture; it does not prove automatic full-passage visibility or general full-paper extraction. [Failed read](restart-browser/390-failed-read.png) and saved-result recovery are isolated injected failures. Failed-save retry identity is recorded in the main report.

## Cohorts and preserved failures

Earlier unprefixed1440/390captures and`browser-report.json` belong to the core c9b4970 local-simulation cohort. `CORE-*` documents preserve that checkpoint; they do not establish the later protected runner. System sealv1/application111f2de is superseded only for the human-HOLD report wording. Active sealv2 binds b7240cf; no paid output preceded either seal. Historical q01/q02/q03/q04 and original0/9 denominator are untouched.

Original local failed attempts are retained under`outputs/d5/`: sandbox listener denials, coverage misses, an old route-set pin, and browser harness locator/message mistakes. Corrections added meaningful coverage or used the existing truthful UI flow; no coverage floor, test tier, product-truth assertion, source metadata or owner judgment was weakened. New real token measurements, provider schema acceptance, factual support, owner usefulness and paid execution are **unrun**, not skips or passes.

The readable `.log` copies normalize terminal carriage returns/trailing whitespace only. Byte-exact originals are preserved as adjacent `.log.gz` files, with hashes in [the raw-log index](checks/raw-log-index.json); reported outputs/numbers were not edited.

## Publication correction and fresh replay

The first published head57b7181 CI run [42203019523](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/42203019523) exposed three Ruff findings in two helper scripts (imports and one semicolon-separated statement). Global local Ruff had previously covered `src/`, not CI's complete repository command. The helper-only correction preserves active source/wire/packet bindings; [repository-wide Ruff now passes](checks/ruff-repository-final.log). No source or schema is re-frozen for import ordering. Final-head CI is a new separate run reported in the owner checkpoint.

The published snapshot+seal were installed into a **new** disposable `workspace_d5_package_replay` database and the complete protected offline benchmark rerun: [proof](checks/published-package-replay-proof.json), [log](checks/published-package-replay.log). Claims and scoring denominators match the original final run exactly; runtime timestamps are expected to differ. This adds no real provider contact, human label or scientific-quality evidence.

After the helper-only lint correction, the full required `make test-cov-diff` gate reran: **6,453 passed /54 inherited skips /53 separate-tier deselections, 94.54% total and97% patch**,550.27seconds. [Log](checks/full-patch-helper-lint-fix.log). The active `src/`/`web/` application, packet digest and producer hashes are unchanged; this is not another evidence/schema revision.
