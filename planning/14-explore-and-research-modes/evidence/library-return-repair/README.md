# Library return repair and final verification

Verified application **b261ddc5e0e034438a4dcc90bbbcb0ca42c76de3**, immutable build
**PwbeWv0RU7h8JGqumje0V**. Preview http://127.0.0.1:3178/workspace/today?mode=learn.
The subsequent publication commit changes documentation/evidence only.

## Reproduction and fix

Exact-head CI on ff51664 finished8jobs successful and1browser job failed
([prior CI summary](prior-ci.json)). The durable desktop/mobile case captured a
Library note's actual advertised href before activating it, then found a different
Library return focus in Reader. Library's click-capture handler wrote focus for
the note's paper. Its synchronous cache event rerendered return_to before Next
read the clicked href. The fix removes that implicit promotion. Explicit queue
selection still owns focus; clicking a different paper's question preserves the
launching Library view/focus, clicked version/anchor and saved Research identity.

The old unit test expected implicit promotion. Its replacement pins the entire
advertised href before/after activation, exact clicked source/version/anchor,
launching account/view cache and remount. Existing16 live assertions and API
request bodies are unchanged. No timeout, retry, floor or budget relaxed.

- [Unit red](unit-red.log):1failed/19passed before fix.
- [Focused green](unit-green.log):25passed across2files.
- [Exact CI fixture red](live-red.log):10passed,2failed,4serial dependents unrun.
- [Same fixture/build fix green](live-green.log):16passed,zero retries/skips.
- [Original failure index](original-browser-failures.json): unchanged local
  screenshots/traces, hash-bound. The prior40-work local pass did not expose this
  cross-paper case; it is preserved and does not supersede the failed CI cohort.

## Final gates

[Full frontend coverage](frontend-coverage.log):4,217passed/216files,zero skips;
98.20%statements,94.28%branches,93.88%functions,99.50%lines. Existing floors
98.15/94/93.4/99.11 unchanged. [Lint](lint.log),[typecheck](typecheck.log),
[production build](build.log) and [22/22budgets](budgets.log) pass. CSS24,688/25,600B;
Library168,997/169,984B; Projects169,959/169,984B; no ceiling raised.

[Required pre-push Python patch gate](python-patch-coverage.log):6,318passed,
54inherited local skips,53separate-tier deselections;98%patch. Unchanged backend
source16cc0220cd060cead41eecdf08d641e8d0705dcb; previous full e2e53/53,
simulation20/20$0 and registry260/0 remain separately source-attributed.

[Final64geometry/axe observations](../d1-d4-browser/final-layout/b261ddc/report.json)
pass across1440×1000/390×844,both themes and reduced-motion settings:zero
serious/critical violations,zero page exceptions/blocked requests. Each route,
new-paper full title/text clearance, stable positioning and disabled animation
under reduced motion checked. No authored writes in this matrix.
[Four readable journeys](../d1-d4-browser/owner-walkthrough/b261ddc/report.json)
and [four neutral untrimmed recordings](../d1-d4-browser/accepted/b261ddc/navigation-untrimmed/report.json)
pass at the same application. Earlier96-case authoring/failure/conflict/restart
proof remains attributed to cea881e; it is not relabelled as a new full matrix.

Fresh [documented-claims/hygiene](documented-claims.log):66/66passed;79local
Markdown targets resolve in the final edited guides.

## Actual recording review

Inspected the four actual decoded readable contact sheets and neutral contact
sheets, detailed mobile project/thread and desktop evidence captures, then
contiguous native frames64–131 per neutral clip. Brief fading/settling,
rapid-navigation supersession, stable shell/player, exact passage landings and
logical link focus reviewed. Reduced motion has separate browser assertions.
Original failed clips and unsuccessful local extraction-helper diagnostics remain
local; no decoder result alone is called a visual pass.

[Desktop project](../d1-d4-browser/owner-walkthrough/b261ddc/desktop-light/project-question.png),
[mobile project](../d1-d4-browser/owner-walkthrough/b261ddc/mobile-light/project-question.png),
[mobile thread](../d1-d4-browser/owner-walkthrough/b261ddc/mobile-dark/learning-thread.png),
[desktop motion](../d1-d4-browser/accepted/b261ddc/navigation-untrimmed/desktop-light/navigation.webm),
[mobile motion](../d1-d4-browser/accepted/b261ddc/navigation-untrimmed/mobile-dark/navigation.webm).
The full readable videos/Explore/profile images remain local because they contain
the copied personal profile. Publicly committed screenshots show agent-authored
examples; neutral recordings use an empty organizing question.

## Reproduce

From the worktree root, with the existing isolated stack healthy:

```bash
cd web
ANTHROPIC_API_KEY=local-preview-disabled npm test -- --coverage
ANTHROPIC_API_KEY=local-preview-disabled npm run lint
ANTHROPIC_API_KEY=local-preview-disabled npm run typecheck
ANTHROPIC_API_KEY=local-preview-disabled npm run build
node scripts/route-budgets.mjs
ANTHROPIC_API_KEY=local-preview-disabled \
WORKSPACE_LIVE_URL=http://127.0.0.1:3180 \
WORKSPACE_VERIFICATION_PRINCIPAL=modes-ci-click \
npx --no-install playwright test --config=live-workspace-e2e/playwright.config.ts --reporter=list
```

3180/API8180 uses the exact3-work synthetic CI seed, separate DB/principal.
3178 retains40real public works and three explicitly agent-authored examples;
3179 retains long mechanical stress fixtures. No owner3137data/services touched,
provider/count/source contacts0,recurrence/everyday generation off. Owner labels,
physical-device acceptance and usefulness remain pending. Browser storage outage
plus full reload can lose an unsaved draft after its warning. Grounded assistance
remains the separate D5 quality/spending milestone.
