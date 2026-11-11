import { expect, test } from '@playwright/test';

/**
 * `agent-regulatory` / 从原始文件启动: the legal tab can create its own run and trigger Agent 3
 * without a prior audit, and it renders coverage/citations rather than a legal conclusion.
 */
test('the legal tab runs without an audit and shows coverage or an honest failure', async ({
  page,
}) => {
  await page.goto('/');
  const editor = page.locator('[data-testid="editor-rich"] .ProseMirror');
  await editor.fill('DEMAND GUARANTEE\nAmount: USD 500,000.00\nApplicant: Alpha Tech Pte Ltd');

  await page.getByRole('tab', { name: 'Legal advice' }).click();
  await expect(page.getByTestId('legal-panel')).toBeVisible();
  await page.getByRole('button', { name: 'Run legal check' }).click();

  // Either a report (coverage/citations) or an explicit failure is acceptable; a silent clean
  // result is not. The local index should normally produce a report.
  await expect(
    page.getByTestId('legal-coverage').or(page.getByRole('alert').filter({ hasText: 'Legal check failed' })),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Not a legal opinion/i)).toBeVisible();
});
