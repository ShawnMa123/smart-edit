import { expect, test } from '@playwright/test';

/** Task 14.5 - a blank can be filled, and typing does not jump the caret to the last line. */

const SAMPLE = new URL(
  '../../fixtures/imports/guarantee-and-standby-letters-of-credit-wording.pdf',
  import.meta.url,
).pathname;

test('a PDF blank accepts text without jumping to the last line', async ({ page }) => {
  await page.goto('/');
  await page.setInputFiles('[data-testid="import-file-input"]', SAMPLE);
  await page.getByRole('button', { name: 'Use this text' }).click();

  const editor = page.locator('[data-testid="editor-rich"]');
  await expect(editor).toContainText('Beneficiary:');

  const row = editor.locator('[data-pdf-row="true"]').filter({ hasText: 'Beneficiary:' }).first();
  const gap = row.locator('.pdf-gap--rule').last();
  await gap.click();
  await page.keyboard.type('ACME Trading');

  // The text landed inside the underlined blank, not at the end of the document.
  await expect(gap).toContainText('ACME Trading');
  await expect(row).toContainText('Beneficiary:');
  const lastBlock = editor.locator('[data-pdf-row], p, h1, h2, h3').last();
  await expect(lastBlock).not.toContainText('ACME Trading');
});