const { chromium } = require('playwright');
(async () => {
  const out = process.argv[2];
  const base = process.env.BASE || 'http://127.0.0.1:3000';
  const routes = ['today','radar','library','interests','operations','review','items/' + encodeURIComponent(process.env.ITEM || 'ci:workspace-agent-evaluation')];
  const browser = await chromium.launch();
  for (const [name, vp] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const errs = [];
    page.on('console', m => { if (m.type()==='error') errs.push(m.text().slice(0,160)); });
    for (const r of routes) {
      const resp = await page.goto(`${base}/workspace/${r}`, { waitUntil: 'networkidle', timeout: 90000 });
      await page.waitForTimeout(800);
      const file = `${out}/${name}-${r.split('/')[0]}.png`;
      await page.screenshot({ path: file, fullPage: true });
      const h1 = await page.locator('h1').first().textContent().catch(()=>null);
      const txt = (await page.locator('main').innerText().catch(()=> '')).slice(0,200).replace(/\s+/g,' ');
      console.log(name, r, resp.status(), JSON.stringify(h1), '|', txt);
    }
    if (errs.length) console.log('console errors', name, errs.slice(0,5));
    await ctx.close();
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
