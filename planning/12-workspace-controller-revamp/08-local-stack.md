# 08 · Run the live workspace locally (verified recipe)

**Verified 2026-11-03 in a Claude Code cloud container** (Linux, Postgres 16
binaries at `/usr/lib/postgresql/16/bin`, Python 3.13, Node 22, Chromium at
`/opt/pw-browsers`, no Docker daemon). The repo's own live Playwright suite
passed **16/16** against this stack. The full report, with file:line
evidence, is in [recon/06-runpath.md](recon/06-runpath.md).

Use this stack for:
- before and after **screenshots** of every `/workspace/*` route;
- **manual QA** in dark, light and mobile;
- running `live-workspace-e2e/*.spec.ts`, which the unit suite cannot cover.

> **Zero spend and no network writes.** `ANTHROPIC_API_KEY=local-preview-disabled`
> always. **Never click "Check sources now" against this stack.** `POST /workspace/refresh`
> fetches real feeds over the network. Both seeds below are offline.

## 0. Variables

```bash
REPO=/home/user/arxiv-research-agent          # your checkout
WORK=${WORK:-$HOME/ws-stack}                   # scratch dir outside the repo
VENV=$WORK/venv
PG=/usr/lib/postgresql/16/bin
PGDATA=/tmp/ws-pg/data
mkdir -p $WORK
```

## 1. Python environment (one time, about 5 GB, about 5 min)

The app imports torch, faiss and sentence-transformers at load time, so
they are required even though the workspace never uses them.

```bash
cd $REPO
uv venv --python 3.13 $VENV
grep -v -E "^(torch|sentence-transformers|transformers|faiss-cpu|nvidia|triton|tokenizers|safetensors|huggingface|scikit|scipy)" \
  requirements-runtime-lock.txt > $WORK/req-lite.txt
uv pip install --python $VENV/bin/python -r $WORK/req-lite.txt
uv pip install --python $VENV/bin/python faiss-cpu==1.14.3
uv pip install --python $VENV/bin/python "torch==2.12.1" --index-url https://download.pytorch.org/whl/cpu
uv pip install --python $VENV/bin/python sentence-transformers==5.6.0 transformers==5.13.0
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true $VENV/bin/python -c "import fastapi, src.api.app; print('ok')"
```

(The verified run used `--extra-index-url https://pypi.org/simple` for torch
and got the CUDA wheel, which works on CPU. The CPU-only line above is
smaller but was not run.)

## 2. Postgres on 127.0.0.1:15438 (one time, then start/stop)

```bash
mkdir -p /tmp/ws-pg && chown postgres:postgres /tmp/ws-pg && chmod 700 /tmp/ws-pg
runuser -u postgres -- $PG/initdb -D $PGDATA -U workspace --auth=trust -E UTF8
runuser -u postgres -- $PG/pg_ctl -D $PGDATA -l /tmp/ws-pg/pg.log -o "-p 15438 -k /tmp/ws-pg -c listen_addresses=127.0.0.1" -w start
$PG/createdb -h 127.0.0.1 -p 15438 -U workspace workspace        # CI-fixture DB (for live e2e)
$PG/createdb -h 127.0.0.1 -p 15438 -U workspace workspace_rich   # rich demo DB (for screenshots)
```

## 3. Backend environment

```bash
cd $REPO
export ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true ENABLE_WORKSPACE=true ENABLE_API_AUTH=true \
  WORKSPACE_SCHEDULE_APPROVED=false API_KEYS=e2e:sk_e2e_local_preview_disabled
DB=workspace_rich   # or: workspace  (CI fixture, required by live e2e)
export POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15438/$DB
export WORKSPACE_RATE_DATABASE_URL=$POSTGRES_URL
```

## 4. Seed (once per fresh database)

```bash
$VENV/bin/python -m src.workspace migrate

# CI fixture (3 works, sources not_checked, edition "ready partial") — DB "workspace":
WORKSPACE_E2E_SEED=1 E2E_PRINCIPAL=e2e $VENV/bin/python - < web/e2e/fixtures/workspace_seed.py

# Rich demo (14 works, 5/5 sources ok, 9-item "ready" edition at 45 min) — DB "workspace_rich":
WORKSPACE_OWNER=e2e WORKSPACE_MINUTES=45 $VENV/bin/python - < planning/12-workspace-controller-revamp/tools/rich_seed.py
```

About `tools/rich_seed.py`:
- It feeds **hand-written** RSS through the real intake parser with an
  injected transport. It refuses to run on a non-loopback DB or with a real
  key.
- Its arXiv IDs are `2611.99xxx`, which are not real papers.
- Quirks: arXiv items show "Publication date unknown", which is how the
  parser treats arXiv RSS dates. Re-running it adds new versions of the blog
  items.
- **For queue design, re-seed with `WORKSPACE_MINUTES=45`** to get a 9-item
  edition. 15 minutes gives about 3 items.

## 5. Start the API (:8000) and Next (:3000)

```bash
cd $REPO
setsid nohup $VENV/bin/python -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log \
  > $WORK/api.log 2>&1 < /dev/null &
until curl -fsS http://127.0.0.1:8000/healthz >/dev/null; do sleep 1; done

cd $REPO/web
WORKSPACE_LIVE=1 API_INTERNAL_BASE=http://127.0.0.1:8000 ARXIV_API_KEY=sk_e2e_local_preview_disabled NEXT_TELEMETRY_DISABLED=1 \
  setsid nohup npx --no-install next dev --webpack --hostname 127.0.0.1 --port 3000 > $WORK/web.log 2>&1 < /dev/null &
until curl -fsS http://127.0.0.1:3000/api/healthz >/dev/null; do sleep 1; done
curl -s http://127.0.0.1:3000/api/workspace/state | head -c 200     # expect "principal_key_id":"e2e"
```

- `WORKSPACE_LIVE` must be exactly `1`, or every live route is a 404.
- `ARXIV_API_KEY` must equal the secret half of `API_KEYS`. The proxy injects
  it server-side.

## 6. Screenshots

```bash
cd $REPO/web
mkdir -p $WORK/shots
ITEM=arxiv:2611.99100 NODE_PATH=$(npm root -g) node ../planning/12-workspace-controller-revamp/tools/shot.cjs $WORK/shots
```

- This captures 7 routes × desktop 1440×1000 and mobile 390×844, full page.
- Use `ITEM=ci:workspace-agent-evaluation` on the CI DB.
- To hide the Next dev badge, add
  `await page.addStyleTag({content:'nextjs-portal{display:none!important}'})`
  before each screenshot.
- **Theme.** The tool captures the OS default (light). For dark captures, set
  `colorScheme: 'dark'` in `browser.newContext`. For an explicit preference,
  run `localStorage.setItem(<THEME_STORAGE_KEY>, 'dark')` from
  `web/lib/tokens.ts` before navigation, then reload.
- **For the owner,** use `deviceScaleFactor: 2`. Use 1 for your own checks.
- Commit the "after" set to `planning/12-workspace-controller-revamp/evidence/after/`.

## 7. Live e2e regression gate

The repo pins `@playwright/test` 1.62.1, which expects `chromium-1234`, but
the container ships 1243. Symlink them:

```bash
PWB=$WORK/pw-browsers; mkdir -p $PWB
ln -sfn /opt/pw-browsers/chromium-1243 $PWB/chromium-1234
ln -sfn /opt/pw-browsers/chromium_headless_shell-1243 $PWB/chromium_headless_shell-1234
ln -sfn /opt/pw-browsers/ffmpeg-1011 $PWB/ffmpeg-1011
# backend must be on DB=workspace (CI fixture), principal e2e, 5 sources
cd $REPO/web
PLAYWRIGHT_BROWSERS_PATH=$PWB WORKSPACE_LIVE_URL=http://127.0.0.1:3000 \
  npx --no-install playwright test --config=live-workspace-e2e/playwright.config.ts --reporter=line
```

- Baseline: **16 passed (1.9 min)** on `916f038`.
- The suite writes notes into the DB. Drop and re-seed the `workspace` DB
  between runs if a spec depends on a clean state.

## 8. Stop everything

**Don't use `pkill -f`**: it matched and killed the agent's own shell
during verification.

```bash
for p in $(ps -eo pid,cmd | awk '/[u]vicorn src.api.app/{print $1} /[n]ext-server|[n]ext dev --webpack/{print $1}'); do kill $p; done
runuser -u postgres -- $PG/pg_ctl -D $PGDATA -m fast stop
```

## 9. Repo launchers that do not fit this container

- `scripts/workspace-local.sh` needs Docker and has a hard-coded macOS venv
  path.
- `web/e2e/support/stack.sh seed-workspace` needs Docker.
- `web/playwright.workspace.config.ts` is the **fictional preview** tier
  (`/today`), not `/workspace/*`.
- **`web/scripts/workspace-seed.mjs` rewrites the tracked
  `web/lib/daily/topics.json`. Do not run it.**
