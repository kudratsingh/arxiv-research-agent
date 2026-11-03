const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const args = process.argv.slice(2);
  if (args.length !== 1 || !args[0].trim() || args[0].startsWith('-')) {
    throw new Error('Usage: THEME=light|dark DPR=1 BASE=http://127.0.0.1:3000 ITEM=<id> node shot.cjs <output-directory>');
  }
  const theme = process.env.THEME ?? 'light';
  if (!['light', 'dark'].includes(theme)) throw new Error('THEME must be light or dark');
  const dprText = process.env.DPR ?? '1';
  const dpr = Number(dprText);
  if (!dprText.trim() || !Number.isFinite(dpr) || dpr <= 0) throw new Error('DPR must be a positive finite number');
  const base = new URL(process.env.BASE || 'http://127.0.0.1:3000');
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) {
    throw new Error('BASE must be an HTTP(S) URL without credentials, query, or fragment');
  }
  const baseUrl = base.href.replace(/\/$/, '');
  const out = path.resolve(args[0]);
  await fs.mkdir(out, { recursive: true });
  const { chromium } = require('playwright');
  const routes = ['today', 'radar', 'library', 'interests', 'operations', 'review', 'items/' + encodeURIComponent(process.env.ITEM || 'ci:workspace-agent-evaluation')];
  const browser = await chromium.launch();
  try {
    for (const [name, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
      const ctx = await browser.newContext({ viewport, colorScheme: theme, deviceScaleFactor: dpr });
      try {
        await ctx.addInitScript((preference) => localStorage.setItem('arxiv-agent.theme', preference), theme);
        let refreshAttempted = false;
        await ctx.route('**/*', async (route) => {
          const request = route.request();
          const url = new URL(request.url());
          if (request.method() === 'POST' && /^\/api\/workspace\/refresh\/?$/.test(url.pathname)) {
            refreshAttempted = true;
            await route.abort('blockedbyclient');
            return;
          }
          await route.continue();
        });
        const page = await ctx.newPage();
        const errs = [];
        page.on('console', (message) => { if (message.type() === 'error') errs.push(message.text().slice(0, 160)); });
        for (const route of routes) {
          const response = await page.goto(`${baseUrl}/workspace/${route}`, { waitUntil: 'networkidle', timeout: 90000 });
          if (!response || !response.ok()) throw new Error(`Navigation failed for ${route}: ${response?.status() ?? 'no response'}`);
          await page.locator('main h1').first().waitFor({ state: 'visible', timeout: 90000 });
          await page.locator('main [aria-busy="true"]').waitFor({ state: 'hidden', timeout: 90000 });
          if (route === 'radar') await page.getByText('Loading this stored result window…').waitFor({ state: 'hidden', timeout: 90000 });
          const heading = await page.locator('main h1').first().innerText();
          if (/^(Workspace unavailable|This source is not in the loaded workspace\.|This retained source version is unavailable\.)$/.test(heading.trim())) {
            throw new Error(`${route} did not load workspace content: ${heading.trim()}`);
          }
          await page.waitForFunction((expected) => document.documentElement.getAttribute('data-theme') === expected && localStorage.getItem('arxiv-agent.theme') === expected, theme);
          if (refreshAttempted) throw new Error('Blocked forbidden POST /api/workspace/refresh');
          const file = path.join(out, `${name}-${theme}-${route.split('/')[0]}.png`);
          await page.screenshot({ path: file, fullPage: true });
          const summary = (await page.locator('main').innerText()).slice(0, 200).replace(/\s+/g, ' ');
          console.log(name, theme, route, response.status(), JSON.stringify(heading), '|', summary);
        }
        if (refreshAttempted) throw new Error('Blocked forbidden POST /api/workspace/refresh');
        if (errs.length) console.log('console errors', name, errs.slice(0, 5));
      } finally {
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
