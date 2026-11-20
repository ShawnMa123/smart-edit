import { expect, test } from '@playwright/test';

import { Workspace } from './support/workspace';

/**
 * Maps to `editor-shell` / "Server refusal" and `frontend-console` / "Empty submission refused".
 * A failure must read as a failure: no conclusion, a machine-readable code, and a way to retry.
 */
test('empty submission is refused and reported as a failed audit', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();
  await ws.clear(); // a server draft may exist; this test needs an intentionally empty editor
  await ws.runAudit();

  const failure = page.getByRole('alert');
  await expect(failure).toContainText('Audit failed — no conclusion produced');
  await expect(page.getByText('EMPTY_SUBMISSION')).toBeVisible();

  // The stage chain never started, and the panel shows no result row at all.
  expect(ws.stageCalls()).toEqual([]);
  await expect(ws.result()).toHaveCount(0);
  await expect(ws.ruleAudit()).toHaveCount(0);

  // Retry is offered from the failed state.
  await expect(page.locator('[data-testid="audit-run-again"]')).toBeVisible();
});

/**
 * Legal advice is implemented in this build (`legal-review`): the tab must say so, render the
 * statute-advice surface, and still never render an audit result or approval control.
 */
test('the legal tab renders the statute advice surface', async ({ page }) => {
  await page.goto('/');

  const tab = page.getByRole('tab', { name: 'Legal advice' });
  // The status sits in its own tag under the short label (workspace-shell / design D7).
  await expect(tab.locator('.tab-status')).toHaveText('Full');
  await expect(tab).toHaveAttribute('aria-label', 'Legal advice');
  await tab.click();

  const legalPane = page.locator('aside[aria-label="AI assistant"]');
  await expect(legalPane.getByLabel('Legal question')).toBeVisible();
  await expect(legalPane.getByRole('button', { name: 'Ask' })).toBeVisible();
  await expect(legalPane.getByText('Advisory only — backed by the statute corpus.')).toBeVisible();

  await legalPane.getByRole('tab', { name: 'Rule check' }).click();
  await expect(legalPane.getByRole('button', { name: 'Amount missing' })).toBeVisible();
  await expect(legalPane.getByRole('button', { name: 'Amount confirmed' })).toBeVisible();
  await expect(legalPane.getByRole('button', { name: 'Amount unconfirmed' })).toBeVisible();

  // The legal surface never runs the document audit or approves anything.
  await expect(page.locator('[data-testid="audit-run"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="rule-audit"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="audit-result"]')).toHaveCount(0);
});