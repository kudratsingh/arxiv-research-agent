# v20 CI aggregate-capacity correction

The runtime and packet remain frozen at application `d33a0ccf7d21052bc20fef3047769befd85b4372` and packet `60cf5c83a3553c765993eb8cb2db5aed7bb5e382f9434baf9c893a3c582f4b27`. This correction changes CI capacity only. It authorizes no provider/count contact, live grant, accounting mutation, cap/expiry amendment, merge or deployment.

## Observed cancellation

[Run 44231702113](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/44231702113), head `d7e9a1a186f691afcc7035e6f1875d50f9b4a354`, selected 8,721 unit/integration tests after 53 E2E cases were deselected for their separate tier. It reached 97% without a visible F/E progress marker, then the 90-minute job ceiling cancelled coverage at 05:07:34Z on 2026-11-18. The unit step ran from 03:39:16Z: 88 minutes 18 seconds. This is not a completed or passing hosted gate. Patch coverage, E2E, three mock campaigns, safety and simulation were skipped. Raw regression packaging and the partial coverage upload still ran; their original artifacts are preserved.

The previous v19 CI job completed coverage in 56m54s and needed another 7m41s afterward. The enlarged v20 local gate completed in 68m26s, but it used the explicitly supplied shared interpreter on Python 3.13.7. Hosted CI follows the unchanged `.python-version` and used Python 3.14.10. Local and hosted environments are distinct evidence; no identical-interpreter or identical-duration claim.

## Bounded correction

Raise only `jobs.tests.timeout-minutes` from 90 to 110. This allows twenty additional aggregate minutes for remaining tests and downstream tiers. The source and tests are unchanged; every selector, coverage input, project/package/patch floor, per-test timeout, install/network bound, provider deadline, programme cap and expiry remains identical. The normalized YAML values are equal after restoring that one number; all nine jobs remain.

No test is skipped, shortened or replaced. The existing complete local runtime proof remains applicable to byte-identical source/tests. Focused harness/artifact/documentation verification passed 136 tests; the immutable packet CLI verifies and the retained complete XML still gives 95% patch coverage. A fresh exact-head hosted workflow must rerun all tiers and establish actual completion. Extra capacity is not evidence of a pass.

The first browser job separately timed out in its unchanged ten-minute OS dependency installation: 139 MB across 185 new packages from the Ubuntu mirror. No browser test ran. A requested early one-job retry was rejected because the parent workflow was still running; no retry job started. The corrected head's full workflow is the fresh browser attempt, with browser configuration, suite and timeout unchanged. There is no repeated blind rerun loop.

The C4 dependency audit remains a separate known failure on the documented unpatched development advisory. No exception is installed. Source/evidence/scoring/model/request bindings and the financial envelope are unchanged; the consolidated proposal remains inactive and conditional on explicit risk approval plus all required exact-final-head CI results.

All failed/cancelled evidence and predecessor manifests are permanent. The raw coverage export gap from the earlier failed local run is disclosed separately; the final successful local raw database and contexts are preserved. Owner3137/review3178, everyday generation, recurrence and notifications remain unchanged.
