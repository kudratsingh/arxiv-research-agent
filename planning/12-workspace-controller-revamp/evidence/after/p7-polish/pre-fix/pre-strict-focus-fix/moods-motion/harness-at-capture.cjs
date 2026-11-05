// Captured synthetic state variants. Software-only UI evidence; no backend mutations.
const {chromium,expect}=require('@playwright/test'),fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const base='http://127.0.0.1:3168',principal='controller-p7-preview',out=path.resolve('planning/12-workspace-controller-revamp/evidence/after/p7-polish/final/moods-motion');
const report={startedAtUtc:new Date().toISOString(),base,principal,scope:'Injected latency/outage/empty states from captured synthetic preview state; no source or service reliability claim',cases:[],blocked:[],errors:[]};
const persisted=({as_of,...state})=>state;
(async()=>{await fs.mkdir(out,{recursive:true});const browser=await chromium.launch();try{
 for(const[size,width,height]of[['desktop',1440,1000],['mobile',390,844]])for(const theme of['light','dark'])for(const reducedMotion of['no-preference','reduce']){
  const name=`${size}-${theme}-${reducedMotion}`,context=await browser.newContext({viewport:{width,height},colorScheme:theme,isMobile:width===390,hasTouch:width===390,reducedMotion,deviceScaleFactor:2});
  const before=await(await context.request.get(base+'/api/workspace/state')).json();assert.equal(before.principal_key_id,principal);assert.equal(before.schedule.enabled,false);
  let scenario='busy',release;const held=new Promise(resolve=>release=resolve);const injected=[];
  await context.addInitScript(()=>{window.__paperAnimations=[];const original=Element.prototype.animate;Element.prototype.animate=function(frames,options){if(this.matches('article.ws-focus'))window.__paperAnimations.push({options,frames});return original.call(this,frames,options);};});
  await context.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());if(u.origin!==base||!['GET','HEAD'].includes(req.method())||/^\/api\/workspace\/(refresh|synthesis|generation|jobs|manual|import)/.test(u.pathname)){report.blocked.push({name,method:req.method(),path:u.origin+u.pathname});return route.abort('blockedbyclient');}
   if(u.pathname==='/api/workspace/state'){
    injected.push({scenario,path:u.pathname,forwarded:false});
    if(scenario==='busy')await held;
    if(scenario==='outage')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'P7 explicitly intercepted software-only outage'})});
    const state=scenario==='empty'?{...before,works:[],editions:[],activity:[],latest_activity:null}:before;
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(state)});
   }return route.continue();});
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push({name,error:String(e)}));
  const evidence=[];
  const capture=async mood=>{
   const target=page.locator(`main .ws-mascot-wrap[data-mood="${mood}"]`).first();await target.waitFor();assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
   const motion=await page.evaluate(()=>Array.from(document.querySelectorAll('.workspace-app .ws-mascot,.workspace-app .ws-mascot *,.workspace-app .ws-equalizer i')).map(el=>({class:el.getAttribute('class'),mood:el.getAttribute('data-mood'),animation:getComputedStyle(el).animationName})).filter(row=>row.animation!=='none'));
   if(reducedMotion==='reduce')assert.deepEqual(motion,[],'Reduced-motion CSS animations remained active');
   const mode=mood==='busy'?'busy':mood==='alert'?'outage':'empty';await page.screenshot({path:path.join(out,`${name}-${mode}.png`)});evidence.push({mode,mood,animated:motion,screenshot:`${name}-${mode}.png`});
  };
  try{
   await page.goto(base+'/workspace/today',{waitUntil:'domcontentloaded'});await capture('busy');
   release();await page.locator('article.ws-focus').waitFor();await page.getByRole('button',{name:'Next paper',exact:true}).click();
   await expect(page.getByRole('progressbar',{name:'Reading queue progress'})).toHaveAttribute('value','2');
   const paperAnimations=await page.evaluate(()=>window.__paperAnimations);if(reducedMotion==='reduce')assert.equal(paperAnimations.length,0,'Reduced-motion article animation called');else assert(paperAnimations.some(a=>a.options.duration===170),'Expected170ms paper animation');
   scenario='outage';await page.reload({waitUntil:'networkidle'});await expect(page.locator('main h1')).toHaveText('Workspace unavailable');await capture('alert');
   scenario='empty';await page.reload({waitUntil:'networkidle'});await expect(page.getByRole('heading',{name:'Make your first bounded check.'})).toBeVisible();await capture('sleepy');
   const after=await(await context.request.get(base+'/api/workspace/state')).json();assert.deepEqual(persisted(after),persisted(before));
   report.cases.push({name,status:'pass',evidence,paperAnimations,injected,serverStateUnchanged:true});console.log('PASS',name);
  }catch(e){report.cases.push({name,status:'fail',error:String(e.stack||e),evidence,injected});await page.screenshot({path:path.join(out,name+'-failure.png')}).catch(()=>{});console.log('FAIL',name,String(e));}
  finally{release();await context.close();await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');}
 }
}finally{await browser.close();}})().catch(e=>report.errors.push({kind:'fatal',error:String(e.stack||e)})).finally(async()=>{report.endedAtUtc=new Date().toISOString();report.status=report.cases.length===8&&report.cases.every(c=>c.status==='pass')&&!report.blocked.length&&!report.errors.length?'pass':'fail';await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,cases:report.cases.length,blocked:report.blocked,errors:report.errors}));if(report.status!=='pass')process.exitCode=1;});
