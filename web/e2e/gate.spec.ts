import { expect, test } from '@playwright/test';

import { DOCUMENT, Workspace } from './support/workspace';

/**
 * `rule-audit` / The gate answers per protected operation. The audit itself leaves the gate
 * "not-asked"; an explicit question produces exactly one decision and it is stored on the run.
 */
test('asking the gate returns one decision and the panel records it', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();
  await ws.paste(DOCUMENT);
  await ws.runAudit();

  await expect(ws.gate()).toHaveAttribute('data-decision', 'not-asked');

  await page.getByLabel('Gate operation').selectOption('save_draft');
  await page.getByTestId('gate-ask').click();

  await expect(ws.gate()).not.toHaveAttribute('data-decision', 'not-asked');
  const decision = await ws.gate().getAttribute('data-decision');
  expect(['allowed', 'blocked', 'indeterminate']).toContain(decision);
  await expect(ws.gate()).toContainText(/allowed|blocked|indeterminate/i);
});

test('a stale report cannot be turned into an allowed decision', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();
  await ws.paste(DOCUMENT);
  await ws.runAudit();
  await expect(ws.result()).toHaveAttribute('data-stale', 'false');

  await ws.paste(`${DOCUMENT} `);
  await expect(ws.staleAlert()).toBeVisible();

  await expect(page.getByTestId('gate-ask')).toBeDisabled();
  await expect(ws.gate()).toHaveAttribute('data-decision', 'not-asked');
});