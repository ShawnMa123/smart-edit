import { expect, test } from '@playwright/test';

import { DOCUMENT, Workspace } from './support/workspace';

/**
 * Honesty path: the backend on :8010 runs **without** `SMART_EDIT_LLM`, so `extract` fails loudly.
 *
 * Maps to `editor-shell` / "Extraction did not complete" and `frontend-console` / "No provider
 * configured". The sharpest assertion here is a *negative* one: the UI must not ask for an audit when
 * the fields are placeholders — a rule audit on placeholder values would produce findings about this
 * document that are pure fiction. No unit test can prove which HTTP calls were skipped.
 */
test('no model provider: field checks did not run, and no audit is requested', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();
  await ws.paste(DOCUMENT);
  await ws.runAudit();

  await expect(ws.notRunAlert()).toBeVisible();
  await expect(ws.notRunAlert()).toContainText('Field checks did not run');
  await expect(ws.notRunAlert()).toContainText('no model provider configured');
  await expect(ws.result()).toHaveAttribute('data-field-checks', 'did-not-run');

  // The absence of a report is stated as its own claim, not as an empty (hence clean) result.
  await expect(ws.ruleAudit()).toHaveAttribute('data-ran', 'false');
  await expect(page.getByText('Rule audit did not run')).toBeVisible();

  // Placeholder fields must not be rendered as a defect list.
  await expect(page.getByText(/Not found in source/)).toHaveCount(0);

  // create → normalize only. No `/stages/audit` was ever sent.
  expect(ws.posts).toHaveLength(2);
  expect(ws.stageCalls()).toEqual(['normalize']);
});