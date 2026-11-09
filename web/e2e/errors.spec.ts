import { expect, test } from '@playwright/test';

import { Workspace } from './support/workspace';

/**
 * Maps to `editor-shell` / "Server refusal" and `frontend-console` / "Empty submission refused".
 * A failure must read as a failure: no conclusion, a machine-readable code, and a way to retry.
 */
test('empty submission is refused and reported as a failed audit', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open(); // textarea intentionally left empty
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
 * Maps to `editor-shell` / "Selecting an unimplemented tab": visible, labelled, and silent about
 * content — a POC must never render sample answers, findings or citations for a capability it lacks.
 */
test('unimplemented assistant tabs are labelled and render no sample output', async ({ page }) => {
  await page.goto('/');

  const tab = page.getByRole('tab', { name: /Knowledge Q&A/ });
  await expect(tab).toContainText('not implemented');
  await tab.click();

  await expect(page.getByRole('status')).toContainText('is not implemented in this build');
  await expect(page.getByRole('status')).toContainText('Only the rule audit tab is wired');
  // No fabricated output for a capability this build lacks: no run control, no audit result block.
  await expect(page.locator('[data-testid="audit-run"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="rule-audit"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="audit-result"]')).toHaveCount(0);
});