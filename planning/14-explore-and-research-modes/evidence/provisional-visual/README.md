# Provisional Build3 visual diagnostic — two confirmed mobile findings

**This is not final D1–D4 acceptance.** Frontend `sourceCommit:null`, immutable
compiled Build3 `DvLBxnx2yfYFJ7MXXpx3W`, Node14901 on3178. ROOT supplied backend
commit `12637c07393fb39f6487af5b9d81a4c79b159196`, API8178 PID3967. The frontend
was still in progress when built; no source commit is inferred from the checkout.

[Summary](summary.json), [raw observations](report.json),
[compiled runtime/asset receipt](compiled-runtime-binding.json),
[original observer report](initial-observer-report.json).
All251 immutable runtime files were hash-verified before and after capture;
actual fetched script/CSS response hashes were compared with that manifest.
The readonly run used `modes-preview`, with before/after state, context-index and
review hashes equal in every context. No app, configuration, service or key change, or direct DB access, occurred.
No authored preference/note/project/reading/judgment write occurred; allowed
context GETs may freeze derived edition/cache rows under the existing contract. All mutations/external/provider/source endpoints were blocked;
zero such requests were attempted. Owner3137 and all other stacks were not
contacted. Shared PostgreSQL/ROOT's mandatory Python gate was untouched.

## Confirmed findings

| Finding | Actual bounds | Scope and evidence |
| --- | --- | --- |
| PV1: initial mobile Today hides part of the second abstract line | In **both390px themes**, complete title516.359–601.297; abstract line 1:672.297–696.297, line 2:699.484–723.484; fixed player begins712. The second line extends11.484px beneath it. | [Light](mobile-light-today.png), [dark](mobile-dark-today.png), [actual native video frame](video-inspection/mobile-light-today-actual-frame.png). Same first public paper/version as D0; D0 line2 ended673.484, so the new visible mode row consumes50px of vertical space. No forced scroll or clamp exception was used. |
| PV2: Research without a selected project clips the mobile Search control | In **both390px themes**, bar top810/bottom832/height22. Its absolute Composer/Open Search target is top821/bottom865/height44; viewport ends844, clipping21px. | [Research empty](mobile-light-research-empty.png), [fresh light bounds](research-empty-bar.json), [fresh dark bounds](mobile-dark-research-empty-bar.json), [actual native video frame](video-inspection/mobile-light-research-empty-actual-frame.png). Zero horizontal overflow does not establish full control visibility. |

Both findings were sent to ROOT and the frontend owner as soon as confirmed.
They remain failures in this package. The script and recordings contain no CSS
injection, programmatic scroll-to-fix, source edit or data substitution.

## Other observations

- Four primary contexts:1440×1000 and390×844, both actual themes. All12 full paper titles clear the player. Ten of12 two-abstract-line checks pass: all eight native queue/Reader-return states and both desktop initial states. The two mobile initial states fail PV1.
- Native queue selection changes the actual paper; actual title href opens the exact retained version and entire abstract text. Reader return keeps that queued paper in all four contexts.
- Research without a project shows the honest create/select state and explicitly says the organizing profile question was not imported. This preview retains the copied organizing question; question-free persisted-profile acceptance belongs to the separate future write fixture.
- All16 axe scans have zero violations. No horizontal overflow, desktop outer scroll overflow, console/hydration error or CSP violation occurred. All four document policies have nonce and no unsafe-eval. Desktop empty-state Search forms remain within their viewport; [light](desktop-light-research-empty-bar.json) and [dark](desktop-dark-research-empty-bar.json) follow-ups retain their bounds.
- Every primary context preserves complete state (excluding response clock), context index and review bytes. Every additional bar follow-up also preserves state. Full before/after hashes are in the JSON reports.
- Four initial same-origin `GET /api/workspace/context/state` requests were canceled with `net::ERR_ABORTED`, one per context; all routes then settled correctly. The exact lifecycle cause is **not established here**. These remain explicit network observations, not a claim of zero network events.

## Captures and actual recordings

Initial Today: [mobile light](mobile-light-today.png), [mobile dark](mobile-dark-today.png),
[desktop light](desktop-light-today.png), [desktop dark](desktop-dark-today.png).
Queue and return PNGs for every context are adjacent. Research:
[mobile empty state](mobile-light-research-empty.png).

Actual readonly WebMs: [mobile light](mobile-light.webm),
[desktop dark](desktop-dark.webm). Both completely decode with exit0. Their contact
sheets and matched native initial/Research frames were visually inspected; the
mobile defects are visibly painted in the actual recording. Cold/loading frames
remain present. [Video report](video-inspection/report.json) records original
clip hashes, duration, native frame indices and matching aids. Thumbnail distance
only selects a review aid; it is not a pixel-equality or application-pass test.

## Observer corrections and reproducibility

The first asset observer treated encoded Reader chunk filename `%5Bid%5D` as a
literal filesystem name, producing four false missing-key assertions. Every
observed responseSHA exactly matches the receipt after decoding to `[id]`.
[Normalization proofs](asset-observer-normalization.json) retain all four exact
comparisons; no byte/hash assertion was relaxed. The [original report](initial-observer-report.json),
[original harness](harness-at-initial-capture.cjs) and [raw log](command.log) remain
unchanged. The current script only corrects URL-to-filesystem name decoding.
Canceled GETs are retained separately rather than silently removed.

Exact primary command, from `/private/tmp/arxiv-agent-eng-workspace-mode-build`:

```sh
env NODE_PATH=$PWD/web/node_modules node planning/14-explore-and-research-modes/evidence/provisional-visual/diagnostic.cjs > /private/tmp/workspace-modes-provisional-visual.log 2>&1
```

[diagnostic.cjs](diagnostic.cjs), [bar follow-up](research-bar.cjs) and
[actual video decoder](inspect-videos.py) are retained. Follow-up commands pass
`dark 390`, `light 1440` and `dark 1440`; their raw logs are adjacent. No3179
runtime or final24-group gate was launched or modified. The preparation manifest
was verified unchanged and `runtimeReady:false` remains intact. Final clean
source/build binding and all write/journey acceptance still wait for ROOT's
separate runtime-ready signal. [Artifact hashes](artifact-hashes.json) cover this
provisional package, excluding the manifest itself.
