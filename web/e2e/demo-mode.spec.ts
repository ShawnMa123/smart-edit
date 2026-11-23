import { expect, test } from '@playwright/test';

const enableDemo = async (page: import('@playwright/test').Page) => {
  await page.goto('/');
  await page.getByRole('checkbox', { name: 'Demo data' }).check();
  await expect(page.getByText(/not real authentication or workflow/i)).toBeVisible();
  await expect(page.getByRole('button', { name: /Demo identity: Chen Rui/ })).toBeVisible();
};

const switchTo = async (page: import('@playwright/test').Page, name: string) => {
  await page.getByRole('button', { name: /Demo identity:/ }).click();
  const row = page.locator('.demo-person').filter({ hasText: name });
  await row.getByRole('button', { name: 'Switch' }).click();
  await page.getByRole('button', { name: 'Close dialog' }).click();
};

test('demo mode switches identity and People while honest mode stays neutral', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: /Local demo session/ })).toBeVisible();
  await enableDemo(page);

  await page.getByRole('button', { name: /Demo identity: Chen Rui/ }).click();
  await expect(page.getByRole('dialog', { name: 'Demo identity' })).toContainText('Emma Wong');
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await page.locator('.topbar').getByRole('button', { name: 'People' }).click();
  const people = page.getByRole('dialog', { name: 'Organisation & members' });
  await expect(people).toContainText('Alpha Tech Ltd.');
  await expect(people).toContainText('HSBC Trade Operations');
  await people.getByRole('button', { name: 'Revoke guest' }).click();
  await expect(people).toContainText('Status: revoked');
  await people.getByRole('button', { name: 'Invite external counsel' }).click();
  await expect(people).toContainText('Status: active');

  await page.getByRole('button', { name: 'Close dialog' }).click();
  await page.getByRole('checkbox', { name: 'Demo data' }).uncheck();
  await expect(page.getByRole('button', { name: /Local demo session/ })).toBeVisible();
  await expect(page.getByText(/not real authentication or workflow/i)).toHaveCount(0);
  await page.locator('.topbar').getByRole('button', { name: 'People' }).click();
  await expect(page.getByRole('dialog', { name: /Organisation & members — not available/ })).toBeVisible();
});

test('demo approval advances through both reviewers and records a simulated receipt', async ({
  page,
}) => {
  await enableDemo(page);

  await page.locator('.rail').getByRole('button', { name: 'Approval' }).click();
  const approval = page.getByRole('dialog', { name: 'Approval workflow' });
  await expect(approval).toContainText('DRAFT');
  await approval.getByRole('button', { name: 'Start approval' }).click();
  await expect(approval).toContainText('IN_REVIEW');
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await switchTo(page, 'Emma Wong');
  await page.locator('.rail').getByRole('button', { name: 'Approval' }).click();
  await page.getByRole('dialog', { name: 'Approval workflow' }).getByRole('button', { name: 'Approve' }).click();
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await switchTo(page, 'Daniel Lee');
  await page.locator('.rail').getByRole('button', { name: 'Approval' }).click();
  await page.getByRole('dialog', { name: 'Approval workflow' }).getByRole('button', { name: 'Approve' }).click();
  const approved = page.getByRole('dialog', { name: 'Approval workflow' });
  await expect(approved).toContainText('APPROVED');
  await expect(approved).toContainText(/Simulated — no external system received/i);
  await approved.getByRole('button', { name: 'Confirm sample handoff' }).click();
  await expect(approved).toContainText('HANDED_OFF');
});

test('demo comments, activity, inbox and reset stay local and separate', async ({ page }) => {
  await enableDemo(page);

  await page.locator('.document-head').getByRole('button', { name: 'Comments' }).click();
  const comments = page.getByRole('dialog', { name: 'Comments' });
  await expect(comments).toContainText('Sample data');
  await comments.getByLabel('New sample comment').fill('Sample note from e2e');
  await comments.getByRole('button', { name: 'Add sample comment' }).click();
  await expect(comments).toContainText('Sample note from e2e');
  await comments.getByRole('button', { name: 'Resolve' }).first().click();
  await expect(comments.getByText('Resolved').first()).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await expect(page.getByLabel('5 activity entries')).toBeVisible();
  await page.getByRole('button', { name: 'Activity' }).click();
  await expect(page.getByRole('dialog', { name: 'Activity' })).toContainText('Version captured');
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await page.getByRole('button', { name: 'Inbox' }).click();
  await expect(page.getByRole('dialog', { name: 'Inbox' })).toContainText('Comment added');
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await page.getByRole('button', { name: 'Reset demo data' }).click();
  await expect(page.getByText(/not real authentication or workflow/i)).toBeVisible();
  await page.getByRole('checkbox', { name: 'Demo data' }).uncheck();
  await expect(page.getByRole('button', { name: /Local demo session/ })).toBeVisible();
});