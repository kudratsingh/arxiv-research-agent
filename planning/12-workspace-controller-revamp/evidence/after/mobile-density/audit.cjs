// Read-only synthetic-layout audit. Runs only against the isolated 3148 preview.
// Real API flow and intercepted GET-state variants are explicitly reported separately.
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const base='http://127.0.0.1:3148';
const out=path.resolve('outputs/controller-session/mobile-density-audit.json');
const shots=path.resolve('outputs/controller-session/mobile-density-captures');
const variants=[
  {name:'real-nine-paper',override:false},
  {name:'layout-only-long-title',override:true,title:'Understanding Reliable Long-Horizon Research Agents Under Uncertain Evidence and Limited Computational Resources',abstract:'A bounded synthetic abstract explains retrieval, evidence selection and reproducible evaluation across multiple research tasks and observations.',minLines:2},
  {name:'layout-only-short-one-line',override:true,title:'Compact Study',abstract:'A short sample.',exactLines:1},
  {name:'layout-only-short-two-lines',override:true,title:'Compact Study',abstract:'A brief synthetic study describes evidence retrieval for agents.',exactLines:2},
  {name:'layout-only-short-three-lines',override:true,title:'Compact Study',abstract:'A brief synthetic study describes evidence retrieval and reproducible evaluation for research agents.',exactLines:3},
];
const report={base,generatedAt:new Date().toISOString(),purpose:'mobile density; synthetic data, no writes',cases:[],blocked:[],consoleErrors:[],pageErrors:[],requestFailures:[]};
let currentCase='';
async function check(name,fn){currentCase=name;try{const detail=await fn();report.cases.push({name,status:'pass',detail});console.log('PASS',name)}catch(e){report.cases.push({name,status:'fail',error:String(e.stack||e)});console.log('FAIL',name,String(e.message||e))}}
async function ready(page){await page.locator('main h1').filter({hasText:'What changed.'}).waitFor({state:'visible'});await page.locator('main [aria-busy="true"]').waitFor({state:'hidden'});await page.locator('article.ws-focus h3 a').waitFor({state:'visible'});}
async function measure(page,variant,step){
  const data=await page.evaluate(()=>{
    const title=document.querySelector('article.ws-focus h3');
    const abstract=document.querySelector('article.ws-focus .ws-focus-abstract');
    const bar=document.querySelector('.ws-bar');
    const composer=document.querySelector('.ws-composer-shell');
    if(!title||!abstract||!bar||!composer)throw Error('missing title, abstract, bar or composer shell');
    const titleRect=title.getBoundingClientRect(),barRect=bar.getBoundingClientRect();
    const walker=document.createTreeWalker(abstract,NodeFilter.SHOW_TEXT);const chars=[];
    while(walker.nextNode()){
      const node=walker.currentNode;
      for(let i=0;i<node.textContent.length;i++){
        if(/\s/.test(node.textContent[i]))continue;
        const range=document.createRange();range.setStart(node,i);range.setEnd(node,i+1);
        for(const r of range.getClientRects())if(r.width>0&&r.height>0)chars.push({top:r.top,bottom:r.bottom,left:r.left,right:r.right});
      }
    }
    const lines=[];
    for(const r of chars){let line=lines.find(x=>Math.abs(x.top-r.top)<1);if(!line){line={...r};lines.push(line)}else{line.top=Math.min(line.top,r.top);line.bottom=Math.max(line.bottom,r.bottom);line.left=Math.min(line.left,r.left);line.right=Math.max(line.right,r.right)}}
    lines.sort((a,b)=>a.top-b.top);
    return {title:{top:titleRect.top,bottom:titleRect.bottom,left:titleRect.left,right:titleRect.right},bar:{top:barRect.top,bottom:barRect.bottom,left:barRect.left,right:barRect.right},composerExpanded:composer.getAttribute('data-expanded'),lines};
  });
  assert.equal(data.composerExpanded,'false','mobile composer must be collapsed');
  assert(data.title.top>=0 && data.title.bottom<=data.bar.top-8,`${step}: title blocked ${JSON.stringify(data)}`);
  assert(data.lines.length>0,`${step}: abstract has no rendered text lines`);
  if(variant.exactLines)assert.equal(data.lines.length,variant.exactLines,`${variant.name}: wrong line count; do not accept a one-line fixture as a two-line test`);
  if(variant.minLines)assert(data.lines.length>=variant.minLines,`${variant.name}: expected at least ${variant.minLines} rendered lines`);
  for(const line of data.lines.slice(0,2)) assert(line.top>=0 && line.bottom<=data.bar.top-8,`${step}: abstract line obscured ${JSON.stringify(data)}`);
  return data;
}
function overrideState(data,variant){
  const ids=data.editions[0]?.work_ids;if(!Array.isArray(ids)||ids.length!==9)throw Error('expected nine synthetic works');
  for(const id of [ids[0],ids[1],ids[3]]){
    const work=data.works.find(w=>w.work_id===id);const versionId=data.editions[0].work_versions[id];
    const version=work?.versions.find(v=>v.version_id===versionId);if(!work||!version)throw Error('missing retained fixture version');
    work.title=variant.title;work.abstract=variant.abstract;version.title=variant.title;version.abstract=variant.abstract;
  }
  return data;
}
async function main(){
  await fs.mkdir(path.dirname(out),{recursive:true});await fs.mkdir(shots,{recursive:true});
  const browser=await chromium.launch();
  try {for(const theme of ['light','dark'])for(const variant of variants.filter(v=>!process.env.DENSITY_VARIANT || v.name.includes(process.env.DENSITY_VARIANT))){
    const label=`${theme}:${variant.name}`;let snapshot;
    const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:2,colorScheme:theme});
    await context.addInitScript(t=>localStorage.setItem('arxiv-agent.theme',t),theme);
    await context.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url());
      if(url.origin!==base||!['GET','HEAD'].includes(req.method())){report.blocked.push({label,case:currentCase,method:req.method(),url:url.origin+url.pathname});return route.abort('blockedbyclient')}
      if(url.pathname==='/api/workspace/state'&&variant.override){
        const response=await route.fetch();if(!response.ok())return route.fulfill({response});
        const data=await response.json();if(data.principal_key_id!=='e2e')throw Error('unexpected synthetic principal');
        snapshot=overrideState(data,variant);return route.fulfill({response,json:snapshot});
      }
      return route.continue();
    });
    const page=await context.newPage();page.on('console',m=>{if(m.type()==='error')report.consoleErrors.push({label,case:currentCase,text:m.text()})});page.on('pageerror',e=>report.pageErrors.push({label,case:currentCase,text:String(e)}));
    page.on('requestfailed',r=>{const u=new URL(r.url()),failure=r.failure()?.errorText;if(!(r.method()==='GET'&&u.origin===base&&u.searchParams.has('_rsc')&&failure==='net::ERR_ABORTED'))report.requestFailures.push({label,case:currentCase,url:r.url(),failure})});
    try{
      await check(`${label}: initial`,async()=>{
        const response=await page.goto(base+'/workspace/today',{waitUntil:'networkidle'});assert(response&&response.ok());await ready(page);
        assert.equal(await page.getByText('Design preview · synthetic sample papers',{exact:true}).count(),1);
        if(!snapshot)snapshot=await page.evaluate(async()=>{const r=await fetch('/api/workspace/state');if(!r.ok)throw Error('state unavailable');return r.json()});
        assert.equal(snapshot.principal_key_id,'e2e');assert.equal(snapshot.editions[0].work_ids.length,9);
        const result=await measure(page,variant,'initial');await page.screenshot({path:path.join(shots,`${theme}-${variant.name}-initial.png`),fullPage:false});return result;
      });
      await check(`${label}: queue change`,async()=>{
        assert(snapshot,'initial state missing');const id=snapshot.editions[0].work_ids[3];
        const work=snapshot.works.find(w=>w.work_id===id);const pinned=snapshot.editions[0].work_versions[id];const title=work.versions.find(v=>v.version_id===pinned)?.title||work.title;
        await page.getByRole('button',{name:'Queue & controls'}).click();
        await page.getByRole('button',{name:`Show paper 4 of 9: ${title}`}).click();
        await page.waitForFunction(id=>new URL(location.href).searchParams.get('focus')===id,id);
        assert.equal(await page.locator('.workspace-app').getAttribute('data-drawer'),'closed');
        assert.equal(await page.locator('article.ws-focus h3 a').innerText(),title);
        return measure(page,variant,'queue change');
      });
      await check(`${label}: Reader return`,async()=>{
        assert(snapshot,'initial state missing');const id=snapshot.editions[0].work_ids[3];
        const link=page.locator('article.ws-focus h3 a');const href=new URL(await link.getAttribute('href'),base);
        assert.equal(href.searchParams.get('version'),snapshot.editions[0].work_versions[id]);
        assert(new URL(href.searchParams.get('return_to'),base).searchParams.get('focus')===id);
        const anchor=href.hash;assert(anchor,'Reader link must retain an anchor');
        await link.click();await page.waitForURL(u=>u.pathname.startsWith('/workspace/items/'));
        assert.equal(new URL(page.url()).hash,anchor);
        await page.getByRole('link',{name:/← Today/}).first().click();await page.waitForURL(u=>u.pathname==='/workspace/today'&&u.searchParams.get('focus')===id);await ready(page);
        return measure(page,variant,'Reader return');
      });
    }finally{await page.waitForLoadState('networkidle',{timeout:30000});await context.close()}
  }}finally{await browser.close()}
}
main().catch(e=>report.cases.push({name:'audit execution',status:'fail',error:String(e.stack||e)})).finally(async()=>{await fs.writeFile(out,JSON.stringify(report,null,2)+'\n');const failed=report.cases.filter(x=>x.status==='fail');console.log(JSON.stringify({out,cases:report.cases.length,failed:failed.length,blocked:report.blocked.length,consoleErrors:report.consoleErrors.length,pageErrors:report.pageErrors.length,requestFailures:report.requestFailures.length,failures:failed.map(x=>({name:x.name,error:x.error.split('\n')[0]}))},null,2));if(failed.length||report.blocked.length||report.consoleErrors.length||report.pageErrors.length||report.requestFailures.length)process.exitCode=1});
