// CI-synthetic P4 browser walkthrough. This writes one named verification question
// per viewport only after checking the isolated principal and fixture provenance.
const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = 'http://127.0.0.1:3149';
const output = path.resolve('outputs/controller-session/p4-reader-audit.json');
const shots = path.resolve('planning/12-workspace-controller-revamp/evidence/after/p4-reader/walkthrough');
async function capture(page,size,stage){await page.screenshot({path:path.join(shots,`ci-synthetic-${size}-${stage}.png`),fullPage:false});}
const report = {base,principal:'controller-p4',fixture:'CI-synthetic; three works, four versions',cases:[],blocked:[],consoleErrors:[],pageErrors:[],requestFailures:[],expectedInjectedConsole:[],writes:[]};
let currentCase = '';
async function check(name, fn) {
  currentCase=name;
  try { const detail=await fn();report.cases.push({name,status:'pass',...(detail===undefined?{}:{detail})});console.log('PASS',name);return true; }
  catch(e){report.cases.push({name,status:'fail',error:String(e.stack||e)});console.log('FAIL',name,String(e.message||e));return false;}
}
async function getState(page){return page.evaluate(async()=>{const r=await fetch('/api/workspace/state');if(!r.ok)throw Error(`state HTTP ${r.status}`);return r.json()})}
async function guard(page){
  assert.equal(new URL(page.url()).origin,base);
  const state=await getState(page);
  assert.equal(state.principal_key_id,'controller-p4');
  assert.equal(state.works.length,3);assert.equal(state.works.reduce((n,w)=>n+w.versions.length,0),4);
  assert.deepEqual(state.works.map(w=>w.work_id).sort(),['ci:workspace-agent-evaluation','ci:workspace-feed-excerpt','ci:workspace-retrieval-budget']);
  assert(state.works.every(w=>w.versions.every(v=>v.title.startsWith('CI fixture — '))),'non-CI fixture version found');
  assert(state.sources.every(s=>s.receipt?.fixture_revision==='workspace-browser-synthetic-v1'),'unexpected source receipt');
  return state;
}
async function readyToday(page){await page.locator('main h1').filter({hasText:'What changed.'}).waitFor({state:'visible'});await page.locator('article.ws-focus h3 a').waitFor({state:'visible'});}
async function readyReader(page){await page.locator('main h1').first().waitFor({state:'visible'});assert(!/unavailable|not in the loaded workspace/i.test(await page.locator('main h1').first().innerText()));}
async function main(){
  await fs.mkdir(path.dirname(output),{recursive:true});await fs.mkdir(shots,{recursive:true});
  const browser=await chromium.launch();
  try {for(const [size,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]){
    const context=await browser.newContext({viewport,deviceScaleFactor:2,colorScheme:'dark'});
    let writesAllowed=false,failNextEntry=false;
    await context.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url());
      if(url.origin!==base){report.blocked.push({size,case:currentCase,kind:'external',method:req.method(),url:url.origin+url.pathname});return route.abort('blockedbyclient')}
      if(!['GET','HEAD'].includes(req.method())){
        if(!writesAllowed||req.method()!=='POST'||!['/api/workspace/reading','/api/workspace/entries'].includes(url.pathname)){
          report.blocked.push({size,case:currentCase,kind:'mutation-denied',method:req.method(),url:url.pathname});return route.abort('blockedbyclient');
        }
        const body=req.postDataJSON();report.writes.push({size,case:currentCase,path:url.pathname,body,injected503:failNextEntry&&url.pathname.endsWith('/entries')});
        if(failNextEntry&&url.pathname.endsWith('/entries')){failNextEntry=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Injected synthetic walkthrough outage'})});}
      }
      return route.continue();
    });
    const page=await context.newPage();
    page.on('console',m=>{if(m.type()==='error'){const event={size,case:currentCase,text:m.text()};if(m.text().includes('503')&&report.writes.some(x=>x.size===size&&x.injected503))report.expectedInjectedConsole.push(event);else if(m.text().includes('409')&&currentCase.includes('real conflict'))report.expectedInjectedConsole.push(event);else report.consoleErrors.push(event)}});
    page.on('pageerror',e=>report.pageErrors.push({size,case:currentCase,text:String(e)}));
    page.on('requestfailed',r=>{const u=new URL(r.url()),failure=r.failure()?.errorText;if(!(r.method()==='GET'&&u.origin===base&&u.searchParams.has('_rsc')&&failure==='net::ERR_ABORTED'))report.requestFailures.push({size,case:currentCase,url:r.url(),failure})});
    let item,version,anchor,question,entry;
    try{
      const initial=await check(`${size}: guard and Today to Reader`,async()=>{
        const r=await page.goto(base+'/workspace/today',{waitUntil:'networkidle'});assert(r&&r.ok());await readyToday(page);
        const state=await guard(page);writesAllowed=true;
        const order=state.editions[0].work_ids;
        item=state.works.find(w=>order.includes(w.work_id)&&w.versions.length===2);
        assert(item,'edition must include the two-version synthetic work');
        const index=order.indexOf(item.work_id),pinned=state.editions[0].work_versions[item.work_id];
        version=item.versions.find(v=>v.version_id===pinned);assert(version&&version.abstract);
        if(index!==0){
          if(size==='mobile')await page.getByRole('button',{name:'Queue & controls'}).click();
          await page.getByRole('button',{name:new RegExp(`^Show paper ${index+1} of ${order.length}:`)}).click();
        }
        const href=new URL(await page.locator('article.ws-focus h3 a').getAttribute('href'),base);
        assert.equal(href.searchParams.get('version'),version.version_id);
        assert.equal(new URL(href.searchParams.get('return_to'),base).searchParams.get('focus'),item.work_id);
        await page.locator('article.ws-focus h3 a').click();await page.waitForURL(u=>u.pathname.startsWith('/workspace/items/'));await readyReader(page);
        assert.equal(new URL(page.url()).searchParams.get('version'),version.version_id);
        return {workId:item.work_id,version:version.version_id,editionOrder:order};
      });
      if(!initial)continue;
      const selected=await check(`${size}: selected passage and keyboard to notes`,async()=>{
        const paragraph=page.locator('.daily-source-text p').first();
        if(!await paragraph.isVisible())await page.getByRole('link',{name:'Source',exact:true}).click();
        await paragraph.waitFor({state:'visible'});
        const selected=await paragraph.evaluate(el=>{
          const node=el.firstChild;if(!node||node.nodeType!==Node.TEXT_NODE)throw Error('source paragraph has no direct text node');
          const text=node.textContent,needle=text.includes('𝛼 + 🚀')?'𝛼 + 🚀':text.slice(12,30),start=text.indexOf(needle),end=start+needle.length;
          const range=document.createRange();range.setStart(node,start);range.setEnd(node,end);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
          el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
          return {text:needle,anchor:`abstract:${Array.from(text.slice(0,start)).length}:${Array.from(text.slice(0,end)).length}`};
        });
        anchor=selected.anchor;await paragraph.scrollIntoViewIfNeeded();await capture(page,size,'01-source-passage');
        await page.locator('main#main').focus();const notes=page.getByRole('link',{name:'Your notes',exact:true});
        const tabOrder=[];let steps=0;while(steps<16 && !await notes.evaluate(el=>el===document.activeElement)){
          await page.keyboard.press('Tab');steps++;
          const name=await page.evaluate(()=>{const el=document.activeElement;return el?.closest('nav[aria-label=\"Reading sections\"]')?el.textContent.trim():null});
          if(name)tabOrder.push(name);
        }
        assert(await notes.evaluate(el=>el===document.activeElement),`notes not reached in ${steps} tabs`);
        assert.deepEqual(tabOrder,['Source','Understand','Your notes']);
        await page.keyboard.press('Enter');await page.keyboard.press('Tab');
        assert(await page.getByRole('combobox',{name:'Save as'}).evaluate(el=>el===document.activeElement));
        await page.keyboard.press('Tab');const field=page.getByRole('textbox',{name:'Your question',exact:true});assert(await field.evaluate(el=>el===document.activeElement));
        question=`CI synthetic P4 verification ${size}: which baseline supports this selected passage?`;await field.fill(question);
        const submit=page.getByRole('button',{name:'Save question',exact:true});await submit.waitFor({state:'visible'});await page.waitForFunction(()=>{const button=Array.from(document.querySelectorAll('button')).find(el=>el.textContent.trim()==='Save question');return button&&!button.disabled},{timeout:10000});
        await page.keyboard.press('Tab');assert(await page.getByRole('button',{name:'Save question',exact:true}).evaluate(el=>el===document.activeElement));
        assert((await page.locator('.workspace-note-context').allInnerTexts()).some(t=>t.includes(anchor)),'selected passage anchor not retained');
        return {selectedText:selected.text,anchor,tabsToNotes:steps,tabOrder};
      });
      if(!selected)continue;
      const navigated=await check(`${size}: Reader queue and recovered draft`,async()=>{
        const currentPath=new URL(page.url()).pathname;
        const next=page.getByRole('link',{name:'Next paper',exact:true});
        const direction=await next.count()?'Next paper':'Previous paper';
        const reverse=direction==='Next paper'?'Previous paper':'Next paper';
        const forward=page.getByRole('link',{name:direction,exact:true});assert.equal(await forward.count(),1,'missing Reader queue neighbour');
        const target=new URL(await forward.getAttribute('href'),base);assert.notEqual(target.pathname,currentPath);
        await forward.click();await page.waitForURL(u=>u.pathname===target.pathname);await readyReader(page);
        const back=page.getByRole('link',{name:reverse,exact:true});assert.equal(await back.count(),1);
        const href=new URL(await back.getAttribute('href'),base);assert.equal(href.pathname,currentPath);
        await back.click();await page.waitForURL(u=>u.pathname===currentPath);await readyReader(page);
        await page.getByRole('link',{name:'Your notes',exact:true}).click();
        const field=page.getByRole('textbox',{name:'Your question',exact:true});await field.waitFor({state:'visible'});assert.equal(await field.inputValue(),question);
        assert((await page.locator('.workspace-note-context').allInnerTexts()).some(t=>t.includes(anchor)));
        return {direction,returnedPath:currentPath,anchor};
      });
      if(!navigated)continue;
      const saved=await check(`${size}: injected outage, reload recovery and real save`,async()=>{
        const field=page.getByRole('textbox',{name:'Your question',exact:true});await field.fill(question);
        failNextEntry=true;await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/workspace/entries')&&r.status()===503),page.getByRole('button',{name:'Save question',exact:true}).click()]);
        assert.equal(await field.inputValue(),question);assert((await page.getByRole('status').innerText()).includes('still here'));
        await field.scrollIntoViewIfNeeded();await capture(page,size,'02-injected-503-draft');
        await page.reload({waitUntil:'networkidle'});await readyReader(page);
        const restored=page.getByRole('textbox',{name:'Your question',exact:true});await restored.waitFor();assert.equal(await restored.inputValue(),question);
        assert((await page.getByRole('status').innerText()).includes('Recovered'));
        await page.getByRole('button',{name:'Save question',exact:true}).click();await page.getByRole('status').filter({hasText:'is saved on the server'}).waitFor();
        const state=await guard(page);entry=state.works.find(w=>w.work_id===item.work_id).entries.find(e=>e.body===question);
        assert(entry,'question missing from server state');assert.equal(entry.version_id,version.version_id);assert.equal(entry.anchor,anchor);
        await page.getByText(question,{exact:true}).scrollIntoViewIfNeeded();await capture(page,size,'03-saved-question');
        return {entryId:entry.id,revision:entry.revision,version:entry.version_id,anchor:entry.anchor};
      });
      if(!saved)continue;
      const returned=await check(`${size}: Today return, reload and Library resume`,async()=>{
        await page.getByRole('link',{name:/← Today/}).first().click();await page.waitForURL(u=>u.pathname==='/workspace/today'&&u.searchParams.get('focus')===item.work_id);await readyToday(page);
        await page.reload({waitUntil:'networkidle'});await readyToday(page);assert.equal(new URL(page.url()).searchParams.get('focus'),item.work_id);await capture(page,size,'04-today-return');
        await page.goto(base+'/workspace/library?view=notes',{waitUntil:'networkidle'});
        const card=page.locator('article').filter({hasText:question});await card.waitFor({state:'visible'});
        const href=new URL(await card.getByRole('link',{name:'Resume this question →'}).getAttribute('href'),base);
        assert.equal(href.searchParams.get('version'),version.version_id);assert.equal(href.searchParams.get('entry'),entry.id);assert.equal(decodeURIComponent(href.hash.slice(1)),anchor);
        await card.getByRole('link',{name:'Resume this question →'}).click();await page.waitForURL(u=>u.pathname.startsWith('/workspace/items/'));await readyReader(page);
        assert.equal(new URL(page.url()).searchParams.get('version'),version.version_id);assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)),anchor);
        assert.equal(await page.getByText(question,{exact:true}).count(),1);
        return {entryId:entry.id,version:version.version_id,anchor};
      });
      if(!returned)continue;
      await check(`${size}: real conflict retains local and server text`,async()=>{
        const card=page.locator('article').filter({hasText:question});await card.getByRole('button',{name:'Edit question'}).click();
        const local=`${question} Local stale edit.`;const remote=`${question} Remote revision.`;
        const field=page.getByRole('textbox',{name:'Your question',exact:true});await field.fill(local);
        const before=await guard(page);const current=before.works.find(w=>w.work_id===item.work_id).entries.find(e=>e.id===entry.id);assert.equal(current.revision,entry.revision);
        const update=await page.evaluate(async({entry,remote})=>{const r=await fetch('/api/workspace/entries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:entry.id,revision:entry.revision,request_id:crypto.randomUUID(),data:{work_id:entry.work_id,version_id:entry.version_id,kind:entry.kind,body:remote,anchor:entry.anchor}})});return {status:r.status,body:await r.json()}},{entry:current,remote});
        assert.equal(update.status,200);assert.equal(update.body.revision,entry.revision+1);
        const [conflict]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/workspace/entries')&&r.status()===409),page.getByRole('button',{name:'Save question',exact:true}).click()]);assert.equal(conflict.status(),409);
        assert.equal(await field.inputValue(),local);assert((await page.getByRole('status').innerText()).includes('changed in another tab'));
        const server=(await guard(page)).works.find(w=>w.work_id===item.work_id).entries.find(e=>e.id===entry.id);assert.equal(server.body,remote);assert.equal(server.anchor,anchor);assert.equal(server.version_id,version.version_id);
        await page.reload({waitUntil:'networkidle'});await readyReader(page);
        const recovered=page.getByRole('textbox',{name:'Your question',exact:true});await recovered.waitFor();assert.equal(await recovered.inputValue(),local);assert((await page.getByRole('status').innerText()).includes('Recovered'));
        const stillServer=(await guard(page)).works.find(w=>w.work_id===item.work_id).entries.find(e=>e.id===entry.id);assert.equal(stillServer.body,remote);
        await recovered.scrollIntoViewIfNeeded();await capture(page,size,'05-real-409-recovered-draft');
        return {entryId:entry.id,priorRevision:entry.revision,serverRevision:server.revision,version:server.version_id,anchor:server.anchor};
      });
    }finally{writesAllowed=false;await page.waitForLoadState('networkidle',{timeout:30000});await context.close()}
  }}finally{await browser.close()}
}
main().catch(e=>report.cases.push({name:'audit execution',status:'fail',error:String(e.stack||e)})).finally(async()=>{
  await fs.writeFile(output,JSON.stringify(report,null,2)+'\n');const failed=report.cases.filter(x=>x.status==='fail');
  console.log(JSON.stringify({output,cases:report.cases.length,failed:failed.length,blocked:report.blocked.length,consoleErrors:report.consoleErrors.length,pageErrors:report.pageErrors.length,requestFailures:report.requestFailures.length,failures:failed.map(x=>({name:x.name,error:x.error.split('\n')[0]}))},null,2));
  if(failed.length||report.blocked.length||report.consoleErrors.length||report.pageErrors.length||report.requestFailures.length)process.exitCode=1;
});
