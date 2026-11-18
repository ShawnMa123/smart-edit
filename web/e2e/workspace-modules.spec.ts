import { expect, test } from '@playwright/test';

import { Workspace } from './support/workspace';

test('rail and top bar expose the reference modules with honest placeholders', async ({ page }) => {
  await page.goto('/');

  const rail = page.locator('.rail');
  await expect(rail).toBeVisible();
  for (const label of ['Document', 'Versions', 'Approval', 'Comments', 'People', 'Developer']) {
    await expect(rail.getByRole('button', { name: label })).toBeVisible();
  }

  await rail.getByRole('button', { name: 'People' }).click();
  const dialog = page.getByRole('dialog', { name: /Organisation & members/ });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(/not available in this build/i);
  await expect(dialog).not.toContainText(/HSBC|Alpha Tech|@/);
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await page.locator('.topbar').getByRole('button', { name: 'Developer' }).click();
  await expect(page.getByRole('dialog', { name: 'Implementation map' })).toContainText(
    /Unavailable/i,
  );
});

test('activity records a real version capture and the inbox reflects it', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();

  await page.getByRole('button', { name: 'Activity' }).click();
  await expect(page.getByRole('dialog', { name: 'Activity' })).toContainText(/No activity yet/i);
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await page.getByRole('button', { name: 'Capture version' }).click();
  await expect(page.getByLabel('1 activity entries')).toBeVisible();
  await expect(page.getByLabel('1 unread notifications')).toBeVisible();

  await page.getByRole('button', { name: 'Inbox' }).click();
  await expect(page.getByRole('dialog', { name: 'Inbox' })).toContainText('Version captured');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await expect(page.getByLabel('0 unread notifications')).toBeVisible();

  await page.getByRole('button', { name: 'Activity' }).click();
  const dialog = page.getByRole('dialog', { name: 'Activity' });
  await expect(dialog).toContainText('Version captured');
  await expect(dialog).toContainText('Browser-local activity');
  await expect(dialog).toContainText(/not a server audit trail/i);
});

test('two captured versions compare locally without creating a new version', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();

  await ws.paste('First body');
  await page.getByRole('button', { name: 'Capture version' }).click();
  await ws.paste('Second body');
  await page.getByRole('button', { name: 'Capture version' }).click();

  await page.getByRole('checkbox', { name: 'Select Version 1 for comparison' }).click();
  await page.getByRole('checkbox', { name: 'Select Version 2 for comparison' }).click();
  await page.getByRole('button', { name: 'Compare versions' }).click();

  const dialog = page.getByRole('dialog', { name: 'Version compare' });
  await expect(dialog).toContainText('First body');
  await expect(dialog).toContainText('Second body');
  await expect(dialog).toContainText(/Read-only comparison/i);

  await page.getByRole('button', { name: 'Close dialog' }).click();
  await expect(page.locator('.version')).toHaveCount(2);
});

test('editor footer locks and the honest submit dialog work', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();

  await expect(page.getByTestId('editor-status')).toContainText('lock: this session');
  await expect(page.getByRole('button', { name: 'Release lock' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Start editing' })).toBeDisabled();

  await page.getByRole('button', { name: 'Release lock' }).click();
  await expect(page.getByTestId('editor-status')).toContainText('lock: unknown');
  await expect(page.getByRole('button', { name: 'Start editing' })).toBeEnabled();

  await page.getByRole('button', { name: 'Start editing' }).click();
  await expect(page.getByTestId('editor-status')).toContainText('lock: this session');

  await page.getByRole('button', { name: 'Submit new version' }).click();
  const dialog = page.getByRole('dialog', { name: 'Submit new version' });
  await expect(dialog).toContainText('not available in this build');
  await expect(dialog).not.toContainText(/submitted|approved/i);

  await page.getByRole('button', { name: 'Capture browser-local version' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.version')).toHaveCount(1);
});

test('toolbar grouping and the comments placeholder remain reachable', async ({ page }) => {
  await page.goto('/');

  await page.getByLabel('Paragraph style').selectOption('heading-2');
  await expect(page.locator('[data-testid="editor-rich"] h2')).toHaveCount(1);

  await page.locator('.toolbar-menu summary').click();
  await page.getByRole('button', { name: 'Insert table' }).click();
  await expect(page.locator('[data-testid="editor-rich"] table')).toHaveCount(1);

  await page.locator('.document-head').getByRole('button', { name: 'Comments' }).click();
  const dialog = page.getByRole('dialog', { name: /Comments — not available/ });
  await expect(dialog).toContainText('comment service');
  await expect(dialog).not.toContainText(/HSBC|Alpha Tech|@/);
});