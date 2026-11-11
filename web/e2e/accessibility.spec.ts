import { expect, test } from '@playwright/test';

/**
 * `editor-shell` / Keyboard operation: panes, tabs and the audit action are reachable and
 * activatable from the keyboard, and focus is visibly indicated.
 */
test('a keyboard-only operator can switch panes and run the audit', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 });
  await page.goto('/');

  // Focus the first tab, then Tab to the assistant tab and activate it with Enter.
  const tabs = page
    .getByRole('tablist', { name: 'Workspace panes' })
    .getByRole('tab');
  await tabs.first().focus();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await expect(tabs.last()).toBeFocused();
  await page.keyboard.press('Enter');

  await expect(page.locator('aside[aria-label="AI assistant"]')).toBeVisible();
  await expect(page.locator('section[aria-label="Document editor"]')).toHaveCount(0);

  // The focused element carries a visible outline, not only a colour change.
  const outline = await tabs.last().evaluate((node) => {
    const style = getComputedStyle(node);
    return { style: style.outlineStyle, width: style.outlineWidth };
  });
  expect(outline.style).not.toBe('none');

  // Reach the audit action from the keyboard and activate it.
  await page.getByRole('button', { name: 'Run spec audit' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('alert')).toContainText('Audit failed');
});

test('status text is present, not colour alone', async ({ page }) => {
  await page.goto('/');
  const editor = page.locator('[data-testid="editor-rich"] .ProseMirror');
  await editor.fill('DEMAND GUARANTEE');
  await page.getByRole('button', { name: 'Run spec audit' }).click();
  await expect(page.getByTestId('stage-row').first()).toBeVisible();

  const rows = page.getByTestId('stage-row');
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    await expect(rows.nth(index)).toContainText(/done|failed|partial|skipped|running/i);
  }
});
