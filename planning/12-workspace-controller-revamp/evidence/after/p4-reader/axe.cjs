const {chromium} = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
const fs = require('node:fs/promises');
(async () => {
  const browser = await chromium.launch();
  const records = [];
  try {
    for (const width of [1440,390]) {
      for (const theme of ['dark','light']) {
        const context = await browser.newContext({viewport:{width,height:width===390?844:1000},colorScheme:theme});
        await context.addInitScript(t=>localStorage.setItem('arxiv-agent.theme',t),theme);
        await context.route('**/*', route => new URL(route.request().url()).origin==='http://127.0.0.1:3148' && route.request().method()==='GET' ? route.continue() : route.abort());
        let page = await context.newPage();
        await page.goto('http://127.0.0.1:3148/workspace/today',{waitUntil:'networkidle'});
        await page.locator('article.ws-focus h3 a').waitFor();
        const href = await page.locator('article.ws-focus h3 a').getAttribute('href');
        await page.close();
        for (const tab of ['source','notes','understand']) {
          page = await context.newPage();
          await page.goto('http://127.0.0.1:3148'+href.split('#')[0]+'#'+tab,{waitUntil:'networkidle'});
          await page.locator('main h1').waitFor();
          await page.locator('#'+tab+'[data-active=true]').waitFor({state:'visible'});
          if(tab==='understand') await page.getByRole('button',{name:'Choose retained source context'}).waitFor();
          const result = await new AxeBuilder({page}).analyze();
          records.push({width,theme,tab,violations:result.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))});
          await page.close();
        }
        await context.close();
      }
    }
  } finally { await browser.close(); }
  await fs.writeFile('outputs/controller-session/p4-axe.json',JSON.stringify(records,null,2)+'\n');
  console.log(JSON.stringify(records.map(x=>({width:x.width,theme:x.theme,tab:x.tab,violations:x.violations.length})),null,2));
  if(records.some(x=>x.violations.some(v=>['serious','critical'].includes(v.impact)))) process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
