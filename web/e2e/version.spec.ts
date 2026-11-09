import { expect, test } from '@playwright/test';

/** `editor-shell` / version history: capture is append-only, restore only reads, clear removes. */
test('captures a version, edits, and restores the captured text without rewriting history', async ({
  page,
}) => {
  await page.goto('/');
  const editor = page.locator('[data-testid="editor-rich"] .ProseMirror');
  await editor.fill('Original guarantee text');

  await page.getByRole('button', { name: 'Capture version' }).click();
  await expect(page.locator('header.document-head')).toContainText('1 captured version');
  await expect(page.locator('aside[aria-label="Version history"]')).toContainText('23 chars');

  await editor.fill('Edited text that must not be restored automatically');
  await page.getByRole('button', { name: 'Capture version' }).click();
  await expect(page.locator('header.document-head')).toContainText('2 captured versions');

  // The newest entry is first; restore the older one.
  await page.getByRole('button', { name: 'Restore into editor' }).last().click();
  await expect(editor).toHaveText('Original guarantee text');
  await expect(page.getByText('Unsaved changes')).toBeVisible();

  // Restore is a read: both captured versions still exist.
  await expect(page.locator('header.document-head')).toContainText('2 captured versions');
  await page.getByRole('button', { name: 'Clear version history' }).click();
  await expect(page.locator('aside[aria-label="Version history"]')).toContainText('No versions yet');
});
