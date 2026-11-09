import { expect, test } from '@playwright/test';

import { DOCUMENT, Workspace } from './support/workspace';

/**
 * Maps to `editor-shell` / "Narrow viewport": below 1366px the workspace collapses to one pane plus a
 * tablist, and the audit must still be reachable (the contract is about layout, not about features
 * disappearing). Runs in the `narrow` project (iPhone 13, 390×844).
 */
test('narrow viewport shows one pane plus tabs, and the audit still runs', async ({ page }) => {
  await page.goto('/');

  const tabs = page.getByRole('tablist', { name: 'Workspace panes' });
  await expect(tabs).toBeVisible();
  await expect(page.locator('section[aria-label="Document editor"]')).toBeVisible();
  await expect(page.locator('aside[aria-label="AI assistant"]')).toHaveCount(0);

  // Only the active pane is mounted, so switching really does hide the previous one.
  await page.getByRole('tab', { name: 'AI assistant' }).click();
  await expect(page.locator('aside[aria-label="AI assistant"]')).toBeVisible();
  await expect(page.locator('section[aria-label="Document editor"]')).toHaveCount(0);

  // Full audit still works from the narrow layout.
  await page.getByRole('tab', { name: 'Document' }).click();
  const ws = new Workspace(page);
  await ws.paste(DOCUMENT);
  await page.getByRole('tab', { name: 'AI assistant' }).click();
  await ws.runAudit();
  await expect(ws.result()).toHaveAttribute('data-field-checks', 'ran');
});