# G6 supporting screens and focused-paper refinement

This is an offline design-preview checkpoint. All papers and source receipts in
this evidence set are synthetic. The public owner workspace on port 3137 was not
used for write testing. Provider contacts, model spend and recurring checks are
zero/disabled. See the final gate record in [STATUS](../../../STATUS.md) for exact
source and evidence commits, raw checks and remaining work.

## Try the running preview

Open <http://localhost:3148/workspace/today>. The persistent notice says
“Design preview · synthetic sample papers.” This preview uses its own
`controller-p6-preview` account and `workspace_controller_p6_preview` database.
Its ten candidate usefulness labels remain blank.

1. In Today, choose a queue row or use Previous/Next, J/K. Scroll halfway down the
   long synthetic abstract before changing papers. The paper header lands at a
   consistent inset while the player and surrounding shell stay in place.
2. Open Reader. Source, Understand and Your notes retain their existing evidence
   boundaries. Exact saved-entry and passage links take precedence over generic
   route headings. Return to the originating view and focused paper.
3. In Interests, use the section index; change the question, streams or terms.
   Save/Discard belong to the original native form through their form attribute.
   Local draft recovery is account-specific; failed and conflicting writes do
   not become saved preferences. The catalogue loads separately.
4. In Sources & checks, select a source and inspect its timestamp and receipt.
   Live source-check buttons are disabled in this synthetic preview. Schedule
   preferences remain editable and every save keeps recurrence disabled.
5. In Review, all candidate forms stay mounted in packet order. Navigate the
   queue without losing drafts. Keys 1/2/3 choose a label; only the candidate’s
   explicit Save judgment button submits it. Leave the preview labels blank;
   automated labels exist only in separate verification accounts.

For browser write reproductions, use the guarded scripts against the separate
3149/API8149 verification service, never the preview or owner account. The
scripts check account identity and fixture shape and block unexpected writes,
source refresh and external requests. `intercepted-source-check.cjs` explicitly
fulfills refresh requests using captured synthetic responses; it never forwards
them to the backend or a public feed.

## Evidence

Text command transcripts retain the emitted messages and measurements; only
trailing whitespace and carriage-return progress formatting are normalized for
version control. JSON, images and actual WebM bytes retain their recorded data.

- `fixture-setup.json`: accounts, databases, immutable edition identities and
  synthetic long-source provenance.
- `baseline/` and `baseline-audit.json`: supporting screens before P6.
- `motion-before/` and `motion-before.json`: G5 paper surface, same work/version
  and viewports as the final `motion-after/` captures.
- `p6-readonly-a11y-preflight-build2.json`: explicitly preliminary browser scan;
  it is not final-head acceptance.
- Final build was frozen after ReaderQueue splitting and static copy. Browser
  acceptance below uses those exact application bytes, now committed at
  `fda9d7616e8cbd0d882bcc41510a997ade117bf9`. [Source binding](source-binding.json)
  records the web tree and unchanged file hashes. Browser verification changed
  only evidence scripts/files; the finalizer made the bounded source commits.
- [Exact commands and fixture/service boundaries](browser-verification-commands.md).
  [Live16 raw log](browser-live16.log) and [structured result](browser-live16-results.json):
  **16 passed (20.8s)** using p6_live. These are real loopback API/Postgres UI
  tests with synthetic fixtures, including the existing explicit zero-dollar
  synthetic request test; they do not invoke a provider.
- [Native sequence](final-native-sequence.json), [raw trace](final-native-sequence.log):
  Today → Radar page2 → direct Today → immediate mid-abstract native Read click
  → Back → Forward → same-document far hash. Back restores870px on desktop;
  no cold-reload workaround or clamping exception is used.
- [Final actual video metrics](motion-record.json), [raw log](browser-motion-record.log),
  [decode/frame review](video-review.json): **2/2 pass**, desktop dark1440×1000
  and mobile light390×844. Queue/J/K headings settle at16px; J/J/K completes in
  less than170ms and the last requested paper wins. The exact20 Unicode
  characters at retainedv1 `abstract:2500:2520` land near16px and above the
  player. Dismiss/Undo makes exactly4 reversible reading writes in this final
  run, restoring saved state. The videos retain real loading frames and add a
  900ms visual hold only after the far-passage geometry assertion passes.
- [Final read-only audit](p6-readonly-a11y.json), [raw log](browser-readonly.log):
  **28 route/theme/viewport cases plus2 tablet cases pass**, zero axe violations
  of any severity. The ten preview usefulness labels stay blank and unchanged
  in every before/after label check. Twelve supporting-screen captures are in
  [p6-readonly-support/](p6-readonly-support/).
- [Supporting workflows](walkthrough-audit.json), [raw log](browser-workflow.log):
  **10/10 pass** across both viewports: actual failed-save/reload recovery,
  real409 conflict with local text retained, disabled-schedule form submission,
  Review drafts without autosave, explicit synthetic judgment save, exact
  packet return and lazy Reader queue/version links. Four expected503/409
  console messages are recorded; unexpected console/page/request failures are0.
- [Source-check UI](intercepted-source-check.json), [raw log](browser-source-check.log):
  **2/2 pass**, captured synthetic responses for `[]` and `[arxiv-cs-lg]`;
  **zero refresh requests forwarded**. This is UI evidence, not source freshness.
- [Native focus/announcement](navigation-focus.json), [raw log](browser-focus.log):
  **2/2 pass**: player retains focus through paper change, polite position
  announcement updates, and explicit Interests navigation focuses its unique
  routeh1 at16px on desktop/mobile.
- [Reduced motion](reduced-motion.json), [raw log](browser-reduced-motion.log):
  **4/4 pass**, zero article animations with the actual reduced-motion media query.
- [Matched before](motion-before.json), [after](motion-after.json): **12/12 each**,
  same synthetic work/version in Today/Radar/Library, both themes and both
  viewports. Every final capture asserts actual HTML theme and painted canvas
  color. The before build is immutable G5`ade234b48520782d32e388e16a3cb811f8a2cf2b`,
  reconstructed separately from git archive; its own build never writes the
  controller's .next. Temporary3150 is closed and its temporary build removed.
  The final edition append is recorded in [browser-motion-edition.log](browser-motion-edition.log):
 9 items/28 works, new edition`2b6ebe5404014ef492e30adced95bb7f`; all original
  editions are preserved.

| Actual recording | Exact retained-passage frame | Decoded contact sheet |
| --- | --- | --- |
| [Desktop dark WebM](recordings/desktop-dark.webm) ·11.60s | [9.0s frame](recordings/desktop-dark-far-frame.png) | [Frames](recordings/desktop-dark-contact.png) |
| [Mobile light WebM](recordings/mobile-light.webm) ·10.68s | [9.0s frame](recordings/mobile-light-far-frame.png) | [Frames](recordings/mobile-light-contact.png) |

| View | Desktop light | Desktop dark | Mobile light | Mobile dark |
| --- | --- | --- | --- | --- |
| Today | [Before](motion-before/desktop-light-today.png) · [After](motion-after/desktop-light-today.png) | [Before](motion-before/desktop-dark-today.png) · [After](motion-after/desktop-dark-today.png) | [Before](motion-before/mobile-light-today.png) · [After](motion-after/mobile-light-today.png) | [Before](motion-before/mobile-dark-today.png) · [After](motion-after/mobile-dark-today.png) |
| Radar | [Before](motion-before/desktop-light-radar.png) · [After](motion-after/desktop-light-radar.png) | [Before](motion-before/desktop-dark-radar.png) · [After](motion-after/desktop-dark-radar.png) | [Before](motion-before/mobile-light-radar.png) · [After](motion-after/mobile-light-radar.png) | [Before](motion-before/mobile-dark-radar.png) · [After](motion-after/mobile-dark-radar.png) |
| Library | [Before](motion-before/desktop-light-library.png) · [After](motion-after/desktop-light-library.png) | [Before](motion-before/desktop-dark-library.png) · [After](motion-after/desktop-dark-library.png) | [Before](motion-before/mobile-light-library.png) · [After](motion-after/mobile-light-library.png) | [Before](motion-before/mobile-dark-library.png) · [After](motion-after/mobile-dark-library.png) |

Earlier application failures and capture-harness mistakes are retained in
[pre-fix/](pre-fix/), excluded from acceptance. In particular, the first recording
labelled dark painted light because its context omitted explicit colorScheme;
final evidence corrects this and checks both the attribute and painted color.
The two Reader-context harness errors used the wrong candidate nesting and a
hidden mobile queue; final verification opens the actual drawer and checks all
packet identities/version links. A newer edition after workflow was rejected
before any recording writes; the bounded fixture append restored the proper
long-first edition. No fixture guard or application requirement was weakened.

## Known limits retained for review

- Browser/client Back-Forward navigation is not a complete unsaved-draft guard.
  This pass restores scroll/list context; it does not claim to solve all draft
  history behavior. Review warns to save/copy drafts before browser history.
- CSS remains above its original ceiling under the owner-approved interim E27
  exception. Removing legacy stylesheet duplication and final consolidation
  remain G7 work. JavaScript ceilings and coverage floors are unchanged.
- These are Chromium desktop/mobile viewport checks, not physical-device tests.
- Fake or synthetic results do not qualify a model/checker or establish real
  source freshness, personal usefulness or comprehensive monitoring.
- This frontend phase performs no provider qualification or paid generation;
  the separately authorized qualification is owned outside this evidence set.
  Recurrence stays disabled. No PR is opened or merged for this frontend phase.

## Restart only this preview

The isolated Postgres service from the kit must already be running on 15458 and
its seeded database must be retained. These commands use its synthetic account;
they do not start, stop or configure the owner’s 3137 service.

From the worktree root, build and copy assets before starting the frontend:

```bash
cd /private/tmp/arxiv-agent-eng-workspace-controller/web
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true NEXT_TELEMETRY_DISABLED=1 npm run build
python3 - <<'PY'
import shutil
from pathlib import Path
shutil.copytree('.next/static', '.next/standalone/.next/static', dirs_exist_ok=True)
if Path('public').is_dir():
    shutil.copytree('public', '.next/standalone/public', dirs_exist_ok=True)
PY
```

Terminal 1 (the local API):

```bash
cd /private/tmp/arxiv-agent-eng-workspace-controller
env ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
  ENABLE_WORKSPACE=true ENABLE_API_AUTH=true WORKSPACE_SCHEDULE_APPROVED=false \
  API_KEYS=controller-p6-preview:sk_controller_p6_preview_local_preview_disabled \
  POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_controller_p6_preview \
  WORKSPACE_RATE_DATABASE_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_controller_p6_preview \
  OMP_NUM_THREADS=1 \
  /Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
  -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8148 --no-access-log
```

Terminal 2 (the compiled frontend):

```bash
cd /private/tmp/arxiv-agent-eng-workspace-controller/web
env WORKSPACE_LIVE=1 WORKSPACE_PREVIEW=1 WORKSPACE_SYNTHETIC_PREVIEW=1 \
  ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
  WORKSPACE_SCHEDULE_APPROVED=false NEXT_TELEMETRY_DISABLED=1 \
  API_INTERNAL_BASE=http://127.0.0.1:8148 \
  ARXIV_API_KEY=sk_controller_p6_preview_local_preview_disabled \
  HOSTNAME=127.0.0.1 PORT=3148 node .next/standalone/server.js
```

Use Ctrl-C in those two terminals to stop this preview. If either port is already
occupied, inspect that exact listener first; do not terminate arbitrary services
or the owner’s 3137/8137 processes.
