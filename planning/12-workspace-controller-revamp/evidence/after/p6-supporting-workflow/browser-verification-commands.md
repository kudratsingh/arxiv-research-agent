# Final native browser reproduction commands

Run from `/private/tmp/arxiv-agent-eng-workspace-controller`, after the frozen
production build/static-copy signal. All API/provider configuration uses the
nonfunctional `local-preview-disabled` sentinel. Port3137/API8137/PG15438 and
owner data are outside these browser commands. Application source is bound in
[source-binding.json](source-binding.json); the frontend finalizer commits and
pushes separately. These browser commands create no commits, PRs or pushes.

The verification frontend was restarted only after `lsof -nP -iTCP:3149
-sTCP:LISTEN` identified its exact Node PID. The same procedure guards8149.
Commands below retain the actual dummy local authentication strings.

```bash
# API: substitute only the explicit fixture database suffix live or walk.
env ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
  ENABLE_WORKSPACE=true ENABLE_API_AUTH=true WORKSPACE_SCHEDULE_APPROVED=false \
  API_KEYS=controller-p6:sk_controller_p6_local_preview_disabled \
  POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_controller_p6_walk \
  WORKSPACE_RATE_DATABASE_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_controller_p6_walk \
  OMP_NUM_THREADS=1 \
  /Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
  -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8149 --no-access-log

# Frontend from web/. Omit WORKSPACE_SYNTHETIC_PREVIEW for live16/source-check.
env WORKSPACE_LIVE=1 WORKSPACE_PREVIEW=1 WORKSPACE_SYNTHETIC_PREVIEW=1 \
  ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
  WORKSPACE_SCHEDULE_APPROVED=false NEXT_TELEMETRY_DISABLED=1 \
  API_INTERNAL_BASE=http://127.0.0.1:8149 \
  ARXIV_API_KEY=sk_controller_p6_local_preview_disabled \
  HOSTNAME=127.0.0.1 PORT=3149 node .next/standalone/server.js

# Native sequence before write testing; final report observes zero writes.
NODE_PATH=$PWD/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/final-native-sequence.cjs
cp /private/tmp/p6-sequence-debug.json planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/final-native-sequence.json

# Read-only 3148 matrices, actual theme assertions, no external/non-GET traffic.
NODE_PATH=$PWD/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/motion-after.cjs
NODE_PATH=$PWD/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/reduced-motion.cjs
NODE_PATH=$PWD/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/p6-readonly-a11y.cjs
NODE_PATH=$PWD/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/navigation-focus.cjs

# Run from web/ with API8149 targeting p6_live and production wording.
env ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
  WORKSPACE_SCHEDULE_APPROVED=false WORKSPACE_VERIFICATION_PRINCIPAL=controller-p6 \
  WORKSPACE_LIVE_URL=http://127.0.0.1:3149 \
  npx playwright test -c live-workspace-e2e/playwright.config.ts

# Root cwd, same p6_live database; source responses fulfilled in browser only.
NODE_PATH=$PWD/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/intercepted-source-check.cjs

# Restart only3149/API8149 to p6_walk/synthetic mode before these writes.
NODE_PATH=$PWD/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/walkthrough.cjs

# Workflow creates a newer edition. Append long-first9 only with exact guards.
env ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
  WORKSPACE_OWNER=controller-p6 \
  POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_controller_p6_walk \
  WORKSPACE_RATE_DATABASE_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_controller_p6_walk \
  /Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
  < planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/motion-edition.py
NODE_PATH=$PWD/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/motion-record.cjs
```

The temporary immutable G5 build came from `git archive ade234b web`, extracted
to `/private/tmp/arxiv-agent-eng-g5-evidence`; only `web/node_modules` was
symlinked to the existing installed dependencies. Its own sentinel-only `npm
run build` and static-copy used its own `.next`. Its frontend3150 used the
unchanged synthetic preview API8148, and `motion-before.cjs` blocked all writes
and external requests. The twelve final before captures assert real themes.
3150 was stopped after exact PID verification and the temporary tree removed.
No8150 API was started. The controller build and sources were unchanged.

Raw logs use `browser-*.log`; structured final results use the corresponding
JSON files. Earlier failures remain under `pre-fix/`, including an incorrect
light capture labelled dark, nested candidate-schema assertion, mobile hidden
queue/overlay assumptions, and the edition guard refusing the newer workflow
edition. The wrong-import fixture append attempt failed before database access;
locked Python stdin then passed the source-import guard. These are excluded
from final acceptance. Initial video assertions passed but had a brief passage
frame; final videos add900ms of visible dwell after the geometry assertion.
