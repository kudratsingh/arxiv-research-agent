// P7 frozen-build read-only browser checks. Browser-local themes/navigation only.
const {chromium,expect}=require('@playwright/test'),AxeBuilder=require('@axe-core/playwright').default;
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const base='http://127.0.0.1:3168',principal='controller-p7-preview',id='arxiv:2611.99800';
const out=path.resolve('planning/12-workspace-controller-revamp/evidence/after/p7-polish/final/commands');
const report={base,principal,startedAtUtc:new Date().toISOString(),fixture:'synthetic offline preview; browser-local commands only',cases:[],blocked:[],errors:[],chapters:[]};
const persisted=({as_of,...state})=>state; // Response clock is generated for each GET.
async function active(page,locator){assert(await locator.evaluate(el=>el===document.activeElement),'Expected input/control focus');}
async function settled(page){await page.locator('main h1').waitFor();await page.locator('main [aria-busy="true"]').waitFor({state:'hidden',timeout:30000});}
(async()=>{await fs.mkdir(out,{recursive:true});const browser=await chromium.launch();try{
 for(const[size,width,height]of[['desktop',1440,1000],['mobile',390,844]])for(const theme of['light','dark']){
  const name=`${size}-${theme}`,record=(size==='desktop'&&theme==='dark')||(size==='mobile'&&theme==='light');
  const context=await browser.newContext({viewport:{width,height},colorScheme:theme,isMobile:width===390,hasTouch:width===390,deviceScaleFactor:2,...(record?{recordVideo:{dir:path.join(out,'raw-video'),size:{width,height}}}:{})});
  await context.route('**/*',route=>{const req=route.request(),u=new URL(req.url());if(u.origin!==base||!['GET','HEAD'].includes(req.method())||/^\/api\/workspace\/(refresh|synthesis|generation|jobs|manual|import)/.test(u.pathname)){report.blocked.push({name,method:req.method(),path:u.origin+u.pathname});return route.abort('blockedbyclient');}return route.continue();});
  const page=await context.newPage(),video=page.video(),start=Date.now();
  page.on('pageerror',e=>report.errors.push({name,error:String(e)}));page.on('console',m=>{if(m.type()==='error')report.errors.push({name,error:m.text()});});
  const chapter=label=>report.chapters.push({name,label,elapsedMs:Date.now()-start});
  try{
   const before=await(await context.request.get(base+'/api/workspace/state')).json();assert.equal(before.principal_key_id,principal);assert.equal(before.schedule.enabled,false);
   await page.goto(base+`/workspace/today?focus=${encodeURIComponent(id)}`,{waitUntil:'networkidle'});await settled(page);assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
   if(size==='mobile'){
    const toggle=page.getByRole('button',{name:'Queue & controls',exact:true});await toggle.click();const drawer=page.getByRole('dialog',{name:'Queue & controls',exact:true});await drawer.waitFor();await expect(page.locator('main')).toHaveAttribute('inert','');for(let i=0;i<8;i++){await page.keyboard.press('Tab');assert(await drawer.evaluate(el=>el.contains(document.activeElement)),'Tab escaped mobile drawer');}for(let i=0;i<8;i++){await page.keyboard.press('Shift+Tab');assert(await drawer.evaluate(el=>el.contains(document.activeElement)),'ReverseTab escaped mobile drawer');}await page.keyboard.press('Control+k');assert.equal(await page.getByRole('dialog',{name:'Commands',exact:true}).count(),0,'Palette opened over controls modal');await page.keyboard.press('Escape');await drawer.waitFor({state:'hidden'});await expect(toggle).toBeFocused();chapter('Mobile drawer focus trap and modal ownership');
   }
   if(size==='desktop'){
    await page.getByRole('button',{name:'Collapse sidebar',exact:true}).click();await expect(page.locator('.workspace-app')).toHaveAttribute('data-rail','true');await page.keyboard.press('Control+k');const railDialog=page.getByRole('dialog',{name:'Commands',exact:true});await railDialog.waitFor();await page.getByRole('combobox',{name:'Find a command'}).fill('time');await expect(railDialog.getByRole('option')).toHaveCount(0);await page.keyboard.press('Escape');await page.getByRole('button',{name:'Expand sidebar',exact:true}).click();await expect(page.locator('.workspace-app')).toHaveAttribute('data-rail','false');chapter('Collapsed rail excludes hidden page commands');
   }
   const trigger=page.getByRole('button',{name:'Open command palette',exact:true});await trigger.click();
   const dialog=page.getByRole('dialog',{name:'Commands',exact:true}),search=page.getByRole('combobox',{name:'Find a command'});await dialog.waitFor();await active(page,search);chapter('Palette open with focused combobox');
   const modalPosition=await page.getByRole('progressbar',{name:'Reading queue progress'}).getAttribute('value'),modalUrl=page.url();
   await page.keyboard.press('Shift+Tab');await active(page,dialog.getByRole('button',{name:/^Close/}));
   for(const key of ['s','d','j','1','2','3'])await page.keyboard.press(key);
   assert.equal(page.url(),modalUrl);assert.equal(await page.getByRole('progressbar',{name:'Reading queue progress'}).getAttribute('value'),modalPosition);await page.keyboard.press('Tab');await active(page,search);chapter('Palette Close plain keys remained inside modal');
   const paletteAxe=(await new AxeBuilder({page}).analyze()).violations;assert.equal(paletteAxe.length,0,JSON.stringify(paletteAxe.map(v=>v.id)));
   const options=dialog.getByRole('option'),count=await options.count();assert(count>=12,'Expected full available command registry');
   const scrollChecks=[];
   for(let i=0;i<count+2;i++){
    await page.keyboard.press('ArrowDown');await active(page,search);
    const activeId=await search.getAttribute('aria-activedescendant');assert(activeId);
    const g=await page.locator(`[id="${activeId}"]`).evaluate(el=>{const r=el.getBoundingClientRect(),pane=el.closest('[role="listbox"]').getBoundingClientRect();return{top:r.top,bottom:r.bottom,paneTop:pane.top,paneBottom:pane.bottom,height:r.height,selected:el.getAttribute('aria-selected')};});
    assert(g.top>=g.paneTop-1&&g.bottom<=g.paneBottom+1,`Offscreen active option ${JSON.stringify(g)}`);assert.equal(g.selected,'true');assert(g.height>=44);scrollChecks.push(g);
   }
   await page.screenshot({path:path.join(out,name+'-palette.png')});chapter('Arrow navigation retained input focus and visible active option');
   for(let i=0;i<6;i++){await page.keyboard.press('Tab');assert(await dialog.evaluate(el=>el.contains(document.activeElement)),'Tab escaped modal');}for(let i=0;i<6;i++){await page.keyboard.press('Shift+Tab');assert(await dialog.evaluate(el=>el.contains(document.activeElement)),'ShiftTab escaped modal');}
   await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});await active(page,trigger);
   await page.keyboard.press('Control+k');await dialog.waitFor();await search.fill('zzzz-no-command');await expect(dialog.getByText('No available commands match. Try another search.',{exact:true})).toBeVisible();assert.equal(await options.count(),0);
   await page.keyboard.press('Escape');await active(page,trigger);
   await page.keyboard.press('Meta+k');await dialog.waitFor();await search.fill('Go to Library');await expect(options).toHaveCount(1);await page.keyboard.press('Enter');await page.waitForURL('**/workspace/library');await settled(page);await expect(page.locator('main h1')).toHaveText('Library');chapter('Filtered Enter dispatched Library once');
   await page.goto(base+`/workspace/today?focus=${encodeURIComponent(id)}`,{waitUntil:'networkidle'});await settled(page);
   await page.locator('main').focus();await page.keyboard.press('?');const shortcuts=page.getByRole('dialog',{name:'Keyboard shortcuts',exact:true});await shortcuts.waitFor();
   await active(page,shortcuts.getByRole('button',{name:/^Close/}));const helpUrl=page.url(),helpPosition=await page.getByRole('progressbar',{name:'Reading queue progress'}).getAttribute('value');for(const key of ['s','d','j','1','2','3'])await page.keyboard.press(key);assert.equal(page.url(),helpUrl);assert.equal(await page.getByRole('progressbar',{name:'Reading queue progress'}).getAttribute('value'),helpPosition);chapter('Help Close plain keys remained inside modal');
   await page.keyboard.press('Tab');await active(page,shortcuts.getByRole('button',{name:/^Close/}));await page.keyboard.press('Shift+Tab');await active(page,shortcuts.getByRole('button',{name:/^Close/}));const shortcutsAxe=(await new AxeBuilder({page}).analyze()).violations;assert.equal(shortcutsAxe.length,0,JSON.stringify(shortcutsAxe.map(v=>v.id)));await page.screenshot({path:path.join(out,name+'-shortcuts.png')});await page.keyboard.press('Escape');chapter('Shortcuts dialog and Escape');
   await page.goto(base+`/workspace/today?focus=${encodeURIComponent(id)}`,{waitUntil:'networkidle'});await settled(page);await page.locator('main').focus();await page.keyboard.press('/');
   const composer=page.getByRole('searchbox',{name:'Search stored papers'});await expect(composer).toBeFocused();await composer.fill('/s');const suggestions=page.getByRole('region',{name:'Available local commands'});await suggestions.waitFor();const first=await suggestions.getByRole('button').first().innerText();assert(/save/i.test(first),`/s Enter mismatch: ${first}`);await page.screenshot({path:path.join(out,name+'-slash.png')});
   await page.keyboard.press('Control+k');await dialog.waitFor();await search.fill('Next paper');await expect(options).toHaveCount(1);await page.keyboard.press('Enter');await expect(page.getByRole('progressbar',{name:'Reading queue progress'})).toHaveAttribute('value','2');
   const saveLabel=()=>page.locator('[data-command="save"]').evaluate(el=>el.getAttribute('aria-label')||el.textContent.trim());
   await expect.poll(()=>suggestions.getByRole('button').first().locator('span').first().innerText()).toBe(await saveLabel());chapter('Slash row updates after palette changes current paper');await composer.fill('/prev');await composer.press('Enter');await expect(page.getByRole('progressbar',{name:'Reading queue progress'})).toHaveAttribute('value','1');
   await composer.fill('/r');await expect(suggestions.getByText('No available command matches.',{exact:true})).toBeVisible();
   const progress=page.getByRole('progressbar',{name:'Reading queue progress'}),initial=await progress.getAttribute('value');await composer.fill('j');assert.equal(await progress.getAttribute('value'),initial,'Typing j changed paper');
   await composer.fill('/next');await expect(suggestions.getByRole('button').first()).toContainText('Next paper');await composer.press('Enter');await expect(progress).not.toHaveAttribute('value',initial);const next=await progress.getAttribute('value');assert.equal(Number(next),Number(initial)+1);chapter('Slash suggestions and submitted Next agree; typing guard');
   await composer.fill(`/theme ${theme==='light'?'dark':'light'}`);await composer.press('Enter');await expect(page.locator('html')).toHaveAttribute('data-theme',theme==='light'?'dark':'light');await composer.fill(`/theme ${theme}`);await composer.press('Enter');await expect(page.locator('html')).toHaveAttribute('data-theme',theme);chapter('Local theme commands restored original theme');
   await composer.fill('');await composer.press('Escape');await page.keyboard.press('j');await expect(progress).toHaveAttribute('value',String(Number(next)+1));chapter('Ordinary J works again after modal dismissal');
   const reviewBefore=(await(await context.request.get(base+'/api/workspace/review')).json()).packet;assert.equal(reviewBefore.labelled_count,0);assert.equal(reviewBefore.items.length,10);
   await page.goto(base+'/workspace/review?packet='+reviewBefore.id,{waitUntil:'networkidle'});await settled(page);
   for(const kind of ['palette','shortcuts']){
    await page.locator('main').focus();await page.keyboard.press(kind==='palette'?'Control+k':'?');
    const modal=page.getByRole('dialog',{name:kind==='palette'?'Commands':'Keyboard shortcuts',exact:true});await modal.waitFor();if(kind==='palette')await page.keyboard.press('Shift+Tab');await active(page,modal.getByRole('button',{name:/^Close/}));
    for(const key of ['1','2','3','s','d','j'])await page.keyboard.press(key);
    assert.equal(await page.locator('main input[type="radio"]:checked').count(),0,'Modal changed a review judgment');const saveJudgments=page.getByRole('button',{name:/Save judgment for candidate/});assert.equal(await saveJudgments.count(),10);assert.equal(await saveJudgments.evaluateAll(els=>els.filter(el=>!el.disabled).length),0,'Modal enabled Save judgment');assert.deepEqual(await page.locator('main textarea').evaluateAll(els=>els.map(el=>el.value)),Array(10).fill(''));
    await page.keyboard.press('Escape');await modal.waitFor({state:'hidden'});
   }
   const reviewAfter=(await(await context.request.get(base+'/api/workspace/review')).json()).packet;assert.deepEqual(reviewAfter,reviewBefore);chapter('Review modal keys left all ten judgments and reasons blank');
   const after=await(await context.request.get(base+'/api/workspace/state')).json();assert.deepEqual(persisted(after),persisted(before));
   report.cases.push({name,status:'pass',theme,options:count,scrollChecks,paletteAxe:[],shortcutsAxe:[],stateUnchanged:true,video:record?name+'.webm':null});console.log('PASS',name);
  }catch(e){report.cases.push({name,status:'fail',error:String(e.stack||e),video:record?name+'.webm':null});await page.screenshot({path:path.join(out,name+'-failure.png')}).catch(()=>{});console.log('FAIL',name,String(e));}
  finally{await context.close();if(video)await video.saveAs(path.join(out,name+'.webm'));await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');}
 }
}finally{await browser.close();}})().catch(e=>report.errors.push({kind:'fatal',error:String(e.stack||e)})).finally(async()=>{report.endedAtUtc=new Date().toISOString();report.status=report.cases.length===4&&report.cases.every(c=>c.status==='pass')&&!report.blocked.length&&!report.errors.length?'pass':'fail';await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,cases:report.cases.length,blocked:report.blocked,errors:report.errors}));if(report.status!=='pass')process.exitCode=1;});
