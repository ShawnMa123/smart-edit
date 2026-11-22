import { chromium } from '@playwright/test';

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://59.110.213.187:8082', { waitUntil: 'networkidle' });
if (await page.getByRole('button', { name: 'Sign in' }).count()) {
  await page.getByLabel('Email').fill('applicant@atlas-trade.test');
  await page.getByLabel('Password').fill('Applicant!2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
}
await page.waitForTimeout(2500);

await page.getByRole('button', { name: 'Approval' }).first().click();
await page.getByRole('tab', { name: 'First approval' }).click();
const dialog = page.getByRole('dialog');
const row = dialog.locator('li', { hasText: 'Counterparty route check' }).first();
await row.waitFor({ timeout: 15000 });
console.log('row:', (await row.innerText()).replace(/\s+/g, ' '));

await page.getByRole('tab', { name: 'Documents' }).click();
await page.getByTestId('approval-documents').waitFor();
const docRow = page
  .getByTestId('approval-documents')
  .locator('li', { hasText: 'Counterparty route check' })
  .first();
await docRow.getByRole('button', { name: /Open/ }).click();
await page.waitForTimeout(1800);
console.log(
  'banner:',
  (await page.getByRole('region', { name: 'Approval status' }).innerText()).replace(/\s+/g, ' '),
);
console.log(
  'stepper:',
  (await page.getByRole('list', { name: 'Approval progress' }).innerText()).replace(/\s+/g, ' '),
);
await browser.close();