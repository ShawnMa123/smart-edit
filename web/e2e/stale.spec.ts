import { expect, test } from '@playwright/test';

import { DOCUMENT, Workspace } from './support/workspace';

/**
 * Maps to `editor-shell` / "Document edited after a report", "Stale results are still readable",
 * "Digest changes with content".
 */
test('editing after a report marks it stale but keeps it readable', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();
  await ws.paste(DOCUMENT);
  await ws.runAudit();

  await expect(ws.result()).toHaveAttribute('data-stale', 'false');
  await expect(page.getByText('33 of 51 planned checks assessed')).toBeVisible();
  await expect(ws.staleAlert()).toHaveCount(0);

  // One character is enough: the snapshot digest is what the report is bound to.
  await ws.paste(`${DOCUMENT} `);

  await expect(ws.staleAlert()).toBeVisible();
  await expect(ws.staleAlert()).toContainText('Report is stale');
  await expect(ws.result()).toHaveAttribute('data-stale', 'true');

  // The stale report stays on screen — deleting it would lose the operator's context — but the
  // numbers must no longer be presented as a judgement about the current text.
  await expect(ws.ruleAudit()).toHaveAttribute('data-ran', 'true');
  await expect(page.getByText('It cannot be used for approval')).toBeVisible();
});