# D0 existing-controller browser baseline

**Read-only baseline passes** on application
`10b4260f734c88a250880cb07d284a467e273529`, web tree
`e4f4f72d1b49f1647fb116e52105c90b03c0335c`, production build
`eppdpYPx86S8JcxekzeuQ`. This is the existing controller before any new mode UI.
The browser run occurred **2026-11-05 12:03:38–12:04:19 UTC**.

[Live isolated baseline](http://127.0.0.1:3178/workspace/today),
[raw report](report.json), [source/build binding](source-binding.json),
[verified static-copy hashes](static-assets.json), [command log](command.log).

| Check | Result |
| --- | --- |
| Desktop1440×1000/mobile390×844, both actual themes | Four contexts pass; OS color scheme selects System theme, actual `html[data-theme]` and computed canvas colors asserted |
| Basic Today/Reader/Radar/Library/Interests/Sources/Review navigation | 28 route observations pass using actual links; exactly one route h1 and no horizontal overflow; desktop document vertical overflow zero |
| Axe | All28 route scans: zero violations |
| Today complete title + first two abstract lines | Pass in all four contexts; desktop last required line bottom756.375/player top780; mobile673.484/player712 |
| Actual focused paper→Reader→return | All four exact pinned retained-version URLs/text match; native return retains the same focused paper |
| Mobile drawer | Both themes open/close normally; Escape returns focus to Queue & controls |
| Console/hydration/CSP | Zero console errors, page errors, unexpected request failures or CSP events; all four document policies have nonce and no unsafe-eval |
| Protected state | Complete state excluding response clock and review index byte-equivalent before/after each context; hashes recorded |
| Mutation/external/provider/source checks | Zero requests attempted/forwarded; all non-GET/HEAD and external/dangerous endpoint requests blocked by harness |

## Captures and retained-source identity

All six PNGs were visually inspected after capture:

- Today: [desktop light](desktop-light-today.png), [desktop dark](desktop-dark-today.png), [mobile light](mobile-light-today.png), [mobile dark](mobile-dark-today.png).
- Reader: [desktop dark](desktop-dark-reader.png), [mobile light](mobile-light-reader.png).

The focused public paper is **Agentic World Modeling for Agent Test-time Scaling
without Environment Replica**, work `arxiv:2610.40927`, exact retained version
`arxiv:2610.40927:v1:metadata-b09108e19893972e`. Reader was entered via the actual
Today paper-title href, including its exact version, `#abstract:0` and focused
`return_to`; its entire1,532-character retained abstract matched the version data.
Reader correctly says retained source abstract and `v1 (metadata revision)`, not
PDF/full text or a generated summary. The retained date visible in Reader is
Nov2; the Nov5 bounded edition creation does **not** establish new freshness.

The isolated principal is `modes-preview`:40 retained public works/40 versions,
11 copied interest topics,15 minutes, zero entries and zero reading revisions.
The existing organizing question is still shown by the controller; Explore's
future question-free behavior is not implemented or tested here. The UI honestly
shows **0/5 sources · limited** because no source checks ran. This is expected
baseline provenance, not a fresh-source or usefulness pass.

## Scope and reproduction

This is a small D0 baseline: four primary contexts and seven basic routes,
without the P7 tablet/70-case matrix, writes, model calls, generated artifacts,
source refreshes, packet preparation or human judgments. The harness did not
change application/configuration/schema/Git/DB/key files or stop/restart services.
Root-owned3178/API8178 remained running;3137/3148/3158/3168 were not contacted.
No new mode/Research persistence or cross-mode tools are claimed.

Exact browser command, from `/private/tmp/arxiv-agent-eng-workspace-mode-build`:

```sh
env NODE_PATH=/private/tmp/arxiv-agent-eng-workspace-mode-build/web/node_modules node planning/14-explore-and-research-modes/evidence/d0-browser/smoke.cjs > /private/tmp/workspace-modes-d0-browser.log 2>&1
```

[smoke.cjs](smoke.cjs) contains the principal/corpus, network, geometry, exact
version, theme, axe and preservation guards. The approved browser launch used
local escalated execution. [Artifact hashes](artifact-hashes.json) cover every
file here except that manifest itself. There were no browser failures or retry
runs. Other engines, OS IME, write flows and new feature acceptance remain unrun.
