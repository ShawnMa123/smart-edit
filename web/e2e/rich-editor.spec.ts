import { expect, test } from '@playwright/test';

/**
 * `rich-text-editor` scenarios that need a real browser: the toolbar state, table commands, and the
 * literal find/replace panel. The audit input is inspected directly: only the plain-text projection
 * may cross the boundary, never TipTap markup.
 */
test.describe('rich editor surface', () => {
  test('formats headings and marks, and the audit receives plain text only', async ({ page }) => {
    const bodies: string[] = [];
    page.on('request', (request) => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/runs') {
        bodies.push(request.postData() ?? '');
      }
    });

    await page.goto('/');
    const editor = page.locator('[data-testid="editor-rich"] .ProseMirror');
    await editor.fill('Demand Guarantee');
    await editor.press('Control+a');
    await page.getByRole('button', { name: 'Heading 1' }).click();
    await expect(editor.locator('h1')).toContainText('Demand Guarantee');

    await editor.press('Control+a');
    await page.getByRole('button', { name: 'Bold' }).click();
    await expect(editor.locator('h1 strong')).toContainText('Demand Guarantee');

    await page.getByRole('button', { name: 'Run spec audit' }).click();
    await expect(page.getByTestId('audit-result')).toBeVisible();

    expect(bodies).toHaveLength(1);
    const submitted = JSON.parse(bodies[0]) as { text: string };
    expect(submitted.text.trimEnd()).toBe('# Demand Guarantee');
    expect(submitted.text).not.toContain('<h1');
    expect(submitted.text).not.toContain('bold');
  });

  test('find and replace treats the term literally and keeps the surrounding text', async ({ page }) => {
    await page.goto('/');
    const editor = page.locator('[data-testid="editor-rich"] .ProseMirror');
    await editor.fill('a.*b (x) [y] a.*b');

    await page.getByRole('button', { name: 'Find and replace' }).click();
    await page.getByRole('textbox', { name: 'Find', exact: true }).fill('a.*b');
    await expect(page.getByTestId('find-status')).toContainText('1 / 2');

    await page.getByRole('textbox', { name: 'Replace with' }).fill('LITERAL');
    await page.getByRole('button', { name: 'Replace all', exact: true }).click();
    await expect(editor).toHaveText('LITERAL (x) [y] LITERAL');
  });

  test('inserts a table and exposes row/column commands', async ({ page }) => {
    await page.goto('/');
    const editor = page.locator('[data-testid="editor-rich"] .ProseMirror');
    await editor.fill('Table host');

    await page.getByRole('button', { name: 'Insert table' }).click();
    await expect(editor.locator('table')).toHaveCount(1);
    await expect(editor.locator('table tr')).toHaveCount(2);

    await page.getByRole('button', { name: 'Insert row below' }).click();
    await expect(editor.locator('table tr')).toHaveCount(3);
    await page.getByRole('button', { name: 'Insert column right' }).click();
    await expect(editor.locator('table tr').first().locator('th, td')).toHaveCount(3);
    await page.getByRole('button', { name: 'Delete row' }).click();
    await expect(editor.locator('table tr')).toHaveCount(2);
    await page.getByRole('button', { name: 'Delete column' }).click();
    await expect(editor.locator('table tr').first().locator('th, td')).toHaveCount(2);
  });
});
