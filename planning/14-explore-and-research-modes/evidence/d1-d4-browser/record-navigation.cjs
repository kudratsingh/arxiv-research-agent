'use strict';
// Supplementary, untrimmed motion capture. Existing acceptance receipts remain immutable.
const fs=require('node:fs/promises'),path=require('node:path'),cp=require('node:child_process'),crypto=require('node:crypto');
const {chromium}=require('@playwright/test');
const {ROOT,APP,Guard,assert,expect,settled,focusedClearance,sha}=require('./support.cjs');
(async()=>{
 const receipt=JSON.parse(await fs.readFile(path.join(ROOT,'service-receipt.json'),'utf8'));
 assert.equal(receipt.frontendBase,'http://127.0.0.1:3179');assert(/^modes-browser-r[0-9]+$/.test(receipt.principal));
 assert.equal(receipt.providerConfiguration,'local-preview-disabled');assert.equal(receipt.recurrenceEnabled,false);
 cp.execFileSync('git',['diff','--exit-code',receipt.applicationCommit,'--','src','web/app','web/components','web/lib','web/middleware.ts'],{cwd:APP});
 assert.equal((await fs.readFile(path.join(receipt.runtimeDirectory,'.next/BUILD_ID'),'utf8')).trim(),receipt.buildId);
 for(const [port,pid]of[[3179,receipt.frontendPid],[8179,receipt.apiPid]])assert(cp.execFileSync('lsof',['-nP',`-iTCP:${port}`,'-sTCP:LISTEN','-Fp'],{encoding:'utf8'}).split('\n').includes('p'+pid));
 const output=path.join(ROOT,'accepted',receipt.applicationCommit.slice(0,7),'navigation-untrimmed');await fs.mkdir(output,{recursive:true});
 const report={scope:'Supplementary actual untrimmed browser recording; no wall-clock to video seek assumption',applicationCommit:receipt.applicationCommit,buildId:receipt.buildId,startedAtUtc:new Date().toISOString(),contexts:[],errors:[],blocked:[],requests:[]};
 const guard=new Guard(receipt,report),browser=await chromium.launch();
 try{for(const[width,height]of[[1440,1000],[390,844]])for(const theme of['light','dark']){
  const name=(width===390?'mobile':'desktop')+'-'+theme,dir=path.join(output,name);await fs.mkdir(dir,{recursive:true});
  const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:2,isMobile:width===390,hasTouch:width===390,colorScheme:theme,recordVideo:{dir,size:{width,height}}});
  await guard.install(context);
  // This supplementary recording never creates or edits authored data.
  await context.route('**/api/workspace/**',async route=>{if(!['GET','HEAD'].includes(route.request().method())){report.blocked.push({reason:'supplementary recording is read-only',method:route.request().method(),url:route.request().url()});return route.abort();}await route.fallback();});
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(String(e)));
  const steps=[];const note=async(step)=>{steps.push({step,atUtc:new Date().toISOString(),url:page.url()});await page.waitForTimeout(800);};
  await page.goto(guard.base+'/workspace/today?mode=learn',{waitUntil:'networkidle'});await settled(page);await focusedClearance(page);await note('Explore initial');
  const progress=page.getByRole('progressbar',{name:'Reading queue progress'});const initial=await progress.getAttribute('value');
  await page.mouse.move(width-8,height/2);await page.mouse.wheel(0,360);await note('Native scroll into abstract');
  await page.keyboard.press('j');await expect(progress).not.toHaveAttribute('value',initial);await focusedClearance(page);await note('Next paper lands at header');
  await page.keyboard.press('j');await page.keyboard.press('k');await focusedClearance(page);await note('Rapid next/previous final selection');
  const articleTitle=await page.locator('article.ws-focus h3').innerText();await page.screenshot({path:path.join(dir,'selected-paper.png')});
  const read=page.locator('article.ws-focus h3 a');await expect(read).toHaveCount(1);await read.click();await expect(page).toHaveURL(/\/workspace\/items\//);await settled(page);await note('Exact-version Reader');
  await page.screenshot({path:path.join(dir,'reader.png')});await page.goBack({waitUntil:'networkidle'});await settled(page);await expect(page.locator('article.ws-focus h3')).toHaveText(articleTitle);await focusedClearance(page);await note('Return restores focused paper');
  const video=page.video();await context.close();const original=await video.path();const recording=path.join(dir,'navigation.webm');await fs.rename(original,recording);
  report.contexts.push({name,steps,recording:path.relative(output,recording),sha256:crypto.createHash('sha256').update(await fs.readFile(recording)).digest('hex'),visualReview:'pending frame review',status:'pass'});
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');console.log('PASS',name);
 }}finally{await browser.close();report.requests=guard.requests;report.endedAtUtc=new Date().toISOString();await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');}
 assert.equal(report.errors.length,0);assert.equal(report.blocked.length,0);
})().catch(e=>{console.error(e);process.exitCode=1;});
