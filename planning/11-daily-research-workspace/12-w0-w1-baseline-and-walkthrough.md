# W0/W1 baseline and owner walkthrough

Date: 2026-11-02. Branch: `codex/daily-workspace-preview`.
This is the first reviewable milestone, not acceptance of the full product.

## What is runnable

From the isolated worktree's `web/` directory:

```bash
npm run dev:workspace
# Open http://127.0.0.1:3126/today
```

For the production build, `npm run build`, then `npm run preview:workspace`
serves the same preview on `http://127.0.0.1:3127/today`. Both commands bind to
loopback, force the disabled model key and point the legacy API proxy at a
closed loopback port. There is no backend dependency for this milestone.
The ordinary application keeps these new routes off unless
`WORKSPACE_PREVIEW=1`; existing query and guided-learning routes remain intact.

The source material, dates and coverage checks are fictional and labelled.
The owner's editable interests and question are real inputs. The interface
never describes these sample abstracts as generated analysis or current news.

## Review this connected loop

1. Open Interests. The core lens covers agentic systems, retrieval/knowledge,
   evaluation and efficient inference. Rocket Twin has its own prepared watch;
   spatial AI/Unreal is a lighter exploration stream. Search any of the 384
   catalogue entries or browse all 26 field anchors. Edit the research question.
2. Open Today. Choose 5, 15 or 45 minutes. Inspect “Why this appeared” and open
   the source-coverage disclosure. A failed check remains distinct from no news.
3. Open the retrieval-evaluation source. Inspect the available abstract and its
   limitations. On a phone switch between Source, Understand and Your notes.
4. Edit and save a question, note or proposed next action. Edit that saved entry
   once more. Return to Today and follow the recorded thread back to its source.
5. Reload, use browser back/forward, and resume from Library at the saved anchor.
   Export notes as Markdown. The preview stores them only in this browser;
   blocked storage produces an explicit unsaved-session state.

## Baseline and checks

The shared checkout was at `dbd4bb8`, with the kit already uncommitted. Remote
`main` was verified at `88d283d`; implementation starts there in its own
worktree. Incoming archive contents matched the supplied planning files and
passed archive integrity. The owner checkout was not advanced or reset.

The latest remote CI run, `41434132708`, failed dependency audit and cancelled
Python tests. That remains historical baseline evidence, not a green CI run.
Production high/critical findings were fixed in this branch: Next.js/config
16.4.4, sharp 0.35.5, source-map-js 1.2.2. The production audit now reports zero
high/critical findings. Storybook is patched to 10.6.5, Zod to 4.6.6, and
compatible transitive security patches are in the lockfile.

The full high/critical audit is now green with an empty exceptions list.
The remaining inherited toolchain findings were removed by explicit development
pins: Lighthouse 13.6.0, tmp 0.2.7 and basic-ftp 6.2.5, together with the
compatible minimatch/brace-expansion update. The same graph was installed in a
disposable directory first and ran successfully through `lhci collect` against
the loopback production Today page. All seven obsolete exceptions were removed;
the audit implementation and thresholds are unchanged. Moderate findings remain
visible in the report; this is not a claim of zero vulnerabilities.

Lighthouse is a changed measurement instrument: the prior pin was 12.6.1.
One desktop compatibility collection on this machine reported performance 0.98,
accessibility 1.0 and best practices 1.0 with 13.6.0 and no runtime error.
That single observation is not the historical nightly matrix or a performance
comparison with the older instrument. Thresholds are retained; future readings
must carry the recorded Lighthouse version before comparison. No report was
uploaded and no external service was enabled.

Verification receipts and screenshots are local under `web/build/workspace/`.
`npm run e2e:workspace` runs the actual routes at desktop and 390 px with source
failure, saved-question reload, back/forward, export, API-call tripwire, axe and
dark-theme checks. The complete Vitest/Storybook coverage gate and route budget
report remain unchanged in their enforcement. Final run totals live in STATUS. The dedicated browser suite is integrated in
CI and isolated from the original seeded-stack suite.

All pre-existing JavaScript ceilings are retained. Four new routes have a
160 KiB gzip allowance. Their initial measurements are 152,994–156,705 B.
The route group's dedicated client template avoids attributing the draft
shell boundary to legacy routes. All emitted CSS measures 15,016 B versus
11,518 B on the same patched dependencies without the preview. Its allowance
moves to 15,872 B; the derived aggregate follows. The ratchet entry in
`web/budgets.json` records the reason and measurements.

## Next reversible storage/intake work

W2 uses the existing explicit operator principal and Postgres pool. Start with
versioned interests, canonical work/version/source observations and owner-scoped
reading state/questions. A user edit carries a revision guard. Topic selection
and connector activation remain separate. Import preview notes explicitly;
retain browser export until the import is confirmed. Do not move private notes
into logs, provider context or shared metadata records.

W3 uses bounded source fixtures before enabling an arXiv/feed adapter, with
identity, redirects, quotas and restart receipts. W4/W5 give real metadata and
manual reading the same continuity path. W6 needs a real worker and the owner's
check time before scheduling. These do not spend model credits.

W7 repairs source retention, factual-support naming, actual settings,
calibration artifact integration and cost semantics. W8/W9 then enable real
grounded summaries and guided deep dives only after a concrete model/source/
call/budget approval, retained-span checks and an actual provider walkthrough.
The fixture milestone does not satisfy those rows. Hardware remains unknown
for experiment feasibility. No code execution, public publishing or external
notification is part of this milestone.
