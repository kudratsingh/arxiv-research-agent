# Final-head CI bound correction

Run [43382685582](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/43382685582)
on publication6ffd54e8 completed eight jobs successfully. Python was cancelled,
not passed, by the35-minute aggregate job bound. Coverage began07:02:47Z; logs
showed continued passing progress through99%, including the new production AUD-01
regression, before cancellation07:36:17Z. The last completed module was
`test_workspace_task_policy.py` at07:36:12Z. There was no logged assertion failure. GitHub's check annotation explicitly states:
"The job has exceeded the maximum execution time of 35m0s". Its complete
annotation response is retained alongside the cancelled-run logs.

The first publication and its full logs, artifacts and status remain in permanent
storage under `arxiv-evidence/evaluation-audit-recovery-20261113/publication/`.
The cancellation is not rewritten as green and is not evidence for the unfinished
Python floors or downstream workflow/campaign/safety/simulation steps.

The correction changes only `jobs.tests.timeout-minutes` from35 to45. A parsed
workflow comparison confirms all nine jobs, step order, test selections, coverage
inputs, floors and per-step/network limits are identical. The per-test60-second
ceiling and provider30/120/480-second deadlines remain unchanged. This supplies
bounded aggregate margin for the enlarged sequential gate; it skips no work.
The cancelled run reached99% of the coverage test selection and still needed
coverage completion/floors and the separate E2E,
14-job protected mock campaign, safety and simulation steps.

Qualification applicationa3cf3d7c and packet97d24567bc98753122315f135a621eb886cebb2b81c32eb5762572589f037e08
are unchanged: CI wall-clock policy is outside the sealed provider/scorer bindings.
The packet is reverified after the correction. No new authorization, provider/count
contact, financial mutation, capacity/expiry change, merge or deployment occurs.

The full pre-push coverage gate is repeated with per-test contexts and slow-test
measurement enabled, preserving the complete selection. The next publication
must obtain all nine checks on its own exact head. Final immutable receipts under
`publication/final-<head>/` identify the new run and keep the earlier8/9 outcome
separate. The completion handoff supplies that exact head/run after observation.

All rights reserved. No license or reuse permission is granted.

## Recovery pre-push gate

Actual repeated result: 7206 passed, 54 skipped, 53 deselected in 1887.82s (0:31:27). Per-test contexts and the30slowest
durations were retained. Project coverage94.41271011199149%;patch10586/10977lines;
all original package floors passed. The packet reverified unchanged.
The run logs and XML/context data are retained separately from the first run.
