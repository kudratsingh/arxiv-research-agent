# D5 v4 contract repair evidence

Application **9bd25a82d313070e810038c8de42c0dc3d9cb8b1**; packet **f21f4b66e1eb99ab75c7c242a9bfa46acb78ccabc13fb885477e8160425fd95a**, approved=false. No real provider/count contacts in this repair batch. The stopped real ledger remains10Messages/20counts/estimatedUSD0.125611, pending/unknown0.

## Contract and accounting

- [Original paid v3 failure fixture](../../../../../tests/fixtures/d5/stage-b-v3/README.md) and [original stopped receipt](stopped-v3-stage-b-receipt.json.gz). The failed result is not rebound to v4 or accepted.
- [Exact prospective request/schema bindings](prospective-requests.json), [wire/local schemas and bodies](requests/). Count bodies are explicit `*-count-request.json.gz`; other initial wires describe the bound candidate and do not authorize Messages under A.
- [Continuation audit](continuation-audit.json): unchanged active ledger, blank45-item worksheet, prospective DB with0policies/0scopes/0grants.
- [Mock A/B results](offline-results.json.gz), [readable report](offline-REPORT.md), [synthetic measurements](offline-stage-a.json.gz). Mock counts/usage are not measured tokens or spend. Quality stays HOLD; development never fills fresh minimums.
- [Actual executable replay](tools/offline-ab.py) and [successful replay receipt](repro-receipt.json). The tool installs into a new empty fixture DB and cannot choose provider transport or read a key. Run using Python stdin as documented in the [runbook](../../CONTRACT-REPAIR-v4.md).

## Actual checks

[Machine-readable verification](verification.json), [compressed exact logs](checks/).

| Check | Observed result |
|---|---|
| Python full coverage/diff |6536passed,54inherited skips,53separate-tier deselections;96.06%overall,97%patch (7338changed lines/184missing)|
| Package floors |API88/86,agents96/92,security100/97,eval95/91|
| Focused D5 |218pass, including original failed response, real PostgreSQL/MockTransport4-stage paths and3exact-decimal round trips|
| Frontend |4263pass/219files/0skips;98.15%statement/94.34%branch/94.13%function/99.52%line coverage|
| Affected Reader panels |37pass; purpose-specific missing fields render without dispatch|
| Types/lint/build |mypy189sources,globalruff,frontendlint/typecheck,productionbuild pass|
| Route budgets |22pass;CSS24868/25600B,Today169849/169984B,Reader165929/169984B|
| Other |53workflowe2e,20/20mockresearchUSD0,registry260/0|
| Browser |8result/passage/reload journeys over4contexts,0serious/criticalaxe,0page exceptions; reducedmotion in both dark contexts|

Intermediate red results and the cancelled obsolete coverage run are retained. No assertion, floor, budget or quality threshold was weakened. The snapshot fix preserves exact numeric strings rather than normalizing away a changed history digest. The first browser harness's [blocked-anchor report](browser-first-blocked-report.json) is retained: it forbade legitimate automatic reading-anchor saves. The [final report](browser-report.json) allows only those exact selected work/version writes to the isolated principal, blocks other writes/nonloopback, and passes all8journeys.

## Browser evidence

New preview **http://localhost:3194/workspace/today?mode=learn**, API8194/DBworkspace_d5_contract_v4_offline/principald5-v4-validation-run; build `dDDwWUpP-YEwj-6HZ9KRo`. Owner3137/review3178 were not used for writes. Assistance remains labelled simulated/quarantined. The original browser evidence remains in outputs alongside this new cohort.

| Context | Learning | Research | Passage | Recording |
|---|---|---|---|---|
|1440-light|[Learn](browser/1440-light/dev-learn.png)|[Research](browser/1440-light/dev-compare.png)|[Exact passage](browser/1440-light/dev-learn-passage.png)|[Walkthrough](browser/1440-light/walkthrough.webm)|
|1440-dark|[Learn](browser/1440-dark/dev-learn.png)|[Research](browser/1440-dark/dev-compare.png)|[Exact passage](browser/1440-dark/dev-learn-passage.png)|[Walkthrough](browser/1440-dark/walkthrough.webm)|
|390-light|[Learn](browser/390-light/dev-learn.png)|[Research](browser/390-light/dev-compare.png)|[Exact passage](browser/390-light/dev-learn-passage.png)|[Walkthrough](browser/390-light/walkthrough.webm)|
|390-dark|[Learn](browser/390-dark/dev-learn.png)|[Research](browser/390-dark/dev-compare.png)|[Exact passage](browser/390-dark/dev-learn-passage.png)|[Walkthrough](browser/390-dark/walkthrough.webm)|

Actual visual inspection in this batch:390light Learn and1440dark Research screenshots. Other contexts are browser/assertion/axe evidence, not a new subjective design approval. No new CSS layout was introduced. The wider unsaved-draft browser-history limitation remains unresolved.

## Remote verification

Final exact-head CI is recorded in the ignored local outputs/d5/contract-repair-v4/FINAL-PUBLICATION.json receipt and owner handoff; local checks are not remote CI. The final owner handoff/receipt records the exact run and conclusions.
