import { chromium } from '@playwright/test';

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on('response', (response) => {
  if (response.url().includes('/lock') && response.request().method() === 'POST') {
    console.log('LOCK', response.status(), response.url());
  }
});

await page.goto('http://59.110.213.187:8082', { waitUntil: 'networkidle' });
if (await page.getByRole('button', { name: 'Sign in' }).count()) {
  await page.getByLabel('Email').fill('bankops@atlas-trade.test');
  await page.getByLabel('Password').fill('BankOps!2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
}
await page.waitForTimeout(2500);

const select = page.getByTestId('open-document-select');
const draftValue = await select.locator('option').evaluateAll((options) => {
  const option = options.find((item) => (item.textContent || '').includes('draft'));
  return option ? option.getAttribute('value') : null;
});
console.log('draft option:', draftValue);
if (draftValue) await select.selectOption(draftValue);
await page.waitForTimeout(2500);

console.log('header:', await page.evaluate(() => document.querySelector('.document-head h1, .document-head h2')?.textContent));
console.log('editable:', await page.evaluate(() => document.querySelector('[data-testid="editor-rich"] .ProseMirror')?.getAttribute('contenteditable')));
console.log('lock label:', await page.evaluate(() => document.querySelector('[data-testid="editor-status"]')?.textContent));
console.log('start disabled:', await page.getByRole('button', { name: 'Start editing' }).isDisabled());
console.log('save disabled:', await page.getByTestId('save-draft').isDisabled());
console.log('notice:', await page.evaluate(() => document.body.innerText.match(/Read-only: [^\n]*/)?.[0] ?? null));
await browser.close();