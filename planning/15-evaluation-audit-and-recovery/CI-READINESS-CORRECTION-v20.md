# v20 CI readiness correction

Runtime remains application `d33a0ccf7d21052bc20fef3047769befd85b4372`; packet remains `60cf5c83a3553c765993eb8cb2db5aed7bb5e382f9434baf9c893a3c582f4b27`. This changes one frontend test and the browser CI host, with no production, provider, evidence, scoring, SDK, lockfile or security-policy changes.

## Reader synchronization

Run [44243372107](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/44243372107), head `b47dab1a80f5e82ce9c74d4bd98fa1187e5732dc`, reported 4,298 passing frontend tests, nine skipped and one failing claim-fragment reload test. The heading was present before the deliberate animation-frame fragment synchronization completed. The same assertion passed in the previous hosted run; ten local pre-change trials also passed, so local reproduction is not claimed. The full hosted failure and both sets of local trials are retained.

The test now waits for the same `aria-current=location` state after initial mount, hash change and history navigation. It keeps every no-save/no-dispatch assertion. There is no arbitrary sleep, increased timeout, new skip or changed assertion. Ten focused post-change trials and all thirty tests in the module passed. Full frontend coverage, type and lint checks run again; their exact outputs are recorded in permanent receipts rather than inferred here.

## Browser installation

Both runs 44231702113 and 44243372107 used the moving Ubuntu 26.04 image and exhausted the unchanged ten-minute Playwright installation bound while fetching 185 OS packages / 139 MB from the regional Ubuntu mirror. Neither attempt reached any browser test. No old failure is relabelled as a regression pass.

Pin only the browser job to `ubuntu-24.04`, a platform supported by the installed Playwright 1.62.1. Ubuntu 26.04 is also supported; this is a controlled host-stability choice after two observed mirror stalls, not a claim that 26.04 is unsupported. Whether it resolves setup remains unproven until the new hosted attempt. The complete full browser matrix, dependency installation, accessibility checks, Compose path and all step/job bounds remain unchanged. Normalized workflow values are identical after restoring only that runner value. No browser is omitted or substituted.

The earlier Python aggregate bound remains 110 minutes; tests and coverage floors are unchanged. The preceding run is left to finish and all failed, cancelled and skipped evidence is preserved. A fresh full workflow on the new exact head supplies its own results.

## Unresolved audit and boundaries

The C4 audit still fails on the previously documented unpatched development dependency. No exception is installed. Owner risk acceptance and all required exact-final-head green checks remain prerequisites for activation. These mechanical fixes grant no model/count contact, live authority, financial mutation, settlement, cap/expiry change, merge or deployment. Owner3137/review3178 and historical evidence remain untouched.
