// Read-only before/after computed form and focus evidence; no typing or saved preferences.
const {chromium}=require('playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const phase=process.argv[2],base=process.argv[3],principal=process.argv[4];
assert(['baseline','final'].includes(phase));assert(['http://127.0.0.1:3148','http://127.0.0.1:3168'].includes(base));
const out=path.resolve('planning/12-workspace-controller-revamp/evidence/after/p7-polish',phase,'form-focus');
const report={phase,base,principal,startedAtUtc:new Date().toISOString(),cases:[],blocked:[],errors:[]};
const persisted=({as_of,...state})=>state; // Response clock is generated for each GET.
(async()=>{await fs.mkdir(out,{recursive:true});const browser=await chromium.launch();try{
 for(const [size,width,height]of[['desktop',1440,1000],['mobile',390,844]])for(const theme of['light','dark']){
  const context=await browser.newContext({viewport:{width,height},colorScheme:theme,isMobile:width===390,hasTouch:width===390,deviceScaleFactor:2});
  await context.route('**/*',route=>{const req=route.request(),u=new URL(req.url());if(u.origin!==base||!['GET','HEAD'].includes(req.method())){report.blocked.push({method:req.method(),url:u.pathname});return route.abort();}return route.continue();});
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(String(e)));
  try{
   const before=await (await context.request.get(base+'/api/workspace/state')).json();assert.equal(before.principal_key_id,principal);assert.equal(before.schedule.enabled,false);
   await page.goto(base+'/workspace/interests',{waitUntil:'networkidle'});await page.locator('main h1').waitFor();
   const input=page.locator('main input:not([type="checkbox"]):not([type="radio"]):visible,main textarea:visible,main select:visible').first();
   await input.waitFor();await input.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
   assert(await input.evaluate(el=>el===document.activeElement));
   const form=await input.evaluate(el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect();return{tag:el.tagName,type:el.getAttribute('type'),label:el.labels?.[0]?.innerText||el.getAttribute('aria-label'),value:el.value,focusVisible:el.matches(':focus-visible'),font:s.font,padding:s.padding,border:s.border,borderRadius:s.borderRadius,background:s.backgroundColor,color:s.color,outline:s.outline,outlineOffset:s.outlineOffset,boxShadow:s.boxShadow,rect:{left:r.left,right:r.right,top:r.top,bottom:r.bottom}};});
   assert(form.focusVisible);assert(form.outline!=='none'&&!form.outline.includes(' 0px '));
   await page.screenshot({path:path.join(out,`${size}-${theme}-form.png`)});
   const themeState=await page.evaluate(()=>({theme:document.documentElement.dataset.theme,canvas:getComputedStyle(document.querySelector('.workspace-app')).backgroundColor}));assert.equal(themeState.theme,theme);
   const after=await (await context.request.get(base+'/api/workspace/state')).json();assert.deepEqual(persisted(after),persisted(before));
   report.cases.push({size,theme,status:'pass',themeState,form,serverStateUnchanged:true,screenshot:`${size}-${theme}-form.png`});console.log('PASS',size,theme);
  }catch(e){report.cases.push({size,theme,status:'fail',error:String(e.stack||e)});console.log('FAIL',size,theme,String(e));}
  await context.close();
 }
}finally{await browser.close();}})().catch(e=>report.errors.push(String(e.stack||e))).finally(async()=>{report.endedAtUtc=new Date().toISOString();report.status=report.cases.length===4&&report.cases.every(c=>c.status==='pass')&&!report.blocked.length&&!report.errors.length?'pass':'fail';await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,cases:report.cases.length,blocked:report.blocked,errors:report.errors}));if(report.status!=='pass')process.exitCode=1;});
