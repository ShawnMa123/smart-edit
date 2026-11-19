import { expect, test } from '@playwright/test';

/**
 * Maps to `editor-shell` / "Desktop viewport": ≥960px shows the three panes side by side with the
 * navigation rail, and the pane tablist does not exist. Runs in the `desktop` project (1440×900).
 */
test('three panes are visible together and no pane tabs are rendered', async ({ page }) => {
  await page.goto('/');

  await expect(page.locator('section[aria-label="Document editor"]')).toBeVisible();
  await expect(page.locator('aside[aria-label="AI assistant"]')).toBeVisible();
  await expect(
    page.locator('[data-testid="editor-rich"], [data-testid="editor-text"]').first(),
  ).toBeVisible();

  await expect(page.getByRole('tablist', { name: 'Workspace panes' })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'AI assistant' })).toHaveCount(0);
});

/**
 * Maps to `workspace-shell` / "Workspace shell provides a standing environment band" and
 * "Assistant pane uses short tabs and a separate capability label".
 */
test('the shell shows the standing environment band and keeps the assistant tabs on one row', async ({
  page,
}) => {
  await page.goto('/');

  const strip = page.locator('.environment-strip');
  await expect(strip).toBeVisible();
  await expect(strip).toContainText(/synthetic demo data/i);
  await expect(strip).not.toContainText(/does not approve or submit/i);
  await expect(strip).toContainText(/this browser/i);

  const tabs = page.getByRole('tablist', { name: 'Assistant capabilities' });
  const listBox = await tabs.boundingBox();
  expect(listBox).not.toBeNull();
  // One row: the tab list stays under 44px tall even though each tab carries a status tag.
  expect(listBox!.height).toBeLessThanOrEqual(44);

  const tabBoxes = await Promise.all(
    (await tabs.getByRole('tab').all()).map((tab) => tab.boundingBox()),
  );
  expect(tabBoxes).toHaveLength(4);
  const heights = tabBoxes.map((box) => box!.height);
  expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(4);
});