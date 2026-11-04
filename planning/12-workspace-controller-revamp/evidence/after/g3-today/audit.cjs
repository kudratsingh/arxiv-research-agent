const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

const base = 'http://127.0.0.1:3148';
const output = path.resolve('outputs/controller-session/g3-today-audit.json');
const shots = path.resolve('planning/12-workspace-controller-revamp/evidence/after/g3-today');
const report = {base, generatedAt:new Date().toISOString(), fixture:'offline synthetic rich data; principal e2e', cases:[], consoleErrors:[], pageErrors:[], blocked:[], requestFailures:[], readingRequests:[], expectedInjectedConsole:[], navigationCancellations:[]};
let currentPage, currentCase = '';
async function check(name, fn) {
  currentCase=name;
  try { const detail = await fn(); if(currentPage)await currentPage.waitForLoadState('networkidle',{timeout:30000}); report.cases.push({name,status:'pass',...(detail === undefined ? {} : {detail})}); console.log('PASS',name); }
  catch(e) { report.cases.push({name,status:'fail',error:String(e.stack || e)}); console.log('FAIL',name,String(e.message || e)); }
}
async function ready(page) {
  await page.locator('main h1').filter({hasText:'What changed.'}).waitFor({state:'visible',timeout:30000});
  await page.locator('main [aria-busy="true"]').waitFor({state:'hidden',timeout:30000});
  await page.locator('article.ws-focus h3 a').waitFor({state:'visible',timeout:30000});
}
async function goto(page, pathname) {
  const r = await page.goto(base+pathname,{waitUntil:'networkidle',timeout:60000});
  assert(r && r.ok(),`navigation ${pathname} status ${r?.status()}`);
}
async function state(page) {
  return page.evaluate(async()=>{const r=await fetch('/api/workspace/state');if(!r.ok)throw Error(`state HTTP ${r.status}`);return r.json()});
}
function titleFor(state,id) {
  const work=state.works.find(x=>x.work_id===id); assert(work,`missing work ${id}`);
  const version=state.editions[0].work_versions[id];
  return work.versions.find(x=>x.version_id===version)?.title || work.title;
}
async function expectFocus(page, id, title) {
  await page.waitForFunction(({id,title})=>new URL(location.href).searchParams.get('focus')===id && document.querySelector('article.ws-focus h3 a')?.textContent?.trim()===title,{id,title},{timeout:10000});
  assert.equal(await page.locator('main article').count(),1,'Today must contain one paper article');
}
function parseColor(value) {
  const v=value.trim();
  const hex=v.match(/^#([0-9a-f]{6})$/i);
  if(hex) return [0,2,4].map(i=>parseInt(hex[1].slice(i,i+2),16));
  const rgb=v.match(/^rgba?\(\s*(\d+)\s*[, ]\s*(\d+)\s*[, ]\s*(\d+)(?:\s*[,/]\s*1(?:\.0+)?)?\s*\)$/i);
  if(rgb)return rgb.slice(1,4).map(Number);
  throw Error(`unsupported or nonopaque color: ${value}`);
}
function contrast(a,b) {
  const luminance=c=>{const parts=c.map(n=>{const v=n/255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4});return 0.2126*parts[0]+0.7152*parts[1]+0.0722*parts[2]};
  const x=luminance(a),y=luminance(b); return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05);
}
async function tapKey(page,key) { await page.locator('main#main').focus(); await page.keyboard.press(key); }
async function assertMobileTitle(page) {
  const geometry=await page.evaluate(()=>{const t=document.querySelector('article.ws-focus h3').getBoundingClientRect(),b=document.querySelector('.ws-bar').getBoundingClientRect();return {top:t.top,bottom:t.bottom,barTop:b.top};});
  assert(geometry.top<800 && geometry.top>=0 && geometry.bottom<=geometry.barTop-8, `mobile title obscured or outside viewport: ${JSON.stringify(geometry)}`);
  return geometry;
}
async function main() {
  await fs.mkdir(path.dirname(output),{recursive:true});
  await fs.mkdir(shots,{recursive:true});
  const browser=await chromium.launch();
  try {
    for (const [size,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}],['tablet768',{width:768,height:1000}],['tablet1024',{width:1024,height:1000}]]) {
      for (const theme of (size.startsWith('tablet')?['dark']:['light','dark'])) {
        const label=`${size}-${theme}`;
        const context=await browser.newContext({viewport,deviceScaleFactor:2,colorScheme:theme});
        await context.addInitScript(t=>localStorage.setItem('arxiv-agent.theme',t),theme);
        let failNextReading=false;
        await context.route('**/*',async route=>{
          const req=route.request(), u=new URL(req.url());
          if(req.method()==='POST' && /^\/api\/workspace\/refresh\/?$/.test(u.pathname)) { report.blocked.push({label,kind:'refresh',url:u.pathname}); return route.abort('blockedbyclient'); }
          if(u.origin!==base) { report.blocked.push({label,kind:'external',url:u.origin+u.pathname}); return route.abort('blockedbyclient'); }
          if(req.method()==='POST' && /^\/api\/workspace\/reading\/?$/.test(u.pathname)) {
            const body=req.postDataJSON(); report.readingRequests.push({label,body,injectedFailure:failNextReading});
            if(failNextReading) { failNextReading=false; return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Injected audit failure'})}); }
          }
          return route.continue();
        });
        const page=await context.newPage(); currentPage=page;
        page.on('console',m=>{if(m.type()==='error') { const entry={label,url:page.url(),text:m.text()}; if(label==='desktop-light' && m.text().includes('503') && report.readingRequests.some(x=>x.label===label && x.injectedFailure)) report.expectedInjectedConsole.push(entry); else report.consoleErrors.push(entry); }});
        page.on('pageerror',e=>report.pageErrors.push({label,url:page.url(),text:String(e)}));
        page.on('requestfailed',r=>{const url=new URL(r.url()),failure=r.failure()?.errorText;const entry={label,case:currentCase,url:r.url(),failure};if(r.method()==='GET' && url.origin===base && url.searchParams.has('_rsc') && failure==='net::ERR_ABORTED')report.navigationCancellations.push(entry);else report.requestFailures.push(entry)});
        let snapshot,ids,titles;
        try {
          await check(`${label}: seeded Today`,async()=>{
            await goto(page,'/workspace/today'); await ready(page);
            snapshot=await state(page); assert.equal(snapshot.principal_key_id,'e2e');
            ids=snapshot.editions[0].work_ids; assert.equal(ids.length,9);
            titles=ids.map(id=>titleFor(snapshot,id));
            assert.equal(await page.locator('main article').count(),1);
            assert.equal(await page.locator('article.ws-focus h3 a').innerText(),titles[0]);
            assert.equal(await page.getByText('Design preview · synthetic sample papers',{exact:true}).count(),1);
            assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
            const layout=await page.evaluate(()=>({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,titleY:document.querySelector('article.ws-focus h3').getBoundingClientRect().y}));
            assert(layout.scrollWidth<=layout.width+1,`horizontal overflow ${JSON.stringify(layout)}`);
            if(size==='mobile')await assertMobileTitle(page);
            if(['desktop','mobile'].includes(size))await page.screenshot({path:path.join(shots,`${size}-${theme}-today.png`),fullPage:false});
            return {ids,titleY:layout.titleY};
          });
          await check(`${label}: progress fill and track contrast`,async()=>{
            const colors=await page.locator('progress[aria-label="Reading queue progress"]').evaluate(el=>{const progress=getComputedStyle(el),root=getComputedStyle(el.closest('.workspace-app'));return {track:progress.backgroundColor,fill:progress.color,primary:root.getPropertyValue('--color-primary').trim()};});
            const track=parseColor(colors.track),fill=parseColor(colors.fill),primary=parseColor(colors.primary);
            assert.deepEqual(fill,primary,'progress fill does not use the scoped primary color');
            const ratio=contrast(fill,track);assert(ratio>=3,`progress fill/track contrast ${ratio.toFixed(3)}:1 < 3:1; ${JSON.stringify(colors)}`);
            return {...colors,ratio};
          });
          await check(`${label}: queue selection and drawer close`,async()=>{
            assert(ids&&titles,'seed check failed'); await goto(page,'/workspace/today'); await ready(page);
            if(size==='mobile'||size==='tablet768') {
              await page.getByRole('button',{name:size==='mobile'?'Queue & controls':'Expand sidebar'}).click();
              await page.getByRole('dialog').waitFor({state:'visible'});
              if(size==='mobile'&&theme==='dark')await page.screenshot({path:path.join(shots,'mobile-dark-queue-open.png'),fullPage:false});
            }
            const row=page.getByRole('button',{name:`Show paper 4 of 9: ${titles[3]}`});
            await row.click(); await expectFocus(page,ids[3],titles[3]);
            if(size==='mobile'||size==='tablet768')assert.equal(await page.locator('.workspace-app').getAttribute('data-drawer'),'closed');
            if(size==='mobile')await assertMobileTitle(page);
          });
          await check(`${label}: j/k order and boundaries`,async()=>{
            assert(ids&&titles,'seed check failed'); await goto(page,'/workspace/today');await ready(page);
            await tapKey(page,'k');assert.equal(await page.locator('article.ws-focus h3 a').innerText(),titles[0]);
            for(let i=1;i<ids.length;i++){await tapKey(page,'j');await expectFocus(page,ids[i],titles[i]);}
            await tapKey(page,'j');await expectFocus(page,ids[8],titles[8]);
            for(let i=7;i>=0;i--){await tapKey(page,'k');await expectFocus(page,ids[i],titles[i]);}
            await tapKey(page,'k');await expectFocus(page,ids[0],titles[0]);
          });
          await check(`${label}: reload and browser history`,async()=>{
            assert(ids&&titles,'seed check failed');
            await goto(page,'/workspace/radar');await goto(page,'/workspace/today');await ready(page);
            await tapKey(page,'j');await expectFocus(page,ids[1],titles[1]);
            await page.reload({waitUntil:'networkidle'});await ready(page);await expectFocus(page,ids[1],titles[1]);
            await tapKey(page,'j');await expectFocus(page,ids[2],titles[2]);
            await page.goBack({waitUntil:'networkidle'});await page.waitForURL('**/workspace/radar');
            await page.goForward({waitUntil:'networkidle'});await ready(page);await expectFocus(page,ids[2],titles[2]);
          });
          await check(`${label}: Reader retained version and return`,async()=>{
            assert(ids&&titles,'seed check failed'); await goto(page,'/workspace/today');await ready(page);
            await tapKey(page,'j');await expectFocus(page,ids[1],titles[1]);
            const work=snapshot.works.find(x=>x.work_id===ids[1]);
            const pinned=snapshot.editions[0].work_versions[ids[1]] || work.version_id;
            const version=work.versions.find(x=>x.version_id===pinned) || work;
            const pdf=(version.retained_materials||[]).find(x=>x.format==='pdf');
            const anchor=work.reading.revision>0 && work.reading.version_id===pinned ? work.reading.anchor : pdf?.first_anchor || `${version.access_state}:0`;
            const link=page.locator('article.ws-focus h3 a'); const url=new URL(await link.getAttribute('href'),base);
            assert.equal(url.searchParams.get('version'),pinned);assert.equal(decodeURIComponent(url.hash.slice(1)),anchor);
            const ret=new URL(url.searchParams.get('return_to'),base);assert.equal(ret.pathname,'/workspace/today');assert.equal(ret.searchParams.get('focus'),ids[1]);
            await link.click();await page.waitForURL(u=>u.pathname.startsWith('/workspace/items/'));
            await page.locator('main h1').first().waitFor({state:'visible'});
            assert.equal(new URL(page.url()).searchParams.get('version'),pinned);assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)),anchor);
            const back=page.getByRole('link',{name:/← Today/}).first();await back.click();await page.waitForURL('**/workspace/today?**');await ready(page);await expectFocus(page,ids[1],titles[1]);
            if(size==='mobile')await assertMobileTitle(page);
            if(size==='desktop'&&theme==='dark')await page.screenshot({path:path.join(shots,'desktop-dark-reader-return.png'),fullPage:false});
            return {id:ids[1],version:pinned,anchor};
          });
          await check(`${label}: end of stage is unobscured`,async()=>{
            await goto(page,'/workspace/today');await ready(page);
            const details=page.locator('main details.workspace-edition-details > summary');
            await details.scrollIntoViewIfNeeded();
            const geometry=await details.evaluate(el=>{const r=el.getBoundingClientRect(),bar=document.querySelector('.ws-bar')?.getBoundingClientRect();return {top:r.top,bottom:r.bottom,viewport:innerHeight,barTop:bar?.top,barBottom:bar?.bottom,left:r.left,right:r.right,barLeft:bar?.left,barRight:bar?.right}});
            assert(geometry.top>=0 && geometry.bottom<=geometry.viewport,JSON.stringify(geometry));
            if(geometry.barTop!==undefined && geometry.barBottom!==undefined && geometry.barLeft!==undefined && geometry.barRight!==undefined) {
              const overlaps=geometry.bottom>geometry.barTop && geometry.top<geometry.barBottom && geometry.right>geometry.barLeft && geometry.left<geometry.barRight;
              assert(!overlaps,`edition footer obscured by control bar: ${JSON.stringify(geometry)}`);
            }
            return geometry;
          });
          if(size==='desktop'&&theme==='light') await check(`${label}: failed save and reversible Save/Undo`,async()=>{
            assert(ids&&titles,'seed check failed');await goto(page,`/workspace/today?focus=${encodeURIComponent(ids[0])}`);await ready(page);
            const guard=await state(page);
            assert.equal(new URL(page.url()).origin,base);assert.equal(guard.principal_key_id,'e2e');assert.equal(guard.editions[0]?.work_ids.length,9);
            assert.equal(await page.getByText('Design preview · synthetic sample papers',{exact:true}).count(),1);
            assert.equal(guard.editions[0].work_ids[0],ids[0]);
            const original=guard.works.find(x=>x.work_id===ids[0]).reading;
            assert.equal(original.status,'unread','audit expects fresh synthetic item');
            const save=page.locator('[data-command="save"]');failNextReading=true;
            await Promise.all([page.waitForResponse(r=>r.url().includes('/api/workspace/reading')&&r.status()===503),save.click()]);
            assert.equal(await page.locator('article.ws-focus h3 a').innerText(),titles[0]);
            assert.equal((await state(page)).works.find(x=>x.work_id===ids[0]).reading.status,original.status);
            await save.click();await page.getByText('Saved on the server: saved.',{exact:true}).waitFor();
            assert.equal((await state(page)).works.find(x=>x.work_id===ids[0]).reading.status,'saved');
            const undo=page.getByRole('button',{name:'Undo last change'});await undo.click();
            await page.getByText('Saved on the server: unread.',{exact:true}).waitFor();
            const restored=(await state(page)).works.find(x=>x.work_id===ids[0]).reading;
            for(const key of ['status','anchor','version_id','snoozed_until'])assert.equal(restored[key],original[key],`Undo failed to restore ${key}`);
            for (const status of ['dismissed','snoozed']) {
              const command=status==='dismissed'?'dismiss':'snooze';
              await page.locator(`[data-command="${command}"]`).click();
              await page.getByText(`Saved on the server: ${status}.`,{exact:true}).waitFor();
              await page.waitForFunction(title=>document.querySelector('article.ws-focus h3 a')?.textContent?.trim()===title,titles[1]);
              assert.equal(new URL(page.url()).searchParams.get('focus'),ids[0]);
              await page.getByRole('button',{name:'Undo last change'}).click();
              await page.getByText('Saved on the server: unread.',{exact:true}).waitFor();
              await expectFocus(page,ids[0],titles[0]);
              const after=(await state(page)).works.find(x=>x.work_id===ids[0]).reading;
              for(const key of ['status','anchor','version_id','snoozed_until'])assert.equal(after[key],original[key],`Undo failed to restore ${key}`);
            }
            const writes=report.readingRequests.filter(x=>x.label===label);assert.equal(writes.length,7);
            assert.equal(writes[0].injectedFailure,true);assert.equal(writes[1].body.work_id,ids[0]);
            assert.deepEqual(writes.slice(1).map(x=>x.body.data.status),['saved','unread','dismissed','unread','snoozed','unread']);
            const finalReading=(await state(page)).works.find(x=>x.work_id===ids[0]).reading;
            return {workId:ids[0], restoredStatus:finalReading.status, revisions:[original.revision,finalReading.revision]};
          });
        } finally {await page.waitForLoadState('networkidle',{timeout:30000}); currentPage=undefined; await context.close();}
      }
    }
  } finally {await browser.close();}
}
main().catch(e=>report.cases.push({name:'audit execution',status:'fail',error:String(e.stack||e)})).finally(async()=>{
  await fs.writeFile(output,JSON.stringify(report,null,2)+'\n');
  const failed=report.cases.filter(x=>x.status==='fail');
  console.log(JSON.stringify({output,cases:report.cases.length,failed:failed.length,consoleErrors:report.consoleErrors.length,pageErrors:report.pageErrors.length,blocked:report.blocked.length,requestFailures:report.requestFailures.length,navigationCancellations:report.navigationCancellations.length,failures:failed.map(x=>({name:x.name,error:x.error.split('\n')[0]}))},null,2));
  if(failed.length||report.consoleErrors.length||report.pageErrors.length||report.blocked.length||report.requestFailures.length)process.exitCode=1;
});
