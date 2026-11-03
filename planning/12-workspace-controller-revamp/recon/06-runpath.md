> **Kit note (2026-11-03):** this is the verbatim run-path report. Paths under the session scratchpad (`/tmp/claude-0/.../scratchpad`) do not survive the session. The seed and screenshot scripts now live in [`../tools/`](../tools/), and the generalised recipe is [`../08-local-stack.md`](../08-local-stack.md).

I got the live workspace running here with seeded data, served it through `next dev`, took screenshots of every `/workspace/*` route, and ran the repo's own live Playwright suite against it: 16 of 16 passed in 1.9 minutes. Everything I started is stopped again. No tracked files were changed by me.

**Short answer:** a full offline backend works in this container. It does need some setup, because the repo's own launchers depend on Docker and a macOS path, and neither works here.

## Why the repo's launchers can't be used as-is
- **Docker isn't running here.** The client is installed but `/var/run/docker.sock` is missing. That blocks `scripts/workspace-local.sh` (`:32`, `:48`) and `web/e2e/support/stack.sh seed-workspace` (`:115-125`).
- **`scripts/workspace-local.sh:6` hard-codes a macOS path** for `VENV_PYTHON`.
- **Python dependencies were not installed.** `import fastapi` failed. The app also imports torch and faiss at load time (`src/tools/embeddings.py:42`, `src/tools/chunk_ranker.py:15`), so those are needed too.
- **What is available:** Postgres 16 at `/usr/lib/postgresql/16/bin`, `redis-server` (not needed), Python 3.13.18, Node 22.23.4, Next 16.4.4, and Chromium in `/opt/pw-browsers`.

## What the backend requires (`src/workspace/routes.py`)
- The router has prefix `/workspace` (`:55`) and is mounted at `src/api/app.py:1340-1342`.
- `owner()` (`:59-67`):
  - `ENABLE_WORKSPACE` unset gives 404 `workspace_disabled`. The default is False (`src/config.py:1580`).
  - Auth off makes `require_principal` return None (`src/api/auth.py:629-630`), which gives 403. So `ENABLE_API_AUTH=true` and `API_KEYS=name:secret` are mandatory.
- `repository()` (`:70-76`) returns 503 without `POSTGRES_URL`.
- Endpoints: `GET /state` (`:110`), `POST /profile` (`:116`), `/reading` (`:122`), `/entries` (`:128`), `GET /review` (`:134`), `POST /refresh` (`:250`), `POST /edition` (`:257`), `GET /items` (`:263`), `GET /materials` (`:210`, `:216`), `/generation/jobs` (`:180`).
- **Avoid `POST /refresh`** ("Check sources" in the UI). It calls the real `fetch_source` over the network (`:245`). The seeds below never do.
- An edition only includes works fetched in the last 7 days (`prepare_edition`, `:225-230`).

## What the Next side requires
- **`WORKSPACE_LIVE` must be exactly `"1"`** when the server runs, or every live route returns 404 (`web/app/(live)/layout.tsx:8`). The Shell is applied in `template.tsx:20`.
- **Request path:** `requestWorkspaceJSON` (`web/lib/api/client.ts:51-65`) sends `/api/workspace/<path>` as GET, or POST when there is a body. The catch-all proxy forwards it to `API_INTERNAL_BASE`, defaulting to `http://localhost:8000` (`app/api/[...path]/route.ts:210`).
- **The API key is injected server-side.** The proxy adds `X-API-Key` from `ARXIV_API_KEY` (`route.ts:158-166`, `lib/server/principal.ts:141-150`). It must equal the secret half of `API_KEYS`; the name half becomes `principal_key_id`.
- **Proxy errors:** an unreachable upstream gives 502 (`route.ts:181-186`), which the UI shows as "The local workspace is unavailable" (`lib/workspace/api.ts:64`).
- **CSP is off in dev** (`lib/server/csp.ts:163-169`) and enforced in production builds.

## Seed options
1. **CI fixture: `web/e2e/fixtures/workspace_seed.py`.**
   - Guard (`:22-36`) needs `WORKSPACE_E2E_SEED=1`, `ENABLE_WORKSPACE=true`, `USE_MOCK_DATA=true`, `ANTHROPIC_API_KEY=local-preview-disabled`, and `E2E_PRINCIPAL`.
   - It writes 3 works / 4 versions with titles like "CI fixture — …" (`:39-101`), sets every source to `not_checked` (`:163-176`), and freezes an edition (`:177-182`).
   - It refuses to run on a database containing non-fixture data (`:127-131`), so it needs its own database.
   - Result: 15-minute edition, 3 items, "ready partial", source checks 0 of 5.
2. **Richer offline seed I wrote (not in the repo):** `/tmp/claude-0/-home-user-arxiv-research-agent/a2a832ec-056f-594b-8dc7-0ad1dc9cbee5/scratchpad/rich_seed.py`.
   - It feeds hand-written arXiv and blog RSS through the real parser and `fetch_source(..., transport=...)` (`src/workspace/intake.py:555-563`, `:102-108`). URL checks there do no DNS lookup (`:223-229`), so it is fully offline.
   - Then it calls `store.ingest` and `prepare_edition`.
   - Result: 14 works, all 5 sources "success", and with `WORKSPACE_MINUTES=45` a 9-item edition, "ready".
   - arXiv IDs are in the 2611.99xxx range so they don't match real papers. Titles and authors are made up.
   - Known quirks: arXiv items show "Publication date unknown", which is how the parser treats arXiv RSS dates (`intake.py:440-444`). Re-running it adds new versions of the blog items, because their dates are relative to "now".

## Commands (all run and checked here)
```bash
REPO=/home/user/arxiv-research-agent
SP=/tmp/claude-0/-home-user-arxiv-research-agent/a2a832ec-056f-594b-8dc7-0ad1dc9cbee5/scratchpad
VENV=$SP/venv          # already built (4.9 GB); reuse it

# (0) One-time Python env — already done. What I ran:
#   uv venv --python 3.13 $VENV
#   grep -v -E "^(torch|sentence-transformers|transformers|faiss-cpu|nvidia|triton|tokenizers|safetensors|huggingface|scikit|scipy)" $REPO/requirements-runtime-lock.txt > $SP/req-lite.txt
#   uv pip install --python $VENV/bin/python -r $SP/req-lite.txt
#   uv pip install --python $VENV/bin/python faiss-cpu==1.14.3
#   uv pip install --python $VENV/bin/python torch==2.12.1 --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple   # resolved to the CUDA build from PyPI; works on CPU
#   uv pip install --python $VENV/bin/python sentence-transformers==5.6.0 transformers==5.13.0
#   Untested, smaller: drop --extra-index-url to get the CPU wheel, as Dockerfile:54-58 does.

# (1) Postgres on 127.0.0.1:15438 (the data dir already exists; initdb + createdb were one-time)
PG=/usr/lib/postgresql/16/bin
#   mkdir -p /tmp/ws-pg && chown postgres:postgres /tmp/ws-pg && chmod 700 /tmp/ws-pg
#   runuser -u postgres -- $PG/initdb -D /tmp/ws-pg/data -U workspace --auth=trust -E UTF8
runuser -u postgres -- $PG/pg_ctl -D /tmp/ws-pg/data -l /tmp/ws-pg/pg.log -o "-p 15438 -k /tmp/ws-pg -c listen_addresses=127.0.0.1" -w start
#   $PG/createdb -h 127.0.0.1 -p 15438 -U workspace workspace        # CI fixture DB (now also has notes from the e2e run)
#   $PG/createdb -h 127.0.0.1 -p 15438 -U workspace workspace_rich   # richer seed DB

# (2) Backend env. Choose the DB: workspace_rich for screenshots, workspace for the live e2e suite.
cd $REPO
export ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true ENABLE_WORKSPACE=true ENABLE_API_AUTH=true \
  WORKSPACE_SCHEDULE_APPROVED=false API_KEYS=e2e:sk_e2e_local_preview_disabled \
  POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15438/workspace_rich
export WORKSPACE_RATE_DATABASE_URL=$POSTGRES_URL

# (3) Seed — already done for both DBs. Re-run only on a fresh DB:
#   CI DB:   $VENV/bin/python -m src.workspace migrate && WORKSPACE_E2E_SEED=1 E2E_PRINCIPAL=e2e $VENV/bin/python - < web/e2e/fixtures/workspace_seed.py
#   rich DB: WORKSPACE_OWNER=e2e WORKSPACE_MINUTES=45 $VENV/bin/python - < $SP/rich_seed.py

# (4) API on :8000 (about 5–10 s to /healthz because of the torch import)
setsid nohup $VENV/bin/python -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log > $SP/api.log 2>&1 < /dev/null &
until curl -fsS http://127.0.0.1:8000/healthz >/dev/null; do sleep 1; done

# (5) Next dev on :3000 with WORKSPACE_LIVE=1
cd $REPO/web
WORKSPACE_LIVE=1 API_INTERNAL_BASE=http://127.0.0.1:8000 ARXIV_API_KEY=sk_e2e_local_preview_disabled NEXT_TELEMETRY_DISABLED=1 \
  setsid nohup npx --no-install next dev --webpack --hostname 127.0.0.1 --port 3000 > $SP/web.log 2>&1 < /dev/null &
until curl -fsS http://127.0.0.1:3000/api/healthz >/dev/null; do sleep 1; done
curl -s http://127.0.0.1:3000/api/workspace/state | head -c 200   # expect "principal_key_id":"e2e"

# (6) Screenshots: 7 routes (today, radar, library, interests, operations, review, items/[id]) × desktop 1440x1000 / mobile 390x844, full page
ITEM=arxiv:2611.99100 NODE_PATH=$(npm root -g) node $SP/shot.cjs $SP/shots-rich
#   For the CI DB use ITEM=ci:workspace-agent-evaluation.
#   To hide the Next dev "N" badge: await page.addStyleTag({content:'nextjs-portal{display:none!important}'})

# (7) Regression gate: the repo's live suite. The repo's @playwright/test 1.62.1 expects chromium-1234; only 1243 is installed, so $SP/pw-browsers holds symlinks to it.
PLAYWRIGHT_BROWSERS_PATH=$SP/pw-browsers WORKSPACE_LIVE_URL=http://127.0.0.1:3000 \
  npx --no-install playwright test --config=live-workspace-e2e/playwright.config.ts --reporter=line
#   Run against POSTGRES_URL=.../workspace (CI DB): 16 passed (1.9m). It writes notes into that DB and needs principal "e2e" with 5 sources (live.spec.ts:13-20).

# (8) Stop. Don't use pkill -f: it matched my own shell and killed it.
for p in $(ps -eo pid,cmd | awk '/[u]vicorn src.api.app/{print $1} /[n]ext-server|[n]ext dev --webpack/{print $1}'); do kill $p; done
runuser -u postgres -- $PG/pg_ctl -D /tmp/ws-pg/data -m fast stop
```

## Verified vs. inferred
**Verified:**
- `/healthz` reports postgres ok. `/workspace/state` returns 401 without a key and 200 with it, and also 200 through the Next proxy.
- All 7 routes return 200 on desktop and mobile with real content. On the rich DB, Today shows "9 items · ready" and "Source checks: 5 of 5 available".
- The live suite passed 16/16.
- After the e2e run, Today's "Continue your question" shows a saved question, which is useful for that state.
- Screenshots are in `$SP/shots/` (CI DB) and `$SP/shots-rich/` (rich DB). `$SP/shots/desktop-today-noindicator.png` shows the badge hidden.

**Inferred, not tested:**
- The CPU-only torch install path.
- A production build (`npm run build` plus standalone, like `scripts/workspace-local.sh:73-77`) with CSP enforced.
- The live suite against the rich DB.

## Repo options that don't fit
- **`web/playwright.workspace.config.ts`** is the preview tier: `WORKSPACE_PREVIEW=1`, route `/today` (gated by `app/(daily)/layout.tsx:4`), with a dead upstream `http://127.0.0.1:9`. It renders the fictional daily preview UI, not the live `/workspace/*` Shell.
- **`web/scripts/workspace-seed.mjs`** doesn't seed data. It rewrites the tracked file `web/lib/daily/topics.json` (`:3-6`). Don't run it.
- **`web/e2e/support/stub-upstream.mjs`** only answers `/healthz` and returns 404 for everything else (`:55-58`).

## Lighter alternative (not built)
Intercept `**/api/workspace/**` with Playwright's `page.route` and return JSON captured from the real API. The GET calls the UI makes are:
- `state` (`lib/workspace/useWorkspace.ts:13,24`)
- `items?…` (`components/workspace/Radar.tsx:74`)
- `review?packet_id=` (`CandidateReview.tsx:31`)
- `materials?work_id&version_id` and `materials/{id}` (`RetainedSource.tsx:84,126,143`)
- `generation/jobs` (`SyntheticWorkbench.tsx:216`)

The UI also POSTs when you act: changing 5/15/45 posts `profile` then `edition` (`Today.tsx:123-124`). Response types come from `lib/api/generated/schema`. Since the real backend works, I'd use it instead.

## Notes
- The scratch venv is 4.9 GB. The Postgres data dir is `/tmp/ws-pg/data` (stopped), holding the `workspace` and `workspace_rich` databases.
- Staged renames from `docs/handoff/` to `planning/12-workspace-controller-revamp/` and untracked planning files showed up in `git status` during my run. The tree was clean when I started, and I didn't make them.

Files are in /tmp/claude-0/-home-user-arxiv-research-agent/a2a832ec-056f-594b-8dc7-0ad1dc9cbee5/scratchpad:
- rich_seed.py
- shot.cjs
- shots/
- shots-rich/
- pw-browsers/
- venv/