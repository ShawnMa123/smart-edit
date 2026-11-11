import { expect, test } from '@playwright/test';

/**
 * Maps to `editor-shell` / "Desktop viewport": ≥1366px shows the three panes side by side, and the
 * pane tablist does not exist. Runs in the `desktop` project (1440×900) — Playwright's default
 * 1280×720 is *narrow* in this app (`useViewport.ts` switches at ≤1365px).
 */
test('three panes are visible together and no pane tabs are rendered', async ({ page }) => {
  await page.goto('/');

  await expect(page.locator('section[aria-label="Document editor"]')).toBeVisible();
  await expect(page.locator('aside[aria-label="AI assistant"]')).toBeVisible();
  await expect(page.locator('[data-testid="editor-rich"] .ProseMirror')).toBeVisible();

  await expect(page.getByRole('tablist', { name: 'Workspace panes' })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'AI assistant' })).toHaveCount(0);
});