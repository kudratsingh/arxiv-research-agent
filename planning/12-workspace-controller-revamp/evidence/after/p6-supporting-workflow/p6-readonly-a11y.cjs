// Read-only P6 audit: synthetic preview only; every non-GET/HEAD and external request is blocked.
const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = 'http://127.0.0.1:3148';
const dir = path.resolve('planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow');
const id = 'arxiv:2611.99800';
const suffix = process.env.P6_AUDIT_PREFLIGHT === '1' ? '-preflight-build2' : '';
const report = { base, build: suffix ? 'P6 Build 2 preflight' : 'P6 final build', fixture: 'controller-p6-preview synthetic sample', cases: [], tablet: [], labelChecks: [], blocked: [], errors: [] };
(async () => {
  await fs.mkdir(path.join(dir, `p6-readonly-support${suffix}`), { recursive: true });
  const browser = await chromium.launch();
  try {
    for (const [size, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) for (const theme of ['light', 'dark']) {
      const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, colorScheme: theme });
      await ctx.addInitScript(t => localStorage.setItem('arxiv-agent.theme', t), theme);
      let active = `${size}-${theme}`;
      await ctx.route('**/*', route => { const req = route.request(), url = new URL(req.url()); if (url.origin !== base || !['GET', 'HEAD'].includes(req.method())) { report.blocked.push({ active, method: req.method(), url: url.origin + url.pathname }); return route.abort('blockedbyclient'); } return route.continue(); });
      const page = await ctx.newPage();
      page.on('pageerror', e => report.errors.push({ active, kind: 'pageerror', text: String(e) }));
      page.on('console', m => { if (m.type() === 'error') report.errors.push({ active, kind: 'console', text: m.text() }); });
      page.on('requestfailed', req => { const url = new URL(req.url()), error = req.failure()?.errorText; if (!(req.method() === 'GET' && url.origin === base && url.searchParams.has('_rsc') && error === 'net::ERR_ABORTED')) report.errors.push({ active, kind: 'requestfailed', url: req.url(), text: error }); });
      try {
        const first = await page.goto(`${base}/workspace/today?focus=${encodeURIComponent(id)}`, { waitUntil: 'networkidle' }); assert(first && first.ok());
        const paper = page.locator('article.ws-focus h3 a').first(); await paper.waitFor({ state: 'visible' });
        const reader = await paper.getAttribute('href'); assert(reader && reader.startsWith('/workspace/items/'));
        const fixture = await page.evaluate(async () => { const response = await fetch('/api/workspace/state'); if (!response.ok) throw Error('state failed'); const state = await response.json(); return { principal: state.principal_key_id, works: state.works.length, scheduleEnabled: state.schedule.enabled, work: state.works.find(w => w.work_id === 'arxiv:2611.99800')?.version_id }; });
        assert.deepEqual(fixture, { principal: 'controller-p6-preview', works: 39, scheduleEnabled: false, work: 'arxiv:2611.99800:v1' });
        const reviewLabels = async () => page.evaluate(async () => { const response = await fetch('/api/workspace/review'); if (!response.ok) throw Error('review failed'); const value = await response.json(); return (value.packet?.items ?? []).map(item => item.feedback.label); });
        const labelsBefore = await reviewLabels(); assert(labelsBefore.length > 0 && labelsBefore.every(label => label === null));
        for (const [route, url] of [['today', `/workspace/today?focus=${encodeURIComponent(id)}`], ['radar', '/workspace/radar?q=agent&days=0'], ['library', '/workspace/library?view=notes'], ['reader', reader], ['interests', '/workspace/interests'], ['operations', '/workspace/operations'], ['review', '/workspace/review']]) {
          active = `${size}-${theme}-${route}`;
          try {
            const response = await page.goto(base + url, { waitUntil: 'networkidle' }); assert(response && response.ok());
            await page.locator('main h1').first().waitFor({ state: 'visible' });
            await page.locator('main [aria-busy="true"]').waitFor({ state: 'hidden', timeout: 30000 });
            assert.equal(await page.getByText('Design preview · synthetic sample papers', { exact: true }).count(), 1);
            assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
            assert.equal(await page.locator('main h1').count(), 1);
            const overflow = await page.evaluate(() => ({ document: document.documentElement.scrollWidth - document.documentElement.clientWidth, body: document.body.scrollWidth - document.body.clientWidth }));
            assert(overflow.document <= 1 && overflow.body <= 1, `horizontal overflow ${JSON.stringify(overflow)}`);
            const axe = await new AxeBuilder({ page }).analyze();
            const violations = axe.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) }));
            if (['interests', 'operations', 'review'].includes(route)) await page.screenshot({ path: path.join(dir, `p6-readonly-support${suffix}`, `${active}.png`), fullPage: false });
            let lowerReach = null;
            if (route === 'operations' || route === 'review') {
              const target = route === 'operations' ? page.locator('main .daily-generation h3') : page.locator('main article.workspace-review-candidate h2').last();
              if (await target.count()) {
                await target.evaluate(node => node.scrollIntoView({ block: 'center', behavior: 'instant' }));
                lowerReach = await target.evaluate(node => { const rect = node.getBoundingClientRect(), bar = document.querySelector('.ws-bar')?.getBoundingClientRect(), hit = document.elementFromPoint(rect.left + Math.min(rect.width / 2, 100), rect.top + rect.height / 2); return { top: rect.top, bottom: rect.bottom, viewport: innerHeight, barTop: bar?.top ?? null, hit: Boolean(hit && (node.contains(hit) || hit.contains(node))) }; });
                assert(lowerReach.top >= 0 && lowerReach.bottom <= lowerReach.viewport && lowerReach.hit, `lower content obscured: ${JSON.stringify(lowerReach)}`);
              }
            }
            report.cases.push({ size, theme, route, status: 'pass', heading: await page.locator('main h1').innerText(), url: page.url(), overflow, violations, lowerReach });
            console.log('PASS', active, 'axe', violations.length);
          } catch (error) { report.cases.push({ size, theme, route, status: 'fail', error: String(error.stack || error) }); console.log('FAIL', active, String(error)); }
        }
        const labelsAfter = await reviewLabels(); assert.deepEqual(labelsAfter, labelsBefore);
        report.labelChecks.push({ size, theme, count: labelsAfter.length, allBlank: labelsAfter.every(label => label === null), unchanged: true });
      } catch (error) { report.errors.push({ active, kind: 'setup', text: String(error.stack || error) }); }
      finally { await ctx.close(); }
    }
    for (const width of [768, 1024]) {
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 2 });
      let active = `tablet-${width}`;
      await ctx.route('**/*', route => { const req = route.request(), url = new URL(req.url()); if (url.origin !== base || !['GET', 'HEAD'].includes(req.method())) { report.blocked.push({ active, method: req.method(), url: url.origin + url.pathname }); return route.abort('blockedbyclient'); } return route.continue(); });
      const page = await ctx.newPage();
      try { const response = await page.goto(base + '/workspace/operations', { waitUntil: 'networkidle' }); assert(response && response.ok()); await page.locator('main h1').waitFor({ state: 'visible' }); const dimensions = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth })); assert(dimensions.scrollWidth <= dimensions.width + 1); const toggle = page.getByRole('button', { name: /Expand sidebar|Queue & controls|Collapse sidebar/ }); await toggle.click(); assert(await page.getByRole('button', { name: /Show source 1 of/ }).isVisible()); report.tablet.push({ width, status: 'pass', dimensions }); }
      catch (error) { report.tablet.push({ width, status: 'fail', error: String(error.stack || error) }); }
      finally { await ctx.close(); }
    }
  } finally { await browser.close(); }
})().catch(error => report.errors.push({ kind: 'fatal', text: String(error.stack || error) })).finally(async () => {
  await fs.writeFile(path.join(dir, `p6-readonly-a11y${suffix}.json`), JSON.stringify(report, null, 2) + '\n');
  const failed = report.cases.filter(c => c.status !== 'pass').length + report.tablet.filter(c => c.status !== 'pass').length;
  const violations = report.cases.flatMap(c => (c.violations || []).map(v => ({ route: c.route, size: c.size, theme: c.theme, id: v.id, impact: v.impact })));
  console.log(JSON.stringify({ cases: report.cases.length, tablets: report.tablet.length, failed, violations, blocked: report.blocked.length, errors: report.errors.length }, null, 2));
  if (failed || report.blocked.length || report.errors.length || violations.some(v => ['serious', 'critical'].includes(v.impact))) process.exitCode = 1;
});
