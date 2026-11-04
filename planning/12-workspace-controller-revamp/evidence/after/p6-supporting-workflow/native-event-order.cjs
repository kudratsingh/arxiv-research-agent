// Offline native browser dispatch, deliberately not fireEvent or Element.click.
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch();
  const cases = [];
  try {
    for (const cleanup of ['microtask', 'task']) {
      const page = await browser.newPage();
      await page.setContent('<button id="probe">Native event diagnostic</button>');
      await page.evaluate((cleanup) => {
        window.trace = [];
        document.addEventListener('click', (event) => {
          window.trace.push('document capture');
          const target = event.target;
          const listener = () => window.trace.push('target capture');
          target.addEventListener('click', listener, {capture: true, once: true});
          const remove = () => {
            window.trace.push(`${cleanup} cleanup`);
            target.removeEventListener('click', listener, true);
          };
          if (cleanup === 'microtask') queueMicrotask(remove);
          else setTimeout(remove, 0);
        }, true);
      }, cleanup);
      await page.locator('#probe').click();
      await page.waitForFunction(() => window.trace.some(item => item.endsWith('cleanup')));
      const trace = await page.evaluate(() => window.trace);
      assert.equal(trace.includes('target capture'), cleanup === 'task');
      cases.push({cleanup, trace});
      await page.close();
    }
  } finally { await browser.close(); }
  const result = {mode: 'offline native event diagnostic; no application or network requests', cases};
  await fs.writeFile('planning/12-workspace-controller-revamp/evidence/after/p6-supporting-workflow/native-event-order.json', JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
})().catch(error => { console.error(error); process.exitCode = 1; });
