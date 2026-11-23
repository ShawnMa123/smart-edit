import { expect, test } from '@playwright/test';

/**
 * `interface-language`: the chrome speaks English, declares it, and the assistant requests the English
 * locale. Chinese *content* (document text, quoted source excerpts) is allowed and deliberately not
 * scanned — only the named chrome roots are checked.
 */
const CJK = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;

const CHROME_ROOTS = [
  'header',
  '.topbar',
  '.rail',
  '.environment-strip',
  '.pane-tabs',
  '.pane-menu',
  '.document-head',
  '.assistant-tabs',
  '.editor-status',
  '.editor-footer',
];

test('declares English and keeps the rendered chrome in English', async ({ page }) => {
  await page.goto('/');

  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  const title = await page.title();
  expect(title.trim().length).toBeGreaterThan(0);
  expect(CJK.test(title), `document title should be English: ${title}`).toBe(false);

  const chrome = await page.evaluate((roots) => {
    const parts: string[] = [];
    for (const selector of roots) {
      document.querySelectorAll(selector).forEach((node) => {
        parts.push((node as HTMLElement).innerText ?? '');
      });
    }
    return parts.join('\n');
  }, CHROME_ROOTS);

  expect(chrome.length).toBeGreaterThan(0);
  expect(CJK.test(chrome), 'chrome copy must not contain Chinese characters').toBe(false);
});

test('creates the assistant session with the English locale', async ({ page }) => {
  let sessionBody: { locale?: string } | null = null;
  page.on('request', (request) => {
    const { pathname } = new URL(request.url());
    if (request.method() === 'POST' && pathname === '/api/assistant/sessions') {
      sessionBody = request.postDataJSON() as { locale?: string };
    }
  });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Knowledge Q&A' }).click();
  await page.getByLabel('Knowledge question').fill('What can you do?');
  await page.getByRole('button', { name: 'Ask' }).click();

  await expect.poll(() => sessionBody?.locale).toBe('en');
});